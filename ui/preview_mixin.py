"""
计算、预览、导出 Mixin

提供发运单的计算、预览显示和导出功能
"""

from PyQt5.QtWidgets import (QTableWidgetItem, QFileDialog, QMessageBox,
                             QHeaderView, QLabel)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from core.calculator import ShippingCalculator
from core.exporter import ShippingExporter


class PreviewMixin:
    """计算、预览、导出 Mixin"""

    def calculate(self):
        """执行计算"""
        if not self.tree_builder.root:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        try:
            self.statusBar().showMessage('正在计算...')

            # 标记被隐藏的节点
            for node in self.tree_builder.all_nodes:
                node._is_hidden = self._is_node_hidden(node)

            self.calculator = ShippingCalculator(self.tree_builder)
            self.current_shipping_order = self.calculator.generate_shipping_order()

            self._update_total_weight()

            visible_count = len([n for n in self.tree_builder.all_nodes if not getattr(n, '_is_hidden', False)])
            hidden_count = len([n for n in self.tree_builder.all_nodes if getattr(n, '_is_hidden', False)])

            self.update_status_bar()
            self.statusBar().showMessage('计算完成！')
            QMessageBox.information(self, '成功',
                f'计算完成！\n\n'
                f'共 {len(self.current_shipping_order)} 条发运记录\n'
                f'可见节点: {visible_count} 个\n'
                f'已隐藏节点: {hidden_count} 个（不参与计算）')
        except Exception as e:
            self.statusBar().showMessage('计算失败')
            QMessageBox.critical(self, '错误', f'计算失败:\n{str(e)}')

    def show_preview(self):
        """显示预览（自动触发计算）"""
        if not self.tree_builder.root:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        # 自动触发计算（确保数据最新）
        self.calculate()
        if self.current_shipping_order is None or self.current_shipping_order.empty:
            return

        self.refresh_table()
        self.preview_group.setVisible(True)

    def close_preview(self):
        """关闭预览"""
        self.preview_group.setVisible(False)

    def validate_config(self):
        """检验所有层级是否维护完毕"""
        if not self.tree_builder.all_nodes:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        errors = []
        warnings = []
        hidden_count = 0

        for node in self.tree_builder.all_nodes:
            if self._is_node_hidden(node):
                hidden_count += 1
                continue

            if not node.children:
                if node.expand_status == '是':
                    errors.append(f"{node.material_id} - {node.name}（叶子节点不应设置'是否展开=是'）")
                elif not node.shipping_entity or not node.shipping_method:
                    missing = []
                    if not node.shipping_entity:
                        missing.append('发运主体')
                    if not node.shipping_method:
                        missing.append('发运方式')
                    warnings.append(f"{node.material_id} - {node.name}（缺少: {', '.join(missing)}）")
            else:
                if not node.expand_status:
                    errors.append(f"{node.material_id} - {node.name}（未设置'是否展开'）")
                elif node.expand_status == '否':
                    if not node.shipping_entity or not node.shipping_method:
                        missing = []
                        if not node.shipping_entity:
                            missing.append('发运主体')
                        if not node.shipping_method:
                            missing.append('发运方式')
                        warnings.append(f"{node.material_id} - {node.name}（'是否展开=否'但缺少: {', '.join(missing)}）")

        if not errors and not warnings:
            QMessageBox.information(self, '检验通过',
                f'✅ 所有层级维护完毕！\n\n'
                f'共 {len(self.tree_builder.all_nodes)} 个物料\n'
                f'已配置: {len(self.tree_builder.all_nodes) - hidden_count} 个\n'
                f'已隐藏（不展开）: {hidden_count} 个')
            return

        result_msg = "检验结果：\n\n"

        if errors:
            result_msg += f"❌ 错误（{len(errors)}个）：\n"
            for item in errors[:20]:
                result_msg += f"  • {item}\n"
            if len(errors) > 20:
                result_msg += f"  ... 还有 {len(errors) - 20} 个\n"
            result_msg += "\n"

        if warnings:
            result_msg += f"⚠️ 警告（{len(warnings)}个）：\n"
            for item in warnings[:20]:
                result_msg += f"  • {item}\n"
            if len(warnings) > 20:
                result_msg += f"  ... 还有 {len(warnings) - 20} 个\n"
            result_msg += "\n"

        result_msg += f"已隐藏（不展开）: {hidden_count} 个"

        if errors:
            QMessageBox.warning(self, '检验未通过', result_msg)
        else:
            QMessageBox.warning(self, '检验提醒', result_msg)

    def refresh_table(self):
        """刷新预览表格（按发运主体分组显示）"""
        if self.current_shipping_order is None or self.current_shipping_order.empty:
            self.table_widget.setRowCount(0)
            self.lbl_stats.setText("共 0 条记录")
            return

        import pandas as pd
        df = self.current_shipping_order.copy()

        def get_sort_key(entity):
            if not entity:
                return (2, 99)
            code = entity.split('-')[0] if '-' in entity else entity
            try:
                n = int(code)
            except ValueError:
                return (2, 99)
            if n == 98: return (1, 98)
            elif n == 99: return (1, 99)
            elif n == 0: return (1, 100)
            else: return (0, n)

        df['_sort'] = df['发运主体'].apply(get_sort_key)
        df = df.sort_values(['_sort', '物料号']).reset_index(drop=True)

        display_rows = []
        current_entity = None
        for _, row in df.iterrows():
            entity = row.get('发运主体', '')
            if entity != current_entity:
                current_entity = entity
                display_rows.append({'_is_header': True, '发运主体': entity})
            display_rows.append({
                '_is_header': False,
                '序号': row.get('序号', ''),
                '物料号': row.get('物料号', ''),
                '图号': row.get('图号', ''),
                '规格': row.get('规格', ''),
                '名称': row.get('名称', ''),
                '数量': row.get('数量', ''),
                '净重': row.get('净重', ''),
                '总重(kg)': row.get('总重(kg)', ''),
                '发运类型': row.get('发运类型', ''),
                '发运主体': row.get('发运主体', ''),
                '备注': row.get('备注', ''),
            })

        self.table_widget.setRowCount(len(display_rows))
        header_font = QFont()
        header_font.setBold(True)
        header_bg = QColor(230, 240, 255)

        for i, item in enumerate(display_rows):
            if item['_is_header']:
                self.table_widget.setItem(i, 0, QTableWidgetItem(''))
                self.table_widget.setItem(i, 1, QTableWidgetItem('发运主体'))
                self.table_widget.setItem(i, 2, QTableWidgetItem(item['发运主体']))
                for col in range(11):
                    cell = self.table_widget.item(i, col)
                    if cell:
                        cell.setFont(header_font)
                        cell.setBackground(header_bg)
            else:
                self.table_widget.setItem(i, 0, QTableWidgetItem(str(item.get('序号', ''))))
                self.table_widget.setItem(i, 1, QTableWidgetItem(str(item.get('物料号', ''))))
                self.table_widget.setItem(i, 2, QTableWidgetItem(str(item.get('图号', ''))))
                self.table_widget.setItem(i, 3, QTableWidgetItem(str(item.get('规格', ''))))
                self.table_widget.setItem(i, 4, QTableWidgetItem(str(item.get('名称', ''))))
                self.table_widget.setItem(i, 5, QTableWidgetItem(str(item.get('数量', ''))))
                self.table_widget.setItem(i, 6, QTableWidgetItem(str(item.get('净重', ''))))
                self.table_widget.setItem(i, 7, QTableWidgetItem(str(item.get('总重(kg)', ''))))
                self.table_widget.setItem(i, 8, QTableWidgetItem(str(item.get('发运类型', ''))))
                self.table_widget.setItem(i, 9, QTableWidgetItem(item['发运主体']))
                self.table_widget.setItem(i, 10, QTableWidgetItem(str(item.get('备注', ''))))

        data_count = sum(1 for r in display_rows if not r['_is_header'])
        self.lbl_stats.setText(f"共 {data_count} 条记录")
        self._update_total_weight()

    def _update_total_weight(self):
        """更新项目总重显示"""
        if hasattr(self, 'lbl_total_weight'):
            if self.current_shipping_order is not None and not self.current_shipping_order.empty:
                total = self.current_shipping_order['总重(kg)'].sum()
                self.lbl_total_weight.setText(f'{total:,.2f} kg')
            else:
                self.lbl_total_weight.setText('0 kg')

    def export_excel(self):
        """导出Excel（自动触发计算）"""
        if not self.tree_builder.root:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        # 自动触发计算（确保数据最新）
        self.calculate()
        if self.current_shipping_order is None or self.current_shipping_order.empty:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出发运单', '发运单.xlsx',
            'Excel文件 (*.xlsx)'
        )

        if file_path:
            try:
                project_name = self.edit_project_name.text() if hasattr(self, 'edit_project_name') else ''
                project_drawing = self.edit_project_drawing.text() if hasattr(self, 'edit_project_drawing') else ''
                construction_no = self.edit_project_construction.text() if hasattr(self, 'edit_project_construction') else ''
                author = self.edit_maker.text() if hasattr(self, 'edit_maker') else ''
                reviewer = self.edit_reviewer.text() if hasattr(self, 'edit_reviewer') else ''
                total_weight = self.current_shipping_order['总重(kg)'].sum() if not self.current_shipping_order.empty else 0

                exporter = ShippingExporter()
                exporter.export_to_excel(
                    self.current_shipping_order, file_path,
                    project_name=project_name,
                    project_drawing=project_drawing,
                    construction_no=construction_no,
                    author=author,
                    reviewer=reviewer,
                    total_weight=total_weight
                )
                self.statusBar().showMessage(f'导出成功: {file_path}')

                reply = QMessageBox.question(
                    self, '导出成功',
                    f'发运单已导出到:\n{file_path}\n\n是否现在打开？',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    import os
                    os.startfile(file_path)
            except Exception as e:
                self.statusBar().showMessage('导出失败')
                QMessageBox.critical(self, '错误', f'导出失败:\n{str(e)}')

    def export_csv(self):
        """导出CSV（自动触发计算）"""
        if not self.tree_builder.root:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        # 自动触发计算（确保数据最新）
        self.calculate()
        if self.current_shipping_order is None or self.current_shipping_order.empty:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出发运单', '发运单.csv',
            'CSV文件 (*.csv)'
        )

        if file_path:
            try:
                exporter = ShippingExporter()
                exporter.export_to_csv(self.current_shipping_order, file_path)
                self.statusBar().showMessage(f'导出成功: {file_path}')
                QMessageBox.information(self, '成功', f'发运单已导出到:\n{file_path}')
            except Exception as e:
                self.statusBar().showMessage('导出失败')
                QMessageBox.critical(self, '错误', f'导出失败:\n{str(e)}')

    def update_status_bar(self):
        """更新状态栏"""
        data_count = len(self.tree_builder.all_nodes) if self.tree_builder.all_nodes else 0
        shipping_units = len(self.tree_builder.get_all_shipping_units()) if self.tree_builder.root else 0

        configured_count = 0
        if self.tree_builder.all_nodes:
            for node in self.tree_builder.all_nodes:
                if node.shipping_entity and node.shipping_method:
                    configured_count += 1

        self.lbl_data_count.setText(f'数据: {data_count} 条')
        self.lbl_config_count.setText(f'已配置: {configured_count} 个')
        self.lbl_shipping_units.setText(f'发运单元: {shipping_units} 个')
