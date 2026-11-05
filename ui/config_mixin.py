"""
节点配置操作 Mixin

提供发运主体、发运方式、是否展开等配置的交互操作
"""

from PyQt5.QtWidgets import (QMenu, QDialog, QVBoxLayout, QListWidget,
                             QListWidgetItem, QLabel, QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import Qt


class ConfigMixin:
    """节点配置操作 Mixin"""

    def on_item_changed(self, item, column):
        """
        项目变化事件（数据变化时）

        Args:
            item: 树节点项
            column: 变化的列
        """
        # 复选框变化不需要处理
        if column == 0:
            return

        # 重入保护：_handle_expand_change/_handle_entity_change 等内部会程序化 setText，
        # 从而再次触发 itemChanged。若不加保护，对"自身有配置且子孙也有配置"的节点
        # 改"是否展开"并一路点"否"时，两个确认对话框会交替无限弹出，且每层重入都
        # 重复 _save_state 泛洪撤销栈。处理期间忽略重入事件。
        if getattr(self, '_in_item_changed', False):
            return
        self._in_item_changed = True
        try:
            node = item.data(1, Qt.UserRole)
            if not node:
                return

            # 检查节点是否被隐藏
            if self._is_node_hidden(node):
                return

            # 先捕获快照，确认生效后再提交：取消时不会留下无效果的撤销点，
            # 也不会提前清空预览结果（P2-R1）
            snapshot = None
            if column in [6, 7, 8, 9]:
                snapshot = self._save_state_snapshot()

            accepted = True
            if column == 6:  # 是否展开
                accepted = self._handle_expand_change(item, node)
            elif column == 7:  # 发运主体
                accepted = self._handle_entity_change(item, node)
            elif column == 8:  # 发运方式
                accepted = self._handle_method_change(item, node)
            elif column == 9:  # 备注
                node.remark = item.text(9)

            if accepted is not False:
                if snapshot is not None:
                    # 提交快照：置脏并失效预览（均在 _push_undo_snapshot 内统一处理）
                    self._push_undo_snapshot(snapshot)
                else:
                    # 非撤销类列编辑（如名称/图号）：仍需标记未保存并失效预览
                    self._dirty = True
                    self._update_title()
                    self._invalidate_preview_after_change()

            # 统一更新背景色和状态显示
            self._update_item_style(item, node)
        finally:
            self._in_item_changed = False

    def _handle_expand_change(self, item, node):
        """处理是否展开列变化

        Returns:
            True: 变更生效；False: 用户取消/自动回退，调用方应回滚撤销点
        """
        value = item.text(6)
        # 叶子节点不能设为"是"
        if value == '是' and not node.children:
            item.setText(6, '否')
            return False
        # 有发运配置的节点设为"是"时，需确认并清空配置
        if value == '是' and (node.shipping_entity or node.shipping_method or node.remark):
            reply = QMessageBox.question(
                self, '确认设置',
                '该节点已维护发运配置！\n\n'
                '设为"是"后将清空该节点的发运配置，\n'
                '它将不再作为独立发运单元参与统计。\n\n'
                '是否继续？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                item.setText(6, '否')
                return False
            # 清空配置
            node.shipping_entity = ''
            node.shipping_method = ''
            node.remark = ''

        node.expand_status = value
        if value == '是':
            # 显示配置值
            item.setText(7, self._get_entity_display_name(node.shipping_entity) if node.shipping_entity else '')
            item.setText(8, self._get_method_display_name(node.shipping_method) if node.shipping_method else '')
            item.setText(9, node.remark if node.remark else '')
            # 恢复展开箭头（B9-1：边界感知递归恢复，深层节点不再遗留隐藏）
            item.setChildIndicatorPolicy(item.ChildIndicatorPolicy.ShowIndicator)
            self._show_children(item, recursive=True)
            self.tree_widget.expandItem(item)
        else:
            # 检查子孙节点是否有发运配置
            if self._has_children_with_config(node):
                reply = QMessageBox.question(
                    self, '确认设置',
                    '该节点的子物料已维护发运配置！\n\n'
                    '设为"否"后将清除所有子物料的发运配置，\n'
                    '它们将不再作为独立发运单元参与统计。\n\n'
                    '是否继续？',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    node.expand_status = '是'
                    item.setText(6, '是')
                    return False
            self._clear_children_config(node)
            self._update_children_display(item)
            # 恢复实际显示值
            item.setText(7, self._get_entity_display_name(node.shipping_entity) if node.shipping_entity else '')
            item.setText(8, self._get_method_display_name(node.shipping_method) if node.shipping_method else '')
            item.setText(9, node.remark if node.remark else '')
            # 顶级节点保留展开箭头，其他节点隐藏
            if node.level > 0:
                item.setChildIndicatorPolicy(item.ChildIndicatorPolicy.DontShowIndicator)
            self._hide_children(item)
            self.tree_widget.collapseItem(item)

        node.calculate_final_quantity()
        self.update_status_bar()
        return True

    def _confirm_collapse_descendants(self, node):
        """节点由"是"隐式变"否"前，若子孙已维护配置则确认并清空（B9-2）

        Returns:
            True: 无需确认或用户确认（子孙配置已清空，可继续置否）
            False: 用户取消，调用方应回退本次变更
        """
        if not self._has_children_with_config(node):
            return True
        reply = QMessageBox.question(
            self, '确认设置',
            '该节点的子物料已维护发运配置！\n\n'
            '设为"否"（发运单元）后将清除所有子物料的发运配置，\n'
            '它们将不再作为独立发运单元参与统计。\n\n'
            '是否继续？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        self._clear_children_config(node)
        return True

    def _confirm_batch_collapse(self, nodes):
        """批量由"是"变"否"前汇总确认一次（B9-2）

        确认后清除相关节点的子孙配置；拒绝则整批取消。
        """
        targets = [
            n for n in nodes
            if n.expand_status == '是' and self._has_children_with_config(n)
        ]
        if not targets:
            return True
        reply = QMessageBox.question(
            self, '确认设置',
            f'选中的节点中有 {len(targets)} 个的子物料已维护发运配置！\n\n'
            '设为发运单元后将清除这些子物料的发运配置，\n'
            '它们将不再作为独立发运单元参与统计。\n\n'
            '是否继续？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        for node in targets:
            self._clear_children_config(node)
        return True

    def _handle_entity_change(self, item, node):
        """处理发运主体列变化

        Returns:
            True: 变更生效；False: 用户取消（调用方回滚撤销点）
        """
        value = item.text(7)
        entity_code = value.split('-')[0] if '-' in value else value
        old_entity = node.shipping_entity
        old_method = node.shipping_method
        old_expand = node.expand_status

        node.shipping_entity = entity_code
        # 应用自动规则（98→B打捆, 99→C装箱）
        from core.entity_config import EntityConfigManager
        EntityConfigManager.apply_auto_rules(node)
        # 更新发运方式显示
        if node.shipping_method:
            item.setText(8, self._get_method_display_name(node.shipping_method))
        if entity_code and old_expand == '是':
            # B9-2：由"是"隐式变"否"时，先确认是否清除子孙配置
            if not self._confirm_collapse_descendants(node):
                # 用户拒绝：回退本次主体/方式变更
                node.shipping_entity = old_entity
                node.shipping_method = old_method
                node.expand_status = old_expand
                item.setText(7, self._get_entity_display_name(old_entity) if old_entity else '')
                item.setText(8, self._get_method_display_name(old_method) if old_method else '')
                item.setText(6, old_expand)
                node.calculate_final_quantity()
                self.update_status_bar()
                return False
            self._update_children_display(item)
            node.expand_status = '否'
            item.setText(6, '否')
            if node.level > 0:
                item.setChildIndicatorPolicy(item.ChildIndicatorPolicy.DontShowIndicator)
            self._hide_children(item)
        node.calculate_final_quantity()
        self.update_status_bar()
        return True

    def _handle_method_change(self, item, node):
        """处理发运方式列变化

        Returns:
            True: 变更生效；False: 用户取消（调用方回滚撤销点）
        """
        value = item.text(8)
        method_code = value[0] if value else ''
        old_method = node.shipping_method
        old_expand = node.expand_status

        node.shipping_method = method_code
        if value and old_expand == '是':
            # B9-2：由"是"隐式变"否"时，先确认是否清除子孙配置
            if not self._confirm_collapse_descendants(node):
                node.shipping_method = old_method
                node.expand_status = old_expand
                item.setText(8, self._get_method_display_name(old_method) if old_method else '')
                item.setText(6, old_expand)
                node.calculate_final_quantity()
                self.update_status_bar()
                return False
            self._update_children_display(item)
            node.expand_status = '否'
            item.setText(6, '否')
            if node.level > 0:
                item.setChildIndicatorPolicy(item.ChildIndicatorPolicy.DontShowIndicator)
            self._hide_children(item)
        node.calculate_final_quantity()
        self.update_status_bar()
        return True

    def _show_selection_menu(self, item, column, pos):
        """
        显示选择菜单

        Args:
            item: 树节点项
            column: 列号
            pos: 全局坐标
        """
        node = item.data(1, Qt.UserRole)
        if not node:
            return

        # 检查是否被隐藏
        if self._is_node_hidden(node):
            return

        # 检查"是否展开"是否为"是"，则发运主体、发运方式不可维护
        if column in [7, 8] and item.text(6) == '是':
            return

        menu = QMenu(self.tree_widget)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                color: white;
            }
        """)

        if column == 6:  # 是否展开
            current_value = item.text(6)
            has_children = item.childCount() > 0
            action_yes = menu.addAction('✓ 是' if current_value == '是' else '  是')
            if not has_children:
                action_yes.setEnabled(False)
                action_yes.setToolTip('没有下级子物料，无法展开')
            else:
                action_yes.triggered.connect(lambda: item.setText(6, '是'))
            action_no = menu.addAction('✓ 否' if current_value == '否' else '  否')
            action_no.triggered.connect(lambda: item.setText(6, '否'))

        elif column == 7:  # 发运主体
            self._show_entity_selector(item)
            return

        elif column == 8:  # 发运方式
            current_value = item.text(8)
            methods = [('A', '散装'), ('B', '打捆'), ('C', '装箱'), ('D', '特殊')]
            for code, name in methods:
                full_text = f'{code}-{name}'
                prefix = '✓ ' if current_value == full_text else '  '
                action = menu.addAction(f'{prefix}{full_text}')
                action.triggered.connect(lambda checked, t=full_text: self._set_item_value(item, 8, t))

        menu.exec_(pos)

    def _set_item_value(self, item, column, value):
        """
        设置项目的值

        Args:
            item: 树节点项
            column: 列号
            value: 值
        """
        node = item.data(1, Qt.UserRole)
        if node:
            if column == 7:  # 发运主体
                entity_code = value.split('-')[0] if '-' in value else value
                # 只更新显示文本，节点数据修改与自动规则（98→B/99→C、展开→否）交由
                # setText 触发的 on_item_changed → _handle_entity_change 统一处理。
                # 关键：绝不能先改 node 再 setText——否则 on_item_changed 里的 _save_state
                # 捕获的是"改后"快照，导致选择发运主体这一高频操作无法撤销。
                item.setText(7, self._get_entity_display_name(entity_code))
                return
            elif column == 8:  # 发运方式
                method_code = value[0] if value else ''
                # 同上：节点修改交由 on_item_changed → _handle_method_change 处理，
                # 保证 _save_state 在改 node 之前捕获快照，撤销可还原
                item.setText(8, self._get_method_display_name(method_code))
                return
            elif column == 6:  # 是否展开
                return
        # 阻止信号避免重复触发 on_item_changed
        self.tree_widget.blockSignals(True)
        item.setText(column, value)
        self.tree_widget.blockSignals(False)
        self.update_status_bar()

    def _show_entity_selector(self, item):
        """
        显示发运主体选择对话框

        Args:
            item: 树节点项
        """
        node = item.data(1, Qt.UserRole)
        if not node:
            return

        current_value = item.text(7)

        dialog = QDialog(self)
        dialog.setWindowTitle('选择发运主体')
        dialog.setMinimumWidth(280)
        dialog.setMinimumHeight(400)

        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # 标题
        label = QLabel(f'物料: {node.material_id} - {node.name}')
        label.setStyleSheet('font-weight: bold; padding: 5px;')
        layout.addWidget(label)

        # 列表
        list_widget = QListWidget()
        list_widget.setStyleSheet("""
            QListWidget { padding: 2px; }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected { background-color: #0078d4; color: white; }
        """)

        # 从 entity_map 动态获取发运主体列表
        fixed_codes = ['98', '99']
        all_codes = sorted(self.entity_map.keys()) if hasattr(self, 'entity_map') and self.entity_map else []
        other_codes = [c for c in all_codes if c not in fixed_codes]

        # 添加固定项
        for code in fixed_codes:
            full_text = self._get_entity_display_name(code)
            widget_item = QListWidgetItem(f'📌 {full_text}')
            widget_item.setData(Qt.UserRole, code)
            list_widget.addItem(widget_item)

        # 分隔线
        sep_item = QListWidgetItem('─' * 30)
        sep_item.setFlags(Qt.NoItemFlags)
        sep_item.setForeground(Qt.gray)
        list_widget.addItem(sep_item)

        # 添加其余项
        for code in other_codes:
            full_text = self._get_entity_display_name(code)
            widget_item = QListWidgetItem(f'  {full_text}')
            widget_item.setData(Qt.UserRole, code)
            list_widget.addItem(widget_item)

        # 高亮当前选中
        for i in range(list_widget.count()):
            widget_item = list_widget.item(i)
            if widget_item.data(Qt.UserRole):
                item_code = widget_item.data(Qt.UserRole)
                item_display = self._get_entity_display_name(item_code)
                if current_value == item_display:
                    list_widget.setCurrentItem(widget_item)
                    break

        # 双击确认
        def on_double_click(widget_item):
            code = widget_item.data(Qt.UserRole)
            if code:
                full_text = self._get_entity_display_name(code)
                self._set_item_value(item, 7, full_text)
                dialog.accept()

        list_widget.itemDoubleClicked.connect(on_double_click)

        layout.addWidget(list_widget)

        # 底部按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: on_double_click(list_widget.currentItem()) if list_widget.currentItem() else None)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)
        dialog.exec_()

    def set_node_expand(self, node, expand):
        """
        设置节点是否展开

        与"是否展开"列点击路径（_handle_expand_change）保持同一语义：
        - 设为"是"前拦截已维护配置的节点（含备注），指向"清空发运配置"入口；
        - 设为"否"收拢子树时，若子孙已维护配置需先确认，确认后清除子孙配置，
          避免隐藏期间保留的配置在改回"是"后意外复活为发运单元。

        Args:
            node: BOM 节点
            expand: 展开状态 ('是' 或 '否')
        """
        if expand == '是' and not node.children:
            return
        if expand == '是' and (node.shipping_entity or node.shipping_method or node.remark):
            QMessageBox.warning(self, '提示',
                '该节点已配置发运主体/方式/备注，不能直接改回"是"。\n'
                '请右键该节点选择"清空发运配置"后再设置。')
            return
        if expand == '否' and self._has_children_with_config(node):
            reply = QMessageBox.question(
                self, '确认设置',
                '该节点的子物料已维护发运配置！\n\n'
                '设为"否"后将清除所有子物料的发运配置，\n'
                '它们将不再作为独立发运单元参与统计。\n\n'
                '是否继续？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._save_state()
        node.expand_status = expand
        if expand == '是':
            node.shipping_entity = ''
            node.shipping_method = ''
            node.remark = ''
        elif expand == '否':
            # 与列点击路径一致：收拢子树时清除子孙发运配置
            self._clear_children_config(node)
        node.calculate_final_quantity()
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()

    def set_node_entity(self, node, entity):
        """
        设置节点发运主体

        Args:
            node: BOM 节点
            entity: 发运主体代码
        """
        # 先捕获快照（不压栈）：B9-2 确认清除子孙配置时，撤销需能回到清除前
        snapshot = self._save_state_snapshot()
        if node.expand_status == '是':
            if not self._confirm_collapse_descendants(node):
                return
        self._push_undo_snapshot(snapshot)
        node.shipping_entity = entity
        # 应用自动规则（98→B打捆，99→C装箱）
        from core.entity_config import EntityConfigManager
        EntityConfigManager.apply_auto_rules(node)
        if node.expand_status == '是':
            node.expand_status = '否'
        node.calculate_final_quantity()
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()

    def set_node_method(self, node, method):
        """
        设置节点发运方式

        Args:
            node: BOM 节点
            method: 发运方式代码
        """
        # 先捕获快照（不压栈）：B9-2 确认清除子孙配置时，撤销需能回到清除前
        snapshot = self._save_state_snapshot()
        if node.expand_status == '是':
            if not self._confirm_collapse_descendants(node):
                return
        self._push_undo_snapshot(snapshot)
        node.shipping_method = method
        if node.expand_status == '是':
            node.expand_status = '否'
        node.calculate_final_quantity()
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()

    def _quick_apply_entity(self, entity_code, method_code):
        """
        F5/F6 快捷设置发运主体+方式

        Args:
            entity_code: 发运主体代码
            method_code: 发运方式代码
        """
        checked = self.get_checked_nodes()
        if not checked:
            current = self.tree_widget.currentItem()
            if current:
                node = current.data(1, Qt.UserRole)
                if node:
                    checked = [node]
        if not checked:
            return
        # 先捕获快照（不压栈），确认通过后再提交；拒绝则整批取消（B9-2）
        snapshot = self._save_state_snapshot()
        if not self._confirm_batch_collapse(checked):
            return
        self._push_undo_snapshot(snapshot)
        for node in checked:
            node.shipping_entity = entity_code
            # 应用自动规则（98→B打捆，99→C装箱）
            from core.entity_config import EntityConfigManager
            EntityConfigManager.apply_auto_rules(node)
            node.expand_status = '否'
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()
        entity_name = self._get_entity_display_name(entity_code)
        self.statusBar().showMessage(f'已设置 {len(checked)} 个节点: {entity_name} + {method_code}')

    def _quick_set_expand(self, value):
        """
        Y/N 快捷设置当前选中节点的是否展开

        Args:
            value: 展开状态 ('是' 或 '否')
        """
        current = self.tree_widget.currentItem()
        if not current:
            return
        node = current.data(1, Qt.UserRole)
        if not node:
            return
        # set_node_expand 内部已保存快照，此处不再重复保存，
        # 避免一次操作产生两个相同快照导致首次撤销无可见效果
        self.set_node_expand(node, value)

    def _apply_custom_config(self):
        """F4 应用自定义发运配置"""
        if not self._custom_config.get('shipping_entity'):
            self._edit_custom_config()
            return
        checked = self.get_checked_nodes()
        if not checked:
            current = self.tree_widget.currentItem()
            if current:
                node = current.data(1, Qt.UserRole)
                if node:
                    checked = [node]
        if not checked:
            return
        # 先捕获快照（不压栈），确认通过后再提交；拒绝则整批取消（B9-2）
        snapshot = self._save_state_snapshot()
        if not self._confirm_batch_collapse(checked):
            return
        self._push_undo_snapshot(snapshot)
        cfg = self._custom_config
        for node in checked:
            node.shipping_entity = cfg['shipping_entity']
            node.shipping_method = cfg['shipping_method']
            node.expand_status = '否'
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()
        entity_name = self._get_entity_display_name(cfg['shipping_entity'])
        QMessageBox.information(self, '成功',
            f'已将 {len(checked)} 个节点设置为:\n'
            f'发运主体: {entity_name}\n'
            f'发运方式: {cfg["shipping_method"]}')

    def _edit_custom_config(self):
        """编辑F4自定义发运配置"""
        from PyQt5.QtWidgets import QFormLayout, QComboBox

        dialog = QDialog(self)
        dialog.setWindowTitle('定义 F4 快捷配置')
        dialog.setMinimumWidth(300)

        layout = QFormLayout()

        combo_entity = QComboBox()
        for code in self._get_all_entity_codes():
            combo_entity.addItem(self._get_entity_display_name(code), code)
        if self._custom_config.get('shipping_entity'):
            idx = combo_entity.findData(self._custom_config['shipping_entity'])
            if idx >= 0:
                combo_entity.setCurrentIndex(idx)
        layout.addRow('发运主体:', combo_entity)

        combo_method = QComboBox()
        methods = [('', '请选择'), ('A', 'A-散装'), ('B', 'B-打捆'), ('C', 'C-装箱'), ('D', 'D-特殊')]
        for code, name in methods:
            combo_method.addItem(name, code)
        if self._custom_config.get('shipping_method'):
            idx = combo_method.findData(self._custom_config['shipping_method'])
            if idx >= 0:
                combo_method.setCurrentIndex(idx)
        layout.addRow('发运方式:', combo_method)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        dialog.setLayout(layout)

        if dialog.exec_() == QDialog.Accepted:
            entity = combo_entity.currentData()
            method = combo_method.currentData()
            if not entity:
                QMessageBox.warning(self, '提示', '请选择发运主体！')
                return
            self._custom_config = {
                'shipping_entity': entity,
                'shipping_method': method,
            }
            entity_name = self._get_entity_display_name(entity)
            self.statusBar().showMessage(f'F4配置已更新: {entity_name} + {method}')

    def _copy_format(self, node):
        """
        复制节点的发运格式

        Args:
            node: BOM 节点
        """
        self._clipboard_config = {
            'expand_status': node.expand_status,
            'shipping_entity': node.shipping_entity,
            'shipping_method': node.shipping_method,
            'remark': node.remark,
        }

    def _shortcut_copy_format(self):
        """快捷键复制当前选中节点的格式"""
        item = self.tree_widget.currentItem()
        if item:
            node = item.data(1, Qt.UserRole)
            if node:
                self._copy_format(node)
                self.statusBar().showMessage(
                    f'已复制格式: 展开={node.expand_status}, 主体={node.shipping_entity}, 方式={node.shipping_method}')

    def _paste_format_to_checked(self):
        """
        将复制的格式粘贴到所有勾选的节点

        粘贴前逐节点过滤不适用的节点并分类提示，避免静默破坏树结构
        （历史缺陷：粘贴"否"到顶级/高层节点会隐藏整棵子树，界面塌缩成只剩最高级）：
        - 顶级节点（level==0）不接受任何格式；
        - 隐藏节点（位于"否"边界之下）不可被操作；
        - 粘贴"展开=是"格式时跳过叶子节点（没有子级可展开）；
        - 粘贴"否"格式时跳过子孙已维护配置的节点（避免静默清除已维护的子树，
          确需整体收拢时请使用带确认对话框的单节点操作路径）。
        """
        if not self._clipboard_config:
            QMessageBox.warning(self, '提示', '请先右键点击一个节点"复制格式"')
            return

        checked = self.get_checked_nodes()
        if not checked:
            QMessageBox.information(self, '提示', '没有勾选任何节点！')
            return

        config = self._clipboard_config
        paste_expand = config['expand_status'] == '是'

        # 写入前逐节点过滤：跳过的节点分类计数，剩余目标节点统一应用
        targets = []
        skip_top = 0         # 顶级节点
        skip_hidden = 0      # 隐藏节点（位于"否"边界之下）
        skip_leaf = 0        # 叶子节点（仅粘贴"是"时）
        skip_maintained = 0  # 子孙已维护配置（仅粘贴"否"时）
        for node in checked:
            if node.level == 0:
                skip_top += 1
                continue
            if self._is_node_hidden(node):
                skip_hidden += 1
                continue
            if paste_expand and not node.children:
                skip_leaf += 1
                continue
            if not paste_expand and self._has_children_with_config(node):
                skip_maintained += 1
                continue
            targets.append(node)

        if targets:
            self._save_state()
            for node in targets:
                if paste_expand:
                    # 粘贴"展开=是"时，清空发运配置
                    node.expand_status = '是'
                    node.shipping_entity = ''
                    node.shipping_method = ''
                    node.remark = ''
                else:
                    # 粘贴"展开=否"时，设置发运配置
                    node.expand_status = '否'
                    node.shipping_entity = config['shipping_entity']
                    node.shipping_method = config['shipping_method']
                    node.remark = config['remark']
            self.refresh_tree(preserve_expand_state=True)
            self.update_status_bar()

        # 结果提示：应用数量 + 跳过数量与原因分类
        skip_reasons = []
        if skip_top:
            skip_reasons.append(f'顶级节点 {skip_top} 个')
        if skip_hidden:
            skip_reasons.append(f'隐藏节点 {skip_hidden} 个')
        if skip_leaf:
            skip_reasons.append(f'叶子节点（无子级可展开）{skip_leaf} 个')
        if skip_maintained:
            skip_reasons.append(f'子孙已维护配置 {skip_maintained} 个')
        skipped = skip_top + skip_hidden + skip_leaf + skip_maintained
        fmt_desc = (f'展开={config["expand_status"]}, '
                    f'主体={config["shipping_entity"]}, '
                    f'方式={config["shipping_method"]}')

        if not targets:
            QMessageBox.information(self, '提示',
                '没有可粘贴的节点，未做任何修改。\n\n'
                f'勾选的 {skipped} 个节点均被跳过：\n' + '\n'.join(skip_reasons))
            return

        msg = f'已将格式粘贴到 {len(targets)} 个节点\n（{fmt_desc}）'
        if skipped:
            msg += f'\n\n另跳过 {skipped} 个不适用节点：\n' + '\n'.join(skip_reasons)
        QMessageBox.information(self, '成功', msg)

    def _clear_node_shipping_config(self, node):
        """
        清空节点的发运配置（主体/方式/备注）

        只清空该节点自身的配置，不改变"是否展开"状态，不影响子孙节点。
        与 set_node_expand 的拦截配合：已维护配置的节点先清空配置，才能改回"是"。

        Args:
            node: BOM 节点
        """
        if not (node.shipping_entity or node.shipping_method or node.remark):
            return
        reply = QMessageBox.question(
            self, '确认清空',
            f'将清空节点 {node.material_id} 的发运主体、发运方式和备注。\n'
            '（不改变"是否展开"状态，不影响子节点）\n\n是否继续？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._save_state()
        node.shipping_entity = ''
        node.shipping_method = ''
        node.remark = ''
        node.calculate_final_quantity()
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()
        self.statusBar().showMessage(f'已清空节点 {node.material_id} 的发运配置')

    def _set_remark_to_checked(self):
        """将备注设置到所有勾选的节点"""
        from PyQt5.QtWidgets import QInputDialog

        checked = self.get_checked_nodes()
        if not checked:
            QMessageBox.information(self, '提示', '没有勾选任何节点！\n请先在左侧勾选需要设置备注的节点。')
            return

        current_remark = checked[0].remark if checked else ''
        text, ok = QInputDialog.getText(
            self, '设置备注',
            f'将为 {len(checked)} 个勾选节点设置相同备注：',
            text=current_remark
        )
        if not ok:
            return

        self._save_state()

        # 一次性建立 uid -> item 映射，避免每个节点都从所有顶层项重新递归查找（B2）
        item_map = {}

        def collect(item):
            node = item.data(1, Qt.UserRole)
            if node:
                item_map[node.uid] = item
            for i in range(item.childCount()):
                collect(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            collect(self.tree_widget.topLevelItem(i))

        # 抑制 itemChanged 重入：批量 setText 不应为每个节点再压一次撤销快照
        prev_in_item_changed = getattr(self, '_in_item_changed', False)
        self._in_item_changed = True
        try:
            for node in checked:
                node.remark = text
                item = item_map.get(node.uid)
                if item is not None:
                    item.setText(9, text)
        finally:
            self._in_item_changed = prev_in_item_changed

        self.statusBar().showMessage(f'已为 {len(checked)} 个节点设置备注')
