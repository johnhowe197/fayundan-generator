"""
进度文件读写模块

管理工作进度的保存和加载（Excel格式）
"""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models.bom_node import BOMNode


class ProgressFileManager:
    """进度文件管理器"""

    def __init__(self, progress_dir: Optional[Path] = None):
        """
        初始化进度文件管理器

        Args:
            progress_dir: 进度文件保存目录
        """
        if progress_dir is None:
            # 默认进度目录指向可写应用目录（打包后为 EXE 所在目录/progress），
            # 避免打包后落到临时目录导致对话框默认定位错误
            from utils.helpers import get_writable_app_dir
            progress_dir = get_writable_app_dir() / 'progress'
        self.progress_dir = Path(progress_dir)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file_path: str, nodes: List[BOMNode],
             project_info: Dict[str, str], hidden_checker=None) -> Tuple[int, int, int]:
        """
        保存工作进度到 Excel 文件

        Args:
            file_path: 文件路径
            nodes: 所有节点列表
            project_info: 项目信息字典
            hidden_checker: 隐藏状态检查函数，接收 node 返回 bool

        Returns:
            (总物料数, 可见节点数, 已隐藏节点数)
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 收集节点数据
        data = []
        visible_count = 0
        hidden_count = 0

        for node in nodes:
            is_hidden = hidden_checker(node) if hidden_checker else False
            if is_hidden:
                hidden_count += 1
            else:
                visible_count += 1

            data.append({
                '项目编号': node.project_id,
                '子物料号': node.material_id,
                '父物料号': node.parent_id,
                '图号': node.drawing_no,
                '规格': node.specification,
                '名称': node.name,
                '数量': node.quantity,
                '子物料净重': node.weight,
                '是否展开': node.expand_status,
                'level': node.level,
                '序号': node.seq_no,
                '发运主体': node.shipping_entity,
                '发运方式': node.shipping_method,
                '备注': node.remark,
                '是否隐藏': '是' if is_hidden else '否'
            })

        df = pd.DataFrame(data)

        # 保存到 Excel（两个工作表）
        with pd.ExcelWriter(str(file_path), engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='BOM数据', index=False)
            pd.DataFrame([project_info]).to_excel(writer, sheet_name='项目信息', index=False)

        return len(data), visible_count, hidden_count

    def load(self, file_path: str) -> Dict:
        """
        从 Excel 文件加载工作进度

        Args:
            file_path: 文件路径

        Returns:
            包含 nodes_data, project_info 的字典
        """
        file_path = Path(file_path)

        # 读取 BOM 数据：按工作表名 'BOM数据' 显式读取，避免用户调换 sheet 顺序时
        # 读到错误的工作表；旧版本文件无该名工作表时回退到第一个工作表
        try:
            df = pd.read_excel(str(file_path), sheet_name='BOM数据')
        except (ValueError, KeyError):
            df = pd.read_excel(str(file_path))
        df = df.fillna('')

        # 验证必需字段
        required_fields = ['子物料号', '父物料号', '数量', '是否展开', 'level']
        missing = [f for f in required_fields if f not in df.columns]
        if missing:
            raise ValueError(f"文件格式不正确！缺少字段: {missing}")

        # 读取项目信息
        project_info = {}
        try:
            excel_file = pd.ExcelFile(str(file_path))
            if '项目信息' in excel_file.sheet_names:
                proj_df = pd.read_excel(str(file_path), sheet_name='项目信息')
                if not proj_df.empty:
                    # 空字段填为空串，避免读回 NaN 后 str(nan)='nan' 灌入界面并随导出带出
                    project_info = proj_df.fillna('').iloc[0].to_dict()
        except Exception:
            pass  # 旧版本没有项目信息表

        return {
            'dataframe': df,
            'project_info': project_info
        }

    def restore_nodes(self, df: pd.DataFrame, nodes: List[BOMNode]) -> None:
        """
        从 DataFrame 恢复节点配置

        按行序逐一恢复（df 第 i 个有效行 ↔ nodes[i]），而非按 (物料号,父物料号)
        首匹配。load 时 build_from_dataframe 正是按同一份 df 的行序创建节点
        （跳过空物料号行），二者位置一一对应。按行序恢复可正确处理拆分物料
        （同物料号+同父物料号的两个实例），避免旧实现首匹配 break 导致两份
        配置都写到第一个节点、第二个节点配置丢失的问题。

        Args:
            df: 包含发运配置的 DataFrame
            nodes: 现有节点列表（由 build_from_dataframe 按同一 df 行序构建）
        """
        node_idx = 0
        for _, row in df.iterrows():
            material_id = str(row.get('子物料号', '')).strip()
            # 与 build_from_dataframe 一致：跳过空物料号行
            if not material_id:
                continue
            if node_idx >= len(nodes):
                break
            node = nodes[node_idx]
            node_idx += 1

            # 处理发运主体
            shipping_entity = self._parse_entity(row.get('发运主体', ''))

            # 处理发运方式
            shipping_method = self._parse_method(row.get('发运方式', ''))

            # 处理备注
            remark = self._parse_string(row.get('备注', ''))

            # 处理是否展开
            expand_val = self._parse_expand(row.get('是否展开', '是'))

            if shipping_entity:
                node.shipping_entity = shipping_entity
            if shipping_method:
                node.shipping_method = shipping_method
            if remark:
                node.remark = remark
            node.expand_status = expand_val
            node.calculate_final_quantity()

    def _parse_entity(self, value) -> str:
        """解析发运主体值"""
        if isinstance(value, float) and not pd.isna(value):
            return f'{int(value):02d}'
        value = str(value).strip()
        if value.endswith('.0'):
            try:
                return f'{int(float(value)):02d}'
            except ValueError:
                pass
        if value in ('nan', 'NaN', ''):
            return ''
        return value

    def _parse_method(self, value) -> str:
        """解析发运方式值"""
        # 浮点数：尝试映射 1→A, 2→B, 3→C, 4→D，否则原样返回
        if isinstance(value, float) and not pd.isna(value):
            method_map = {1: 'A', 2: 'B', 3: 'C', 4: 'D'}
            int_val = int(value)
            return method_map.get(int_val, str(int_val))
        value = str(value).strip()
        if value in ('nan', 'NaN', ''):
            return ''
        return value

    def _parse_string(self, value) -> str:
        """解析字符串值"""
        if isinstance(value, float) and pd.isna(value):
            return ''
        value = str(value).strip()
        if value in ('nan', 'NaN'):
            return ''
        return value

    def _parse_expand(self, value) -> str:
        """解析是否展开值"""
        # 浮点数：1→是，0→否
        if isinstance(value, float) and not pd.isna(value):
            return '是' if int(value) == 1 else '否'
        value = str(value).strip()
        if value in ('nan', 'NaN', ''):
            return '是'
        return value
