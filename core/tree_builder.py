"""
树结构构建器

将平面BOM数据转换为树结构
"""

import pandas as pd
from typing import Dict, List, Optional
from pathlib import Path

from models.bom_node import BOMNode


class TreeBuilder:
    """BOM树结构构建器"""

    def __init__(self):
        self.nodes: Dict[str, BOMNode] = {}  # key: "父物料号_子物料号", value: BOMNode
        self.root: Optional[BOMNode] = None
        self.all_nodes: List[BOMNode] = []
        self.project_id: str = ""

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

        def _norm_id(val):
            """规范化物料号：去除数值型读入产生的 .0 后缀（如 12345.0 → 12345）"""
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return ''
            s = str(val).strip()
            if s.endswith('.0'):
                try:
                    return str(int(float(s)))
                except ValueError:
                    return s
            return s

        for row_idx, row in df.iterrows():
            material_id = _norm_id(row.get('子物料号', ''))
            parent_id = _norm_id(row.get('父物料号', ''))

            if not material_id:
                continue

            # 兼容"层号"和"level"列，处理带点格式（如"..3"→3）和浮点数（如2.0→2）
            raw_level = row.get('层号', row.get('level', 0))
            if pd.isna(raw_level) or str(raw_level).strip() == '':
                child_level = 0
            else:
                level_str = str(raw_level).strip()
                # 处理浮点数格式：2.0 → 2
                if level_str.endswith('.0'):
                    try:
                        child_level = int(float(level_str))
                    except ValueError:
                        child_level = 0
                else:
                    level_str = level_str.lstrip('.')
                    child_level = int(level_str) if level_str.isdigit() else 0

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

        return self.root

    def _recompute_subtree(self, node: BOMNode):
        """
        自顶向下重算子树最终数量

        先算父节点（子节点最终数量 = 自身用量 × 父节点最终数量），
        再递归子节点，确保子节点用到的是父节点已更新的最终数量。
        """
        node.calculate_final_quantity()
        for child in node.children:
            self._recompute_subtree(child)

    def load_from_file(self, file_path: str) -> BOMNode:
        """
        从文件加载BOM数据

        Args:
            file_path: 文件路径

        Returns:
            根节点
        """
        file_path = Path(file_path)

        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path, encoding='utf-8-sig')
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
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

        if file_path.suffix.lower() == '.csv':
            config_df = pd.read_csv(file_path, encoding='utf-8-sig')
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            config_df = pd.read_excel(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")

        # 应用配置
        for _, row in config_df.iterrows():
            parent_id = str(row.get('父物料号', '')).strip()
            material_id = str(row.get('物料号', '')).strip()

            # 查找节点
            for node in self.all_nodes:
                if node.material_id == material_id and node.parent_id == parent_id:
                    # 更新配置
                    if '是否展开' in row:
                        node.expand_status = str(row['是否展开']).strip()
                    if '发运主体' in row:
                        node.shipping_entity = str(row['发运主体']).strip()
                    if '发运方式' in row:
                        node.shipping_method = str(row['发运方式']).strip()
                    if '备注' in row:
                        node.remark = str(row['备注']).strip()
                    break

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
