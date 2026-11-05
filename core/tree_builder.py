"""
树结构构建器

将平面BOM数据转换为树结构
"""

import re
from decimal import Decimal, InvalidOperation

import pandas as pd
from typing import Dict, List, Optional
from pathlib import Path

from models.bom_node import BOMNode
from core.bom_parser import parse_level


def _safe_cell_text(value) -> str:
    """安全读取单元格文本：None/NaN/'nan'/'None'/'null'/空白 → 空字符串"""
    if value is None:
        return ''
    if isinstance(value, float) and pd.isna(value):
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return '' if s in ('', 'nan', 'NaN', 'None', 'null') else s


def _norm_entity_code(value) -> str:
    """规范化发运主体代码：'1.0'→'01'、'1'→'01'、'98'→'98'，非数字原样返回"""
    s = _safe_cell_text(value)
    if not s:
        return ''
    m = re.fullmatch(r'([+-]?\d+)\.0+', s)
    if m:
        s = m.group(1)
    if s.isdigit():
        return s.zfill(2)
    return s


def _norm_id(val) -> str:
    """规范化物料号：去除数值型读入产生的 .0 后缀与科学计数法表示"""
    if val is None:
        return ''
    if isinstance(val, float) and pd.isna(val):
        return ''
    try:
        if pd.isna(val):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if s == '' or s.lower() in ('nan', 'none', 'null'):
        return ''

    # 纯数字 + .0 后缀：直接截断，避免 float 转换丢失长物料号精度
    m = re.fullmatch(r'([+-]?\d+)\.0+', s)
    if m:
        return m.group(1)

    # 科学计数法（如 1.2345678901234568e+18）：用 Decimal 还原为整数串
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?[eE][+-]?\d+', s):
        try:
            d = Decimal(s)
            if d == d.to_integral_value():
                return format(d, 'f').split('.')[0]
        except (InvalidOperation, ValueError):
            pass
    return s


class TreeBuilder:
    """BOM树结构构建器"""

    def __init__(self):
        self.nodes: Dict[str, BOMNode] = {}  # key: "父物料号_子物料号", value: BOMNode
        self.root: Optional[BOMNode] = None
        self.all_nodes: List[BOMNode] = []
        self.project_id: str = ""
        # 结构校验结果（A2-1）：未挂载节点与结构问题描述，供导入/计算前提示
        self.orphan_nodes: List[BOMNode] = []
        self.structure_issues: List[str] = []
        # 配置加载时未匹配的配置行提示（A6）
        self.config_load_warnings: List[str] = []

    def build_from_dataframe(self, df: pd.DataFrame) -> BOMNode:
        """
        从DataFrame构建树结构

        Args:
            df: 包含BOM数据的DataFrame
                必需列：子物料号, 父物料号, 数量, 子物料净重, level
                可选列：图号, 规格, 名称, 是否展开, 项目编号

        Returns:
            根节点

        修复说明：
        同一个物料可能出现在多个父节点下（如 CB70299000015023 出现在 13 个
        不同父节点下）。原来的 `df[df['子物料号'] == parent_id].iloc[0]` 只取
        第一行，导致其他父实例的子节点挂载到了错误的父节点上。

        修复方法：在第一遍创建节点时，同时构建 child_key -> parent_key 的精确
        映射。通过 DataFrame 中每行的 level 信息，找到父节点所在行的 level
        （即 child_level - 1），从而精确定位父节点的 grandparent。
        """
        # 清空现有数据
        self.nodes.clear()
        self.all_nodes.clear()

        # 获取项目编号
        if '项目编号' in df.columns:
            self.project_id = df['项目编号'].iloc[0] if len(df) > 0 else ""
        else:
            self.project_id = ""

        # ---- 预处理：标记哪些物料是父节点 ----
        parent_materials = set()
        for _, row in df.iterrows():
            pid = str(row.get('父物料号', '')).strip()
            if pid:
                parent_materials.add(pid)

        # ---- 第一遍：创建所有节点，同时构建 child_key -> parent_key 精确映射 ----
        parent_key_map = {}  # child_unique_key -> parent_unique_key

        # 追踪每个物料最近一次作为父节点时的唯一 key
        last_parent_key_for = {}  # material_id -> unique_key

        node_counter = 0  # 全局唯一 ID

        for row_idx, row in df.iterrows():
            material_id = _norm_id(row.get('子物料号', ''))
            parent_id = _norm_id(row.get('父物料号', ''))

            if not material_id:
                continue

            # 复用 bom_parser.parse_level，兼容"层号"和"level"列、
            # 带点格式（如"..3"→3）以及浮点数（如 2.0→2）
            raw_level = row.get('层号', row.get('level', 0))
            child_level = parse_level(raw_level)

            # 创建节点
            def _safe_str(val):
                """安全转换：None/NaN/'null'/'None' → 空字符串"""
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return ''
                s = str(val).strip()
                return '' if s in ('', 'null', 'None', 'nan', 'NaN') else s

            node = BOMNode(
                material_id=material_id,
                parent_id=parent_id,
                project_id=self.project_id,
                drawing_no=_safe_str(row.get('图号', '')),
                specification=_safe_str(row.get('规格', '')),
                name=_safe_str(row.get('名称', '')),
                quantity=float(row.get('数量', 0)),
                weight=float(row.get('子物料净重', 0)),
                level=child_level,
                expand_status='是' if child_level == 0 else '否',  # 顶级节点默认展开
                seq_no=float(row.get('序号', 0)) if pd.notna(row.get('序号')) and str(row.get('序号', '')).strip() != '' else 0
            )

            # 使用全局唯一 ID 作为 key（避免同物料不同实例的 key 冲突）
            unique_key = f"n{node_counter}"
            node_counter += 1
            self.nodes[unique_key] = node
            self.all_nodes.append(node)

            # 父节点查找
            if not parent_id:
                parent_key_map[unique_key] = None
            else:
                parent_key = last_parent_key_for.get(parent_id)
                if parent_key is not None:
                    parent_key_map[unique_key] = parent_key
                else:
                    # 父节点是顶层节点（不在 parent_materials 中）
                    # 用 material_id 找到它的 unique_key
                    for uk, n in self.nodes.items():
                        if n.material_id == parent_id and n.level == child_level - 1:
                            parent_key_map[unique_key] = uk
                            break
                    else:
                        parent_key_map[unique_key] = None

            # 只有当该物料是父节点时才更新映射
            if material_id in parent_materials:
                last_parent_key_for[material_id] = unique_key

        # ---- 第二遍：按映射精确挂载子节点 ----
        for child_key, parent_key in parent_key_map.items():
            if parent_key is None:
                continue
            child_node = self.nodes.get(child_key)
            parent_node = self.nodes.get(parent_key)
            if child_node and parent_node and child_node is not parent_node:
                parent_node.add_child(child_node)

        # ---- 循环引用检测：父链成环时后续递归遍历会无限循环 ----
        self._raise_on_parent_cycles()

        # ---- 第三遍：按序号排序子节点 ----
        for node in self.all_nodes:
            if node.children:
                node.children.sort(key=lambda n: n.seq_no)

        # 找到根节点（level=0 或没有父节点的节点）
        for node in self.all_nodes:
            if node.level == 0 or not node.parent_id:
                self.root = node
                break

        # 建树完成后自顶向下统一重算最终数量，消除对输入行序的依赖：
        # 若 BOM 非拓扑序（子节点行排在父节点前），挂载时父节点最终数量尚未乘上
        # 祖先，子节点会算小且事后不纠正。此处统一重算保证正确。
        if self.root:
            self._recompute_subtree(self.root)

        # 建树后立即做结构校验（A2-1）：仅检测、不改动挂载算法
        self.validate_structure()

        return self.root

    def _raise_on_parent_cycles(self):
        """检测父链是否成环（正常建树不会成环，此处防御异常挂载）

        Raises:
            ValueError: 存在循环引用，描述涉及的物料号
        """
        for node in self.all_nodes:
            seen = set()
            current = node
            while current is not None:
                if id(current) in seen:
                    raise ValueError(
                        f'BOM 数据存在循环引用（物料互为父子）：{node.material_id}。'
                        '请检查父物料号与子物料号后重新导入。')
                seen.add(id(current))
                current = current.parent

    def _recompute_subtree(self, node: BOMNode, visited: Optional[set] = None):
        """
        自顶向下重算子树最终数量

        先算父节点（子节点最终数量 = 自身用量 × 父节点最终数量），
        再递归子节点，确保子节点用到的是父节点已更新的最终数量。

        visited 用于防御异常数据形成的环，避免递归无限循环。
        """
        if visited is None:
            visited = set()
        if id(node) in visited:
            return
        visited.add(id(node))
        node.calculate_final_quantity()
        for child in node.children:
            self._recompute_subtree(child, visited)

    def validate_structure(self) -> List[str]:
        """校验树结构完整性（A2-1：只检测，不改变挂载算法）

        检测内容：
        - 从 root 不可达的节点（孤儿节点，不会进入发运单）
        - 多个顶级节点（level=0 或父物料号为空）
        - 孤儿节点找不到层级为 child_level-1 的父节点（层级不匹配）

        Returns:
            结构问题描述列表（为空表示结构正常）
        """
        self.orphan_nodes = []
        issues: List[str] = []

        if not self.all_nodes:
            self.structure_issues = issues
            return issues

        reachable = set()
        if self.root:
            def walk(node):
                if id(node) in reachable:
                    return
                reachable.add(id(node))
                for child in node.children:
                    walk(child)
            walk(self.root)

        orphans = [n for n in self.all_nodes if id(n) not in reachable]
        self.orphan_nodes = orphans

        roots = [n for n in self.all_nodes if n.level == 0 or not n.parent_id]
        if len(roots) > 1:
            codes = '、'.join(n.material_id for n in roots[:10])
            issues.append(
                f'存在 {len(roots)} 个顶级节点（level=0/父物料号为空）：{codes}。'
                f'当前仅处理第一个顶级节点 {roots[0].material_id}，其余子树不会进入发运单；'
                '一个文件只能包含一个顶层产品，请拆分后再导入。')

        if orphans:
            # 按父物料号分组，便于用户定位
            groups: Dict[str, List[BOMNode]] = {}
            for node in orphans:
                groups.setdefault(node.parent_id or '（空）', []).append(node)
            parts = []
            for parent_id, group in list(groups.items())[:10]:
                parts.append(f'父物料号 {parent_id} 下 {len(group)} 个')
            issues.append(
                f'存在 {len(orphans)} 个未挂载节点（不会参与发运单计算）：'
                + '；'.join(parts)
            )

            # 层级不匹配：找不到 level = child_level - 1 的同物料父节点
            mismatched = []
            for node in orphans:
                if not node.parent_id:
                    continue
                expected_level = node.level - 1
                found = any(
                    p.material_id == node.parent_id and p.level == expected_level and p is not node
                    for p in self.all_nodes
                )
                if not found:
                    mismatched.append(node)
            if mismatched:
                sample = '、'.join(
                    f'{n.material_id}(level={n.level}, 父={n.parent_id or "空"})'
                    for n in mismatched[:10]
                )
                issues.append(f'存在 {len(mismatched)} 个层级不匹配/父节点缺失：{sample}')

        self.structure_issues = issues
        return issues

    def load_from_file(self, file_path: str) -> BOMNode:
        """
        从文件加载BOM数据

        Args:
            file_path: 文件路径

        Returns:
            根节点
        """
        file_path = Path(file_path)

        # ID 列强制字符串，避免长物料号被推断为数值丢失精度（A7）
        id_dtype = {'子物料号': str, '父物料号': str}
        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path, encoding='utf-8-sig', dtype=id_dtype)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path, dtype=id_dtype)
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")

        return self.build_from_dataframe(df)

    def load_config(self, config_file: str):
        """
        加载发运配置

        Args:
            config_file: 配置文件路径
        """
        file_path = Path(config_file)

        # ID 列强制字符串，避免 "12345.0" 之类的数值读入导致匹配失败（A6）
        id_dtype = {'父物料号': str, '物料号': str}
        if file_path.suffix.lower() == '.csv':
            config_df = pd.read_csv(file_path, encoding='utf-8-sig', dtype=id_dtype)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            config_df = pd.read_excel(file_path, dtype=id_dtype)
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")

        self.config_load_warnings = []

        # 构建 (规范化父号, 规范化物料号) -> 节点实例列表。
        # 同一父下同物料可能有多个实例（拆分物料），按配置行出现顺序消费第 n 个，
        # 不再命中第一个就 break（A6）。
        node_index: Dict[tuple, List[BOMNode]] = {}
        for node in self.all_nodes:
            key = (_norm_id(node.parent_id), _norm_id(node.material_id))
            node_index.setdefault(key, []).append(node)
        consumed: Dict[tuple, int] = {}

        # 应用配置
        for _, row in config_df.iterrows():
            parent_id = _norm_id(row.get('父物料号', ''))
            material_id = _norm_id(row.get('物料号', ''))
            key = (parent_id, material_id)

            candidates = node_index.get(key, [])
            idx = consumed.get(key, 0)
            if idx >= len(candidates):
                self.config_load_warnings.append(
                    f'未匹配到节点：父物料号={parent_id or "（空）"}，物料号={material_id or "（空）"}'
                )
                continue
            node = candidates[idx]
            consumed[key] = idx + 1

            # 更新配置：空单元格不再被写成 'nan'（A5）
            if '是否展开' in row:
                expand = _safe_cell_text(row['是否展开'])
                if expand in ('是', '否'):
                    node.expand_status = expand
            if '发运主体' in row:
                node.shipping_entity = _norm_entity_code(row['发运主体'])
            if '发运方式' in row:
                node.shipping_method = _safe_cell_text(row['发运方式'])
            if '备注' in row:
                node.remark = _safe_cell_text(row['备注'])

    def save_config(self, config_file: str):
        """
        保存发运配置

        Args:
            config_file: 配置文件路径
        """
        config_data = []

        for node in self.all_nodes:
            # 只保存有配置的节点
            if node.shipping_entity or node.shipping_method or node.expand_status == '否':
                config_data.append({
                    '项目编号': node.project_id,
                    '父物料号': node.parent_id,
                    '物料号': node.material_id,
                    '名称': node.name,
                    '是否展开': node.expand_status,
                    '发运主体': node.shipping_entity,
                    '发运方式': node.shipping_method,
                    '备注': node.remark
                })

        df = pd.DataFrame(config_data)

        file_path = Path(config_file)
        if file_path.suffix.lower() == '.csv':
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df.to_excel(file_path, index=False, engine='openpyxl')
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")

    def get_all_shipping_units(self) -> List[BOMNode]:
        """获取所有发运单元"""
        if self.root:
            return self.root.get_shipping_units()
        return []

    def get_tree_structure(self) -> List[dict]:
        """获取树结构数据（用于界面显示）"""
        if self.root:
            return self._node_to_dict(self.root)
        return []

    def _node_to_dict(self, node: BOMNode) -> List[dict]:
        """将节点转换为字典格式"""
        result = [node.to_dict()]
        result[0]['children'] = []

        for child in node.children:
            result[0]['children'].extend(self._node_to_dict(child))

        return result
