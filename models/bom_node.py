"""
BOM节点数据模型

定义BOM树结构中的节点数据模型，包含：
- 节点基本信息
- 发运配置
- 计算结果
- 树结构关系
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BOMNode:
    """BOM节点"""

    # ========== 基本信息 ==========
    material_id: str                     # 物料号
    parent_id: str                       # 父物料号
    project_id: str = ""                 # 项目编号
    drawing_no: str = ""                 # 图号
    specification: str = ""              # 规格
    name: str = ""                       # 名称
    quantity: float = 0                  # 数量（在父物料下的用量）
    weight: float = 0                    # 净重（单个重量kg）
    level: int = 0                       # 层级深度
    seq_no: float = 0                    # 序号（装配顺序）

    # ========== 发运配置（用户维护） ==========
    expand_status: str = "是"            # 是否展开：是/否
    shipping_entity: str = ""            # 发运主体：01/02/98/99等
    shipping_method: str = ""            # 发运方式：A/B/C/D
    remark: str = ""                     # 备注

    # ========== 计算结果 ==========
    final_quantity: float = 0            # 最终数量
    total_weight: float = 0              # 总重

    # ========== 树结构关系 ==========
    children: List['BOMNode'] = field(default_factory=list)
    parent: Optional['BOMNode'] = None

    # ========== 稳定唯一标识（撤销系统用） ==========
    # 每个节点实例拥有全局唯一且生命周期内不变的 uid。
    # 撤销快照以 uid 为键，避免 (父物料号_物料号) 复合键在拆分物料、
    # 同物料多实例场景下的冲突。0 表示自动分配。
    uid: int = 0

    # 类级 uid 计数器（非 dataclass 字段，所有实例共享）
    _next_uid = 1

    def __post_init__(self):
        """初始化后处理"""
        # 分配/回填稳定唯一 uid
        if not self.uid:
            self.uid = BOMNode._next_uid
            BOMNode._next_uid += 1
        elif self.uid >= BOMNode._next_uid:
            # 从快照回填旧 uid 时，保证计数器始终领先，避免后续自动分配冲突
            BOMNode._next_uid = self.uid + 1

        # 仅在顶级节点（无父节点）时自动计算
        # 子节点的最终数量在 add_child() 设置 parent 后计算
        if self.parent is None:
            self.calculate_final_quantity()

    def calculate_final_quantity(self):
        """
        计算最终数量

        规则：
        - 顶级节点：最终数量 = 自身数量
        - 子节点：最终数量 = 自身数量 × 父节点最终数量
        """
        if self.parent is None:
            # 顶级节点
            self.final_quantity = self.quantity
        else:
            # 子节点：自身数量 × 父节点最终数量
            self.final_quantity = self.quantity * self.parent.final_quantity

        # 计算总重
        self.total_weight = self.final_quantity * self.weight

    @property
    def is_shipping_unit(self) -> bool:
        """
        是否为发运单元

        条件：
        - 是否展开 = 否
        - 发运主体不为空
        - 发运方式不为空
        """
        return (self.expand_status == "否" and
                self.shipping_entity != "" and
                self.shipping_method != "")

    @property
    def aggregation_key(self) -> str:
        """
        聚合键

        格式：物料号|发运主体|发运方式|备注
        用于GROUP BY，相同聚合键的数量会合并
        """
        return f"{self.material_id}|{self.shipping_entity}|{self.shipping_method}|{self.remark}"

    @property
    def group_sort(self) -> int:
        """
        分组排序（委托给 EntityConfigManager）

        规则：
        - 01-20：1（物理分组：机头、过渡槽、偏转槽、电缆槽、中部槽等）
        - 98：2（捆装发运类）
        - 90-97：3（自定义、液压管路、换面件、增供件）
        - 99：4（整合装箱类）
        - 00：5（特殊）
        - 其他：6
        """
        from core.entity_config import EntityConfigManager
        return EntityConfigManager.get_group_sort(self.shipping_entity)

    @property
    def method_sort(self) -> int:
        """
        组内排序（委托给 EntityConfigManager）

        规则：
        - B（打捆）：1
        - A（散装）：2
        - C（装箱）：3
        - D（特殊）：4
        - 其他：5
        """
        from core.entity_config import EntityConfigManager
        return EntityConfigManager.get_method_sort(self.shipping_method)

    def add_child(self, child: 'BOMNode'):
        """
        添加子节点

        Args:
            child: 子节点
        """
        child.parent = self
        child.level = self.level + 1
        child.project_id = self.project_id
        self.children.append(child)
        child.calculate_final_quantity()

    def get_all_descendants(self) -> List['BOMNode']:
        """
        获取所有后代节点

        Returns:
            所有后代节点列表
        """
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_all_descendants())
        return result

    def get_shipping_units(self) -> List['BOMNode']:
        """
        获取所有发运单元（排除被隐藏的节点）

        Returns:
            发运单元节点列表
        """
        units = []

        # 检查节点是否被隐藏（父节点"是否展开=否"）
        is_hidden = getattr(self, '_is_hidden', False)

        if not is_hidden and self.is_shipping_unit:
            units.append(self)

        for child in self.children:
            units.extend(child.get_shipping_units())
        return units

    def update_config(self, expand_status: str = None, shipping_entity: str = None,
                      shipping_method: str = None, remark: str = None):
        """
        更新发运配置

        Args:
            expand_status: 是否展开
            shipping_entity: 发运主体
            shipping_method: 发运方式
            remark: 备注
        """
        if expand_status is not None:
            self.expand_status = expand_status
        if shipping_entity is not None:
            self.shipping_entity = shipping_entity
        if shipping_method is not None:
            self.shipping_method = shipping_method
        if remark is not None:
            self.remark = remark

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            包含节点信息的字典
        """
        return {
            'material_id': self.material_id,
            'parent_id': self.parent_id,
            'project_id': self.project_id,
            'drawing_no': self.drawing_no,
            'specification': self.specification,
            'name': self.name,
            'quantity': self.quantity,
            'weight': self.weight,
            'level': self.level,
            'expand_status': self.expand_status,
            'shipping_entity': self.shipping_entity,
            'shipping_method': self.shipping_method,
            'remark': self.remark,
            'final_quantity': self.final_quantity,
            'total_weight': self.total_weight,
            'is_shipping_unit': self.is_shipping_unit,
            'aggregation_key': self.aggregation_key,
            'group_sort': self.group_sort,
            'method_sort': self.method_sort,
            'children_count': len(self.children)
        }

    def __repr__(self) -> str:
        """字符串表示"""
        return (f"BOMNode(material_id='{self.material_id}', name='{self.name}', "
                f"quantity={self.quantity}, final_quantity={self.final_quantity}, "
                f"level={self.level}, expand_status='{self.expand_status}')")


# ========== 辅助类 ==========

class ExpandStatus:
    """是否展开状态常量"""
    YES = "是"
    NO = "否"


class ShippingMethod:
    """发运方式常量"""
    A = "A"  # 散装
    B = "B"  # 打捆
    C = "C"  # 装箱
    D = "D"  # 特殊


# 发运主体相关函数（委托给 EntityConfigManager）
def get_entity_name(entity_code: str) -> str:
    """
    获取发运主体名称（只返回名称，不包含代码前缀）

    委托给 EntityConfigManager.get_entity_name()

    Args:
        entity_code: 发运主体代码

    Returns:
        发运主体名称（如"机头"，不是"01-机头"）
    """
    from core.entity_config import EntityConfigManager
    return EntityConfigManager.get_entity_name(entity_code)


def get_entity_display_name(entity_code: str) -> str:
    """
    获取发运主体显示名称（包含代码前缀）

    委托给 EntityConfigManager.get_entity_display_name()

    Args:
        entity_code: 发运主体代码

    Returns:
        发运主体显示名称（如"01-机头"，不是"机头"）
    """
    from core.entity_config import EntityConfigManager
    return EntityConfigManager.get_entity_display_name(entity_code)


def update_entity_name_map(entities: list):
    """
    更新发运主体名称映射

    委托给 EntityConfigManager.update_entity_name_map()

    Args:
        entities: 发运主体列表，格式为 [(code, name, desc), ...]
    """
    from core.entity_config import EntityConfigManager
    EntityConfigManager.update_entity_name_map(entities)
