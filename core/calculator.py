"""
计算引擎

实现递归计算和聚合
"""

import pandas as pd
from typing import List, Dict

from models.bom_node import BOMNode
from core.entity_config import EntityConfigManager


class ShippingCalculator:
    """发运单计算器"""

    def __init__(self, tree_builder):
        """
        初始化计算器

        Args:
            tree_builder: 树结构构建器
        """
        self.tree_builder = tree_builder

    def calculate(self) -> pd.DataFrame:
        """
        执行完整计算流程

        Returns:
            计算结果DataFrame
        """
        # 1. 获取所有发运单元
        shipping_units = self.tree_builder.get_all_shipping_units()

        if not shipping_units:
            return pd.DataFrame()

        # 2. 构建结果数据
        results = []
        for unit in shipping_units:
            results.append({
                '物料号': unit.material_id,
                '父物料号': unit.parent_id,
                '图号': unit.drawing_no,
                '规格': unit.specification,
                '名称': unit.name,
                '数量': unit.final_quantity,
                '净重': unit.weight,
                '总重': unit.total_weight,
                '发运主体': unit.shipping_entity,
                '发运方式': unit.shipping_method,
                '备注': unit.remark,
                '聚合键': unit.aggregation_key,
                '分组排序': unit.group_sort,
                '组内排序': unit.method_sort
            })

        df = pd.DataFrame(results)
        return df

    def aggregate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        三重聚合计算

        Args:
            df: 原始计算结果

        Returns:
            聚合后的DataFrame
        """
        if df.empty:
            return df

        # 数量异常检查（必须在聚合前：groupby.sum 会把全 NaN 的分组吸收为 0 而掩盖问题）。
        # NaN 会导致最终数量错误，明确报错（fail-loud）而非静默输出错误发运单
        if '数量' in df.columns and df['数量'].isna().any():
            raise ValueError("发运单计算结果中存在空数量（NaN），请检查BOM数据中的数量字段。")

        # 按聚合键分组求和（聚合键已包含物料号+发运主体+发运方式+备注）
        aggregated = df.groupby(['聚合键', '发运主体', '发运方式', '备注', '分组排序', '组内排序']).agg({
            '数量': 'sum',
            '总重': 'sum',
            '物料号': 'first',
            '净重': 'first',
            '图号': 'first',
            '规格': 'first',
            '名称': 'first',
        }).reset_index()

        # 总重直接采用 agg 的逐行求和结果（'总重': 'sum'）。
        # 不用"求和数量 × first净重"覆盖：同物料在不同父节点下净重可能不同，
        # 逐行求和（Σ 数量×净重）才是正确总重；净重恒相同时两者结果一致。

        # 添加显示用的发运主体名称（带代码前缀，如"08-电缆槽"）
        aggregated['发运主体名称'] = aggregated['发运主体'].apply(
            lambda x: EntityConfigManager.get_entity_display_name(x) if x else ''
        )

        # 按分组排序和组内排序
        aggregated = aggregated.sort_values(['分组排序', '发运主体', '组内排序', '物料号'])

        return aggregated

    def generate_shipping_order(self) -> pd.DataFrame:
        """
        生成最终发运单

        Returns:
            发运单DataFrame
        """
        # 1. 计算
        df = self.calculate()

        if df.empty:
            return pd.DataFrame()

        # 2. 聚合
        aggregated = self.aggregate(df)

        if aggregated.empty:
            return pd.DataFrame()

        # 3. 添加序号
        aggregated['序号'] = range(1, len(aggregated) + 1)

        # 4. 格式化数字（NaN 守卫已在 aggregate() 聚合前完成，此处可安全取整）
        aggregated['数量'] = aggregated['数量'].round(0).astype(int)
        aggregated['净重'] = aggregated['净重'].round(4)
        aggregated['总重'] = aggregated['总重'].round(2)

        # 5. 选择输出列
        output_columns = ['序号', '物料号', '图号', '规格', '名称', '数量', '净重', '总重', '发运方式', '发运主体名称', '备注']

        # 确保所有列都存在
        for col in output_columns:
            if col not in aggregated.columns:
                aggregated[col] = ''

        output = aggregated[output_columns].copy()
        output.columns = ['序号', '物料号', '图号', '规格', '名称', '数量', '净重', '总重(kg)', '发运类型', '发运主体', '备注']

        return output

    def get_statistics(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        shipping_units = self.tree_builder.get_all_shipping_units()

        total_quantity = sum(unit.final_quantity for unit in shipping_units)
        total_weight = sum(unit.total_weight for unit in shipping_units)

        # 按发运主体统计
        by_entity = {}
        for unit in shipping_units:
            entity = unit.shipping_entity or '未配置'
            if entity not in by_entity:
                by_entity[entity] = {'count': 0, 'quantity': 0, 'weight': 0}
            by_entity[entity]['count'] += 1
            by_entity[entity]['quantity'] += unit.final_quantity
            by_entity[entity]['weight'] += unit.total_weight

        # 按发运方式统计
        by_method = {}
        for unit in shipping_units:
            method = unit.shipping_method or '未配置'
            if method not in by_method:
                by_method[method] = {'count': 0, 'quantity': 0, 'weight': 0}
            by_method[method]['count'] += 1
            by_method[method]['quantity'] += unit.final_quantity
            by_method[method]['weight'] += unit.total_weight

        return {
            'total_nodes': len(self.tree_builder.all_nodes),
            'shipping_units': len(shipping_units),
            'total_quantity': total_quantity,
            'total_weight': total_weight,
            'by_entity': by_entity,
            'by_method': by_method
        }
