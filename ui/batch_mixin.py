"""
批量操作和物料管理 Mixin

提供批量设置、物料增删拆分、复选框操作等功能
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel,
                             QComboBox, QLineEdit, QDoubleSpinBox,
                             QDialogButtonBox, QMessageBox, QGroupBox,
                             QTreeWidgetItem)
from PyQt5.QtCore import Qt

from models.bom_node import BOMNode


class BatchMixin:
    """批量操作和物料管理 Mixin"""

    def batch_config(self):
        """批量设置发运配置（对勾选的节点）"""
        if not self.tree_builder.all_nodes:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        checked_nodes = self.get_checked_nodes()
        if not checked_nodes:
            QMessageBox.information(self, '提示', '请先在树结构中勾选需要设置的节点（点击复选框）')
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f'批量设置 - {len(checked_nodes)} 个节点')
        dialog.setFixedSize(350, 250)

        layout = QVBoxLayout()

        info_label = QLabel(f'将对 {len(checked_nodes)} 个勾选的节点进行批量设置:')
        layout.addWidget(info_label)

        form_layout = QFormLayout()

        # 是否展开
        combo_expand = QComboBox()
        combo_expand.addItems(['', '否', '是'])
        combo_expand.setCurrentText('')
        form_layout.addRow('是否展开:', combo_expand)

        # 发运主体
        combo_entity = QComboBox()
        combo_entity.setEditable(True)
        entity_items = [''] + [self._get_entity_display_name(code) for code in self._get_all_entity_codes()]
        combo_entity.addItems(entity_items)
        form_layout.addRow('发运主体:', combo_entity)

        # 发运方式
        combo_method = QComboBox()
        combo_method.setEditable(True)
        combo_method.addItems(['', 'A-散装', 'B-打捆', 'C-装箱', 'D-特殊'])
        form_layout.addRow('发运方式:', combo_method)

        # 联动逻辑：选择"展开=是"时禁用发运主体/方式
        def on_expand_changed(text):
            is_expand = (text == '是')
            combo_entity.setEnabled(not is_expand)
            combo_method.setEnabled(not is_expand)
            edit_remark.setEnabled(not is_expand)
            if is_expand:
                combo_entity.setCurrentText('')
                combo_method.setCurrentText('')
                edit_remark.clear()

        combo_expand.currentTextChanged.connect(on_expand_changed)

        # 备注
        edit_remark = QLineEdit()
        edit_remark.setPlaceholderText('留空则不修改')
        form_layout.addRow('备注:', edit_remark)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec_() == QDialog.Accepted:
            expand = combo_expand.currentText()
            entity_text = combo_entity.currentText()
            entity = entity_text.split('-')[0] if '-' in entity_text else entity_text
            method_text = combo_method.currentText()
            method = method_text[0] if method_text and '-' in method_text else method_text
            remark = edit_remark.text().strip()

            # 先捕获快照（不压栈），仅在确有节点被修改后才推入撤销栈并标脏，
            # 避免勾选节点全为展开节点（全被跳过、无实际变更）时产生无意义撤销点
            snapshot = self._save_state_snapshot()
            count = 0
            skipped = 0
            # 导入自动规则模块
            from core.entity_config import EntityConfigManager
            
            for node in checked_nodes:
                # 设置展开状态
                if expand:
                    node.expand_status = expand
                # 设为"是"= 不维护：与单节点路径（_handle_expand_change）一致，
                # 清空发运主体/方式/备注，避免界面残留旧配置
                if expand == '是':
                    node.shipping_entity = ''
                    node.shipping_method = ''
                    node.remark = ''
                # 设置发运主体/方式：展开的节点不允许设置
                if entity or method:
                    if node.expand_status == '是':
                        skipped += 1
                        continue
                    if entity:
                        node.shipping_entity = entity
                    if method:
                        node.shipping_method = method
                    # 主体和方式可同时生效；仅 98→B打捆、99→C装箱 时自动规则覆盖手动方式
                    if entity:
                        EntityConfigManager.apply_auto_rules(node)
                # 备注：展开节点不维护备注，不写入
                if remark and node.expand_status != '是':
                    node.remark = remark
                node.calculate_final_quantity()
                count += 1

            if skipped > 0:
                QMessageBox.information(self, '提示',
                    f'已设置 {count} 个节点，跳过 {skipped} 个展开节点（展开节点不允许设置发运配置）')

            if count > 0:
                self._push_undo_snapshot(snapshot)
                self._dirty = True
                self._update_title()
            self.refresh_tree()
            self.update_status_bar()
            QMessageBox.information(self, '成功', f'已批量设置 {count} 个节点')

    def get_checked_nodes(self):
        """获取所有勾选的节点（不含隐藏节点）"""
        checked_nodes = []

        def check_item(item):
            # 隐藏节点（位于"否"边界之下）不参与批量操作，
            # 避免触达用户不可见的节点（如残留勾选状态被静默粘贴/删除）
            if item.isHidden():
                return
            if item.checkState(0) == Qt.Checked:
                node = item.data(1, Qt.UserRole)
                if node:
                    # 双重检查：确保节点确实不是隐藏的（使用 _is_node_hidden 判断）
                    if not self._is_node_hidden(node):
                        checked_nodes.append(node)
            for i in range(item.childCount()):
                check_item(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            check_item(self.tree_widget.topLevelItem(i))

        return checked_nodes

    def select_all_nodes(self):
        """全选所有节点"""
        self._set_all_check_state(Qt.Checked)
        self.update_status_bar()

    def deselect_all_nodes(self):
        """取消全选"""
        self._set_all_check_state(Qt.Unchecked)
        self.update_status_bar()

    def invert_select_nodes(self):
        """反选所有节点（不含隐藏节点）"""
        def invert_item_state(item):
            # 隐藏节点（位于"否"边界之下）不参与反选
            if item.isHidden():
                return
            current_state = item.checkState(0)
            new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
            item.setCheckState(0, new_state)
            for i in range(item.childCount()):
                invert_item_state(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            invert_item_state(self.tree_widget.topLevelItem(i))
        self.update_status_bar()

    def check_selected_items(self):
        """对选中的行进行勾选（自动取消祖先节点勾选）"""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            current_item = self.tree_widget.currentItem()
            if current_item:
                current_item.setCheckState(0, Qt.Checked)
                self._uncheck_ancestors(current_item)
        else:
            for item in selected_items:
                item.setCheckState(0, Qt.Checked)
                self._uncheck_ancestors(item)
        self.update_status_bar()

    def uncheck_selected_items(self):
        """取消选中行的勾选"""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            current_item = self.tree_widget.currentItem()
            if current_item:
                current_item.setCheckState(0, Qt.Unchecked)
        else:
            for item in selected_items:
                item.setCheckState(0, Qt.Unchecked)
        self.update_status_bar()

    def _set_all_check_state(self, state):
        """设置所有节点的复选框状态（不含隐藏节点）"""
        def set_item_state(item):
            # 隐藏节点（位于"否"边界之下）不参与全选/取消全选
            if item.isHidden():
                return
            item.setCheckState(0, state)
            for i in range(item.childCount()):
                set_item_state(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            set_item_state(self.tree_widget.topLevelItem(i))

    def _check_range(self, start_item, end_item, checked):
        """勾选/取消勾选两个项目之间的所有项目"""
        all_items = []
        def collect_items(item):
            all_items.append(item)
            for i in range(item.childCount()):
                collect_items(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            collect_items(self.tree_widget.topLevelItem(i))

        try:
            start_idx = all_items.index(start_item)
            end_idx = all_items.index(end_item)
            if start_idx > end_idx:
                start_idx, end_idx = end_idx, start_idx
            state = Qt.Checked if checked else Qt.Unchecked
            for i in range(start_idx, end_idx + 1):
                all_items[i].setCheckState(0, state)
                if checked:
                    self._uncheck_ancestors(all_items[i])
        except ValueError:
            state = Qt.Checked if checked else Qt.Unchecked
            end_item.setCheckState(0, state)
            if checked:
                self._uncheck_ancestors(end_item)

    def add_material_row(self, parent_node=None):
        """
        添加物料行

        Args:
            parent_node: 父节点（可选）
        """
        dialog = QDialog(self)
        dialog.setWindowTitle('添加子物料' if parent_node else '添加物料行')
        dialog.setFixedSize(400, 350)

        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # 父物料号
        edit_parent = QLineEdit()
        if parent_node:
            edit_parent.setText(parent_node.material_id)
            edit_parent.setReadOnly(True)
            form_layout.addRow('父物料号:', edit_parent)
            info_label = QLabel(f'当前父节点: {parent_node.name} ({parent_node.material_id})')
            info_label.setStyleSheet('color: #666; font-size: 11px;')
            form_layout.addRow('', info_label)
        else:
            edit_parent.setPlaceholderText('留空表示顶级节点')
            form_layout.addRow('父物料号:', edit_parent)

        edit_material = QLineEdit()
        edit_material.setPlaceholderText('必填')
        form_layout.addRow('物料号:', edit_material)

        edit_name = QLineEdit()
        form_layout.addRow('名称:', edit_name)

        edit_drawing = QLineEdit()
        form_layout.addRow('图号:', edit_drawing)

        edit_spec = QLineEdit()
        form_layout.addRow('规格:', edit_spec)

        spin_quantity = QDoubleSpinBox()
        spin_quantity.setRange(0, 999999)
        spin_quantity.setValue(1)
        form_layout.addRow('数量:', spin_quantity)

        spin_weight = QDoubleSpinBox()
        spin_weight.setRange(0, 999999)
        spin_weight.setDecimals(4)
        form_layout.addRow('净重(kg):', spin_weight)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec_() == QDialog.Accepted:
            parent_id = edit_parent.text().strip()
            material_id = edit_material.text().strip()
            name = edit_name.text().strip()
            drawing = edit_drawing.text().strip()
            spec = edit_spec.text().strip()
            quantity = spin_quantity.value()
            weight = spin_weight.value()

            if not material_id:
                QMessageBox.warning(self, '警告', '物料号不能为空！')
                return

            level = (parent_node.level + 1) if parent_node else 0
            new_node = BOMNode(
                material_id=material_id,
                parent_id=parent_id,
                drawing_no=drawing,
                specification=spec,
                name=name,
                quantity=quantity,
                weight=weight,
                level=level,
                expand_status='是' if level == 0 else '否'
            )

            # 变更前捕获快照（不压栈），仅在成功添加后推入撤销栈，
            # 避免"未找到父节点/已存在顶级节点"等失败分支产生无意义撤销点
            snapshot = self._save_state_snapshot()
            if parent_node:
                parent_node.add_child(new_node)
            elif parent_id:
                found_parent = None
                for node in self.tree_builder.all_nodes:
                    if node.material_id == parent_id:
                        found_parent = node
                        break
                if found_parent:
                    found_parent.add_child(new_node)
                else:
                    QMessageBox.warning(self, '警告', f'未找到父物料号: {parent_id}')
                    return
            else:
                if self.tree_builder.root:
                    QMessageBox.warning(self, '警告', '已存在顶级节点，不能添加新的顶级节点')
                    return
                self.tree_builder.root = new_node

            self.tree_builder.all_nodes.append(new_node)
            # 成功添加：提交快照并标记未保存
            self._push_undo_snapshot(snapshot)
            self._dirty = True
            self._update_title()
            self.refresh_tree()
            self.update_status_bar()
            QMessageBox.information(self, '成功', f'已添加物料: {material_id}')

    def delete_material(self, node):
        """
        删除单个物料（级联删除子节点）

        Args:
            node: BOM 节点
        """
        descendants = node.get_all_descendants()
        total = len(descendants) + 1

        if node.children:
            reply = QMessageBox.question(
                self, '确认删除',
                f'该物料有 {len(node.children)} 个子节点，共 {total} 个节点将被删除。\n\n'
                f'确定要删除 "{node.material_id} - {node.name}" 及其所有子节点吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, '确认删除',
                f'确定要删除物料 "{node.material_id} - {node.name}" 吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

        if reply == QMessageBox.Yes:
            self._save_state()
            if node.parent:
                node.parent.children.remove(node)
            else:
                # 删除顶级节点后清空 root 引用，避免被删节点残留并继续参与
                # 显示与计算（原实现仅从 all_nodes 移除，树仍显示整个子树）
                if self.tree_builder.root is node:
                    self.tree_builder.root = None
            to_remove = [node] + descendants
            for n in to_remove:
                if n in self.tree_builder.all_nodes:
                    self.tree_builder.all_nodes.remove(n)
            self.refresh_tree()
            self.update_status_bar()
            QMessageBox.information(self, '成功', f'已删除 {total} 个物料')

    def split_material(self, node, item):
        """
        拆分物料为两个发运单元

        Args:
            node: BOM 节点
            item: 树节点项
        """
        if node.children:
            QMessageBox.warning(self, '警告', '有子节点的物料不能拆分！\n请先删除子节点。')
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f'拆分物料 - {node.material_id}')
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout()

        info = QLabel(f'物料: {node.material_id}\n名称: {node.name}\n原始数量: {node.quantity}')
        info.setStyleSheet("font-weight: bold; padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(info)

        # 第一部分
        group1 = QGroupBox("第一部分")
        form1 = QFormLayout()

        entity1 = QComboBox()
        entity1.setEditable(True)
        entity1.addItems([''] + [self._get_entity_display_name(e) for e in self._get_all_entity_codes()])
        if node.shipping_entity:
            entity1.setCurrentText(self._get_entity_display_name(node.shipping_entity))
        form1.addRow('发运主体:', entity1)

        method1 = QComboBox()
        method1.addItems(['', 'A-散装', 'B-打捆', 'C-装箱', 'D-特殊'])
        if node.shipping_method:
            method_map = {'A': 'A-散装', 'B': 'B-打捆', 'C': 'C-装箱', 'D': 'D-特殊'}
            method1.setCurrentText(method_map.get(node.shipping_method, ''))
        form1.addRow('发运方式:', method1)

        qty1 = QDoubleSpinBox()
        qty1.setRange(0, 999999)
        qty1.setValue(node.quantity / 2)
        qty1.setDecimals(0)
        form1.addRow('数量:', qty1)

        group1.setLayout(form1)
        layout.addWidget(group1)

        # 第二部分
        group2 = QGroupBox("第二部分")
        form2 = QFormLayout()

        entity2 = QComboBox()
        entity2.setEditable(True)
        entity2.addItems([''] + [self._get_entity_display_name(e) for e in self._get_all_entity_codes()])
        form2.addRow('发运主体:', entity2)

        method2 = QComboBox()
        method2.addItems(['', 'A-散装', 'B-打捆', 'C-装箱', 'D-特殊'])
        form2.addRow('发运方式:', method2)

        qty2_label = QLabel(f'{node.quantity / 2:.0f}')
        form2.addRow('数量:', qty2_label)

        def update_qty2():
            remaining = node.quantity - qty1.value()
            qty2_label.setText(f'{remaining:.0f}')
        qty1.valueChanged.connect(update_qty2)

        group2.setLayout(form2)
        layout.addWidget(group2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec_() == QDialog.Accepted:
            e1_text = entity1.currentText()
            e1_code = e1_text.split('-')[0] if '-' in e1_text else e1_text
            m1_text = method1.currentText()
            m1_code = m1_text[0] if m1_text else ''

            e2_text = entity2.currentText()
            e2_code = e2_text.split('-')[0] if '-' in e2_text else e2_text
            m2_text = method2.currentText()
            m2_code = m2_text[0] if m2_text else ''

            q1 = qty1.value()
            q2 = node.quantity - q1

            if q1 <= 0 or q2 <= 0:
                QMessageBox.warning(self, '警告', '两部分数量必须都大于0！')
                return

            if not e1_code or not m1_code or not e2_code or not m2_code:
                QMessageBox.warning(self, '警告', '请填写完整的发运主体和发运方式！')
                return

            if node.level == 0:
                QMessageBox.warning(self, '警告',
                    '顶级节点不能拆分！\n'
                    '当前版本仅支持单个顶级节点，拆分出的第二部分无法挂载到树中，'
                    '会静默丢失且不参与计算。')
                return

            self._save_state()

            node.quantity = q1
            node.shipping_entity = e1_code
            node.shipping_method = m1_code
            node.expand_status = '否'
            node.calculate_final_quantity()

            node2 = BOMNode(
                material_id=node.material_id,
                parent_id=node.parent_id,
                project_id=node.project_id,
                drawing_no=node.drawing_no,
                specification=node.specification,
                name=node.name + '-2',
                quantity=q2,
                weight=node.weight,
                level=node.level,
                expand_status='否',
                shipping_entity=e2_code,
                shipping_method=m2_code,
                remark=node.remark,
            )

            # 先建立父引用再挂载，最后重算最终数量：
            # 第二部分数量 = 自身数量 × 父节点最终数量。
            # 原实现在挂载前按顶级节点计算（漏乘父节点倍数），且未设置
            # node2.parent，导致隐藏判断（祖先"否"边界）全部失效。
            node2.parent = node.parent
            if node.parent:
                node.parent.children.append(node2)
                node2.calculate_final_quantity()
            self.tree_builder.all_nodes.append(node2)

            self.refresh_tree(preserve_expand_state=True)
            self.update_status_bar()
            QMessageBox.information(self, '成功',
                f'物料已拆分：\n'
                f'第一部分: {q1:.0f} → {e1_code} {m1_code}\n'
                f'第二部分: {q2:.0f} → {e2_code} {m2_code}')

    def delete_checked_nodes(self):
        """删除所有勾选的节点（级联删除子节点）"""
        checked_nodes = self.get_checked_nodes()

        if not checked_nodes:
            QMessageBox.information(self, '提示', '没有勾选任何节点！')
            return

        all_to_remove = []
        seen = set()
        for node in checked_nodes:
            if id(node) not in seen:
                all_to_remove.append(node)
                seen.add(id(node))
            for desc in node.get_all_descendants():
                if id(desc) not in seen:
                    all_to_remove.append(desc)
                    seen.add(id(desc))

        nodes_with_children = [n for n in checked_nodes if n.children]
        total = len(all_to_remove)

        if nodes_with_children:
            names = ', '.join([n.material_id for n in nodes_with_children[:5]])
            if len(nodes_with_children) > 5:
                names += f' 等{len(nodes_with_children)}个'
            reply = QMessageBox.question(
                self, '确认批量删除',
                f'勾选了 {len(checked_nodes)} 个节点，其中 {len(nodes_with_children)} 个有子节点。\n'
                f'共 {total} 个节点将被删除。\n\n'
                f'有子节点的: {names}\n\n'
                f'确定要删除吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, '确认批量删除',
                f'确定要删除勾选的 {len(checked_nodes)} 个物料吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

        if reply == QMessageBox.Yes:
            self._save_state()
            for node in checked_nodes:
                if node.parent:
                    node.parent.children.remove(node)
            for n in all_to_remove:
                if n in self.tree_builder.all_nodes:
                    self.tree_builder.all_nodes.remove(n)
            # 若顶级节点被批量删除，清空 root 引用（与 delete_material 保持一致）
            if self.tree_builder.root not in self.tree_builder.all_nodes:
                self.tree_builder.root = None
            self.refresh_tree()
            self.update_status_bar()
            QMessageBox.information(self, '成功', f'已删除 {total} 个物料')

    def _delete_key_handler(self):
        """Delete 键：优先删除勾选节点，否则删除右键选中的节点"""
        checked = self.get_checked_nodes()
        if checked:
            self.delete_checked_nodes()
        else:
            current = self.tree_widget.currentItem()
            if current:
                node = current.data(1, Qt.UserRole)
                if node:
                    self.delete_material(node)

    def _on_custom_config_btn(self):
        """F4按钮点击"""
        self._edit_custom_config()

    def show_tree_context_menu(self, pos):
        """显示树节点右键菜单"""
        from PyQt5.QtWidgets import QMenu

        item = self.tree_widget.itemAt(pos)
        if not item:
            return

        node = item.data(1, Qt.UserRole)
        if not node:
            return

        menu = QMenu(self)

        # 展开/折叠
        expand_action = menu.addAction('展开')
        expand_action.triggered.connect(lambda: self.tree_widget.expandItem(item))
        collapse_action = menu.addAction('折叠')
        collapse_action.triggered.connect(lambda: self.tree_widget.collapseItem(item))
        menu.addSeparator()

        # 是否展开
        expand_menu = menu.addMenu('设置是否展开')
        expand_yes = expand_menu.addAction('是 (继续展开子节点)')
        expand_yes.triggered.connect(lambda: self.set_node_expand(node, '是'))
        expand_no = expand_menu.addAction('否 (设为发运单元)')
        expand_no.triggered.connect(lambda: self.set_node_expand(node, '否'))

        # 清空发运配置：配合"设置是否展开→是"的拦截提示
        # （已维护配置的节点需先清空配置，才能改回"是"）
        clear_cfg_action = menu.addAction('🧹 清空发运配置')
        clear_cfg_action.setEnabled(bool(node.shipping_entity or node.shipping_method or node.remark))
        clear_cfg_action.triggered.connect(lambda: self._clear_node_shipping_config(node))
        menu.addSeparator()

        # 发运主体
        entity_menu = menu.addMenu('设置发运主体')
        for entity in self._get_all_entity_codes():
            entity_action = entity_menu.addAction(self._get_entity_display_name(entity))
            entity_action.triggered.connect(lambda checked, e=entity: self.set_node_entity(node, e))

        # 发运方式
        method_menu = menu.addMenu('设置发运方式')
        for code, name in [('A', '散装'), ('B', '打捆'), ('C', '装箱'), ('D', '特殊')]:
            action = method_menu.addAction(f'{code} - {name}')
            action.triggered.connect(lambda checked, c=code: self.set_node_method(node, c))

        menu.addSeparator()

        # 其他操作
        edit_action = menu.addAction('详细配置...')
        edit_action.triggered.connect(lambda: self.edit_tree_node(item))

        menu.addSeparator()

        expand_all_action = menu.addAction('展开所有子节点')
        expand_all_action.triggered.connect(lambda: self.expand_all_children(item))
        collapse_all_action = menu.addAction('折叠所有子节点')
        collapse_all_action.triggered.connect(lambda: self.collapse_all_children(item))

        menu.addSeparator()

        split_action = menu.addAction('✂️ 拆分物料')
        split_action.triggered.connect(lambda: self.split_material(node, item))

        delete_action = menu.addAction('删除物料')
        delete_action.triggered.connect(lambda: self.delete_material(node))

        add_child_action = menu.addAction('➕ 添加子物料')
        add_child_action.triggered.connect(lambda: self.add_material_row(parent_node=node))

        menu.addSeparator()

        remark_action = menu.addAction('📝 设置备注到勾选节点')
        remark_action.triggered.connect(self._set_remark_to_checked)

        copy_fmt_action = menu.addAction('📋 复制格式')
        copy_fmt_action.triggered.connect(lambda: self._copy_format(node))

        paste_fmt_action = menu.addAction('📋 粘贴格式到勾选节点')
        paste_fmt_action.setEnabled(self._clipboard_config is not None)
        paste_fmt_action.triggered.connect(self._paste_format_to_checked)

        menu.exec_(self.tree_widget.mapToGlobal(pos))
