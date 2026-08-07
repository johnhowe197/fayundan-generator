"""
发运主体定义 UI Mixin

提供发运主体定义的查看、编辑、预设管理等界面功能
"""

from PyQt5.QtWidgets import (QDialog, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QFileDialog,
                             QComboBox, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QGroupBox, QInputDialog)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

from core.entity_config import EntityConfigManager


class EntityMixin:
    """发运主体定义 UI Mixin"""

    def show_entity_definition(self):
        """显示发运主体定义对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle('发运主体定义')
        dialog.setFixedSize(650, 600)

        layout = QVBoxLayout()

        # 预设选择区域
        preset_group = QGroupBox("预设配置")
        preset_layout = QVBoxLayout()

        preset_row1 = QHBoxLayout()
        preset_label = QLabel('选择预设:')
        preset_row1.addWidget(preset_label)

        preset_combo = QComboBox()
        preset_combo.setMinimumWidth(200)

        entity_mgr = EntityConfigManager()
        preset_names = entity_mgr.get_preset_names()
        preset_combo.addItems(preset_names)

        current_preset = entity_mgr.get_current_preset_name()
        index = preset_combo.findText(current_preset)
        if index >= 0:
            preset_combo.setCurrentIndex(index)

        preset_row1.addWidget(preset_combo)

        preset_combo.currentTextChanged.connect(lambda name: self._load_preset_to_table(name, table) if name else None)

        btn_save_preset = QPushButton('保存为预设')
        btn_save_preset.setStyleSheet("background-color: #2196F3; color: white;")
        btn_save_preset.clicked.connect(lambda: self._save_table_as_preset(preset_combo.currentText(), table, preset_combo))
        preset_row1.addWidget(btn_save_preset)

        preset_layout.addLayout(preset_row1)

        preset_row2 = QHBoxLayout()
        btn_new_preset = QPushButton('新建预设')
        btn_new_preset.clicked.connect(lambda: self._create_new_preset(preset_combo))
        preset_row2.addWidget(btn_new_preset)

        btn_delete_preset = QPushButton('删除预设')
        btn_delete_preset.clicked.connect(lambda: self._delete_preset(preset_combo))
        preset_row2.addWidget(btn_delete_preset)

        btn_reset_preset = QPushButton('重置预设')
        btn_reset_preset.clicked.connect(lambda: self._reset_presets())
        preset_row2.addWidget(btn_reset_preset)

        btn_set_current = QPushButton('置为当前')
        btn_set_current.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
        btn_set_current.setToolTip('将当前选择的预设设置为全局默认配置')
        btn_set_current.clicked.connect(lambda: self._set_current_preset(preset_combo.currentText()))
        preset_row2.addWidget(btn_set_current)

        preset_row2.addStretch()
        preset_layout.addLayout(preset_row2)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        # 说明标签
        info_label = QLabel('发运主体定义列表（可编辑、新增、导出/导入模板）:')
        layout.addWidget(info_label)

        # 按钮栏
        btn_layout = QHBoxLayout()

        btn_add = QPushButton('新增行')
        btn_add.clicked.connect(lambda: self._add_entity_row(table))
        btn_layout.addWidget(btn_add)

        btn_delete = QPushButton('删除选中行')
        btn_delete.clicked.connect(lambda: self._delete_entity_row(table))
        btn_layout.addWidget(btn_delete)

        btn_move_up = QPushButton('↑ 上移')
        btn_move_up.setToolTip('将选中行上移一位')
        btn_move_up.clicked.connect(lambda: self._move_entity_row(table, -1))
        btn_layout.addWidget(btn_move_up)

        btn_move_down = QPushButton('↓ 下移')
        btn_move_down.setToolTip('将选中行下移一位')
        btn_move_down.clicked.connect(lambda: self._move_entity_row(table, 1))
        btn_layout.addWidget(btn_move_down)

        btn_layout.addStretch()

        btn_export = QPushButton('导出模板')
        btn_export.clicked.connect(lambda: self._export_entity_template(table))
        btn_layout.addWidget(btn_export)

        btn_import = QPushButton('导入模板')
        btn_import.clicked.connect(lambda: self._import_entity_template(table))
        btn_layout.addWidget(btn_import)

        layout.addLayout(btn_layout)

        # 表格
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['代码', '名称', '说明'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)

        entities = entity_mgr.load_definitions()

        def sort_key(item):
            code = item[0]
            if code == '00':
                return (2, 0)
            # 非数字代码（用户自定义）排在数字代码之后、'00'之前，
            # 避免 int(code) 对非数字抛 ValueError 导致对话框崩溃
            if str(code).isdigit():
                return (0, int(code))
            return (1, str(code))
        entities = sorted(entities, key=sort_key)

        locked_codes = EntityConfigManager.LOCKED_CODES

        table.setRowCount(len(entities))
        for i, (code, name, desc) in enumerate(entities):
            item_code = QTableWidgetItem(code)
            item_name = QTableWidgetItem(name)
            item_desc = QTableWidgetItem(desc)
            if code in locked_codes:
                for item in [item_code, item_name, item_desc]:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(QColor(240, 240, 240))
            table.setItem(i, 0, item_code)
            table.setItem(i, 1, item_name)
            table.setItem(i, 2, item_desc)

        layout.addWidget(table)

        # 底部按钮栏
        bottom_layout = QHBoxLayout()

        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(dialog.close)
        bottom_layout.addWidget(btn_close)

        bottom_layout.addStretch()

        btn_save = QPushButton('保存')
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        btn_save.clicked.connect(lambda: self._save_entity_definition(table, dialog))
        bottom_layout.addWidget(btn_save)

        layout.addLayout(bottom_layout)

        dialog.setLayout(layout)
        dialog.exec_()

    def _load_entity_definitions(self):
        """从配置文件加载发运主体定义"""
        entity_mgr = EntityConfigManager()
        return entity_mgr.load_definitions()

    def _save_entity_definition(self, table, dialog):
        """保存发运主体定义"""
        try:
            entities = []
            for row in range(table.rowCount()):
                code = table.item(row, 0).text() if table.item(row, 0) else ''
                name = table.item(row, 1).text() if table.item(row, 1) else ''
                desc = table.item(row, 2).text() if table.item(row, 2) else ''
                if code:
                    entities.append((code, name, desc))

            entity_mgr = EntityConfigManager()

            # 保存到全局定义文件。必须检查返回值：写入失败（如程序所在目录
            # 不可写）时绝不能谎报成功，否则用户看到"已保存"、重开程序后丢失
            if not entity_mgr.save_definitions(entities):
                QMessageBox.critical(self, '保存失败',
                    '发运主体定义未能写入磁盘！\n\n'
                    f'{entity_mgr.last_error}\n\n'
                    f'配置目录：{entity_mgr.config_dir}\n'
                    '请确认程序所在文件夹对当前用户可写（建议把整个程序文件夹'
                    '放到桌面或 D 盘等位置，勿放在 C:\\Program Files 等受保护目录），'
                    '处理后重新点击"保存"。详细信息见 error.log。')
                return

            # 同时更新当前预设（如果存在）
            current_preset = entity_mgr.get_current_preset_name()
            if current_preset:
                entities_dict = {code: name for code, name, desc in entities}
                if not entity_mgr.save_preset(current_preset, entities_dict):
                    QMessageBox.critical(self, '保存失败',
                        f'发运主体定义已保存，但预设 "{current_preset}" 写入失败！\n\n'
                        f'{entity_mgr.last_error}\n\n详细信息见 error.log。')
                    return

            # 更新实体名称映射缓存
            EntityConfigManager.update_entity_name_map(entities)

            # 更新全局实体映射
            self.entity_map = {}
            for code, name, desc in entities:
                self.entity_map[code] = f'{code}-{name}'

            # 刷新发运主体下拉框选项
            if hasattr(self, 'entity_delegate'):
                new_items = [''] + [self._get_entity_display_name(e) for e in self._get_all_entity_codes()]
                self.entity_delegate.items = new_items
                self.tree_widget.setItemDelegateForColumn(7, self.entity_delegate)

            self.refresh_tree(preserve_expand_state=True)

            QMessageBox.information(self, '成功', f'发运主体定义已保存！\n\n共 {len(entities)} 条记录')
            dialog.close()

        except Exception as e:
            QMessageBox.critical(self, '错误', f'保存失败:\n{str(e)}')

    def _load_preset_to_table(self, preset_name, table):
        """加载预设到表格"""
        try:
            entity_mgr = EntityConfigManager()
            preset = entity_mgr.get_preset(preset_name)

            if not preset:
                QMessageBox.warning(self, '警告', f'预设 "{preset_name}" 不存在！')
                return

            entities_dict = preset.get('entities', {})
            # 确保锁定代码存在（兼容旧配置文件）
            entities_dict = EntityConfigManager._ensure_locked_codes(entities_dict)

            table.setRowCount(0)

            locked_codes = EntityConfigManager.LOCKED_CODES

            def sort_key(item):
                code = item[0]
                if code == '00':
                    return (2, 0)
                # 非数字代码（用户自定义）排在数字代码之后、'00'之前，避免 int() 崩溃
                if str(code).isdigit():
                    return (0, int(code))
                return (1, str(code))

            sorted_entities = sorted(entities_dict.items(), key=sort_key)

            row = 0
            for code, name in sorted_entities:
                table.insertRow(row)
                item_code = QTableWidgetItem(code)
                item_name = QTableWidgetItem(name)
                item_desc = QTableWidgetItem('')
                if code in locked_codes:
                    for item in [item_code, item_name, item_desc]:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setBackground(QColor(240, 240, 240))
                table.setItem(row, 0, item_code)
                table.setItem(row, 1, item_name)
                table.setItem(row, 2, item_desc)
                row += 1

            entity_mgr.set_current_preset(preset_name)

            QMessageBox.information(self, '成功', f'已加载预设 "{preset_name}"\n\n共 {row} 条记录')

        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载预设失败:\n{str(e)}')

    def _save_table_as_preset(self, preset_name, table, preset_combo=None):
        """将表格保存为预设"""
        try:
            preset_name, ok = QInputDialog.getText(self, '保存预设',
                '请输入预设名称:', text=preset_name or '')
            if not ok or not preset_name:
                return

            entities_dict = {}
            for row in range(table.rowCount()):
                code = table.item(row, 0).text() if table.item(row, 0) else ''
                name = table.item(row, 1).text() if table.item(row, 1) else ''
                if code:
                    entities_dict[code] = name

            if not entities_dict:
                QMessageBox.warning(self, '警告', '表格中没有发运主体定义！')
                return

            entity_mgr = EntityConfigManager()
            existing = entity_mgr.get_preset(preset_name)

            if existing:
                reply = QMessageBox.question(
                    self, '确认覆盖',
                    f'预设 "{preset_name}" 已存在，是否覆盖？',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            if entity_mgr.save_preset(preset_name, entities_dict):
                if preset_combo:
                    preset_combo.blockSignals(True)
                    preset_combo.clear()
                    preset_combo.addItems(entity_mgr.get_preset_names())
                    preset_combo.setCurrentText(preset_name)
                    preset_combo.blockSignals(False)
                QMessageBox.information(self, '成功', f'已将当前配置保存为预设 "{preset_name}"')
            else:
                QMessageBox.critical(self, '错误',
                    f'保存预设失败！\n\n{entity_mgr.last_error}\n\n'
                    '请确认程序所在文件夹可写，详细信息见 error.log。')

        except Exception as e:
            QMessageBox.critical(self, '错误', f'保存预设失败:\n{str(e)}')

    def _create_new_preset(self, preset_combo):
        """创建新预设"""
        preset_name, ok = QInputDialog.getText(self, '创建新预设', '请输入新预设的名称:')
        if not ok or not preset_name:
            return

        entity_mgr = EntityConfigManager()
        if entity_mgr.create_preset(preset_name):
            # blockSignals 防止刷新下拉时 currentTextChanged 触发
            # _load_preset_to_table 覆盖表格中未保存的编辑
            preset_combo.blockSignals(True)
            preset_combo.clear()
            preset_combo.addItems(entity_mgr.get_preset_names())
            preset_combo.setCurrentText(preset_name)
            preset_combo.blockSignals(False)
            QMessageBox.information(self, '成功', f'已创建新预设 "{preset_name}"')
        elif entity_mgr.get_preset(preset_name) is not None:
            QMessageBox.warning(self, '警告', f'预设 "{preset_name}" 已存在！')
        else:
            QMessageBox.critical(self, '错误',
                f'创建预设失败（未能写入磁盘）！\n\n{entity_mgr.last_error}\n\n'
                '请确认程序所在文件夹可写，详细信息见 error.log。')

    def _delete_preset(self, preset_combo):
        """删除预设"""
        preset_name = preset_combo.currentText()
        if not preset_name:
            QMessageBox.warning(self, '警告', '请先选择一个预设！')
            return

        entity_mgr = EntityConfigManager()
        preset_names = entity_mgr.get_preset_names()

        if len(preset_names) <= 1:
            QMessageBox.warning(self, '警告', '至少需要保留一个预设！')
            return

        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除预设 "{preset_name}" 吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        if entity_mgr.delete_preset(preset_name):
            # blockSignals 防止刷新下拉时 currentTextChanged 触发
            # _load_preset_to_table 覆盖表格中未保存的编辑（删除后
            # setCurrentText 的名称可能已不在列表中，附带警告弹窗）
            preset_combo.blockSignals(True)
            preset_combo.clear()
            preset_combo.addItems(entity_mgr.get_preset_names())
            current = entity_mgr.get_current_preset_name()
            if current:
                preset_combo.setCurrentText(current)
            preset_combo.blockSignals(False)
            QMessageBox.information(self, '成功', f'已删除预设 "{preset_name}"')

    def _reset_presets(self):
        """重置预设到默认值"""
        reply = QMessageBox.question(
            self, '确认重置',
            '确定要将所有预设重置为默认值吗？此操作不可撤销！',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        entity_mgr = EntityConfigManager()
        if entity_mgr.reset_presets():
            QMessageBox.information(self, '成功', '已重置为默认预设配置')
        else:
            QMessageBox.critical(self, '错误', '重置失败！')

    def _set_current_preset(self, preset_name):
        """将指定预设设置为全局当前预设"""
        if not preset_name:
            QMessageBox.warning(self, '警告', '请先选择一个预设！')
            return

        entity_mgr = EntityConfigManager()
        if entity_mgr.set_current_preset(preset_name):
            QMessageBox.information(self, '成功',
                f'已将预设 "{preset_name}" 设置为全局当前配置。\n\n'
                f'后续新建节点将默认使用此预设的发运主体定义。')
        else:
            QMessageBox.critical(self, '错误', '设置失败！')

    def _move_entity_row(self, table, direction):
        """移动表格行"""
        current_row = table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, '警告', '请先选中一行！')
            return

        target_row = current_row + direction
        if target_row < 0 or target_row >= table.rowCount():
            return

        for col in range(table.columnCount()):
            current_item = table.item(current_row, col)
            target_item = table.item(target_row, col)
            current_text = current_item.text() if current_item else ''
            target_text = target_item.text() if target_item else ''
            table.setItem(current_row, col, QTableWidgetItem(target_text))
            table.setItem(target_row, col, QTableWidgetItem(current_text))

        table.selectRow(target_row)

    def _add_entity_row(self, table):
        """新增发运主体行"""
        row_count = table.rowCount()
        table.insertRow(row_count)
        table.setItem(row_count, 0, QTableWidgetItem(''))
        table.setItem(row_count, 1, QTableWidgetItem(''))
        table.setItem(row_count, 2, QTableWidgetItem(''))
        table.selectRow(row_count)

    def _delete_entity_row(self, table):
        """删除选中的行"""
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, '警告', '请先选择要删除的行！')
            return

        locked_codes = EntityConfigManager.LOCKED_CODES

        entities_to_delete = []
        for index in selected_rows:
            code = table.item(index.row(), 0).text() if table.item(index.row(), 0) else ''
            if code in locked_codes:
                QMessageBox.warning(self, '警告', f'发运主体 {code} 是系统固定定义，不可删除！')
                return
            if code:
                entities_to_delete.append(code)

        # 检查是否有物料在使用
        used_entities = []
        for node in self.tree_builder.all_nodes:
            if node.shipping_entity:
                entity_code = node.shipping_entity.split('-')[0] if '-' in node.shipping_entity else node.shipping_entity
                if entity_code in entities_to_delete:
                    used_entities.append(f"{node.material_id} - {node.name}")

        if used_entities:
            msg = f"以下发运主体正在被物料使用，无法删除：\n\n"
            for entity_code in entities_to_delete:
                msg += f"• {entity_code}: 被 {len(used_entities)} 个物料使用\n"
            msg += f"\n正在使用的物料（前10个）：\n"
            for item in used_entities[:10]:
                msg += f"  • {item}\n"
            if len(used_entities) > 10:
                msg += f"  ... 还有 {len(used_entities) - 10} 个\n"
            QMessageBox.warning(self, '无法删除', msg)
            return

        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除选中的 {len(selected_rows)} 行吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            for index in sorted(selected_rows, reverse=True):
                table.removeRow(index.row())

    def _export_entity_template(self, table):
        """导出发运主体模板"""
        import pandas as pd

        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出发运主体模板', '发运主体模板.xlsx',
            'Excel文件 (*.xlsx);;CSV文件 (*.csv)'
        )

        if file_path:
            try:
                data = []
                for row in range(table.rowCount()):
                    code = table.item(row, 0).text() if table.item(row, 0) else ''
                    name = table.item(row, 1).text() if table.item(row, 1) else ''
                    desc = table.item(row, 2).text() if table.item(row, 2) else ''
                    data.append({'代码': code, '名称': name, '说明': desc})

                df = pd.DataFrame(data)

                if file_path.endswith('.csv'):
                    df.to_csv(file_path, index=False, encoding='utf-8-sig')
                else:
                    df.to_excel(file_path, index=False, engine='openpyxl')

                QMessageBox.information(self, '成功', f'模板已导出到:\n{file_path}')
            except Exception as e:
                QMessageBox.critical(self, '错误', f'导出失败:\n{str(e)}')

    def _import_entity_template(self, table):
        """导入发运主体模板"""
        import pandas as pd

        file_path, _ = QFileDialog.getOpenFileName(
            self, '导入发运主体模板', '',
            'Excel文件 (*.xlsx *.xls);;CSV文件 (*.csv);;所有文件 (*.*)'
        )

        if file_path:
            try:
                if file_path.endswith('.csv'):
                    df = pd.read_csv(file_path, encoding='utf-8-sig')
                else:
                    df = pd.read_excel(file_path)

                required_columns = ['代码', '名称', '说明']
                if not all(col in df.columns for col in required_columns):
                    if 'code' in df.columns and 'name' in df.columns:
                        df = df.rename(columns={'code': '代码', 'name': '名称', 'desc': '说明'})
                    else:
                        QMessageBox.warning(self, '警告', f'文件格式不正确！\n需要包含列: {required_columns}')
                        return

                table.setRowCount(0)

                for _, row in df.iterrows():
                    row_count = table.rowCount()
                    table.insertRow(row_count)
                    table.setItem(row_count, 0, QTableWidgetItem(str(row.get('代码', ''))))
                    table.setItem(row_count, 1, QTableWidgetItem(str(row.get('名称', ''))))
                    table.setItem(row_count, 2, QTableWidgetItem(str(row.get('说明', ''))))

                QMessageBox.information(self, '成功', f'已导入 {len(df)} 条发运主体定义')
            except Exception as e:
                QMessageBox.critical(self, '错误', f'导入失败:\n{str(e)}')
