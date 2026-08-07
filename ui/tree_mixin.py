"""
树结构操作 Mixin

提供 BOM 树结构的显示、刷新、展开/折叠等操作
"""

from PyQt5.QtWidgets import QTreeWidgetItem, QTreeWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette

from models.bom_node import BOMNode, ExpandStatus


class TreeMixin:
    """树结构操作 Mixin"""

    def refresh_tree(self, preserve_expand_state=True):
        """
        刷新树结构显示

        Args:
            preserve_expand_state: 是否保留展开状态
        """
        # 记录当前展开状态（以节点稳定 uid 为键，避免同物料号多实例互相串位）
        expanded_nodes = set()
        if preserve_expand_state:
            def collect_expanded(item):
                if item.isExpanded():
                    node = item.data(1, Qt.UserRole)
                    if node:
                        expanded_nodes.add(node.uid)
                for i in range(item.childCount()):
                    collect_expanded(item.child(i))

            for i in range(self.tree_widget.topLevelItemCount()):
                collect_expanded(self.tree_widget.topLevelItem(i))

        self.tree_widget.clear()

        # 构建树时断开信号，避免每个setText触发on_item_changed导致卡顿
        try:
            self.tree_widget.itemChanged.disconnect()
        except TypeError:
            pass

        # 建树与恢复展开放入 try/finally：即使中途异常也确保信号重连，
        # 否则 itemChanged 永久断开、所有列编辑静默失效（下次 refresh 自愈）
        try:
            if self.tree_builder.root:
                self._add_tree_item(self.tree_widget, self.tree_builder.root)

                # 恢复展开状态
                if preserve_expand_state and expanded_nodes:
                    def restore_expanded(item):
                        node = item.data(1, Qt.UserRole)
                        if node and node.uid in expanded_nodes:
                            item.setExpanded(True)
                        for i in range(item.childCount()):
                            restore_expanded(item.child(i))

                    for i in range(self.tree_widget.topLevelItemCount()):
                        restore_expanded(self.tree_widget.topLevelItem(i))
                else:
                    # 默认折叠所有节点，只展开顶级节点
                    self.tree_widget.collapseAll()
                    self.tree_widget.expandToDepth(0)
        finally:
            # 重连前先带 TypeError 守卫 disconnect，防止重复连接导致
            # on_item_changed 双触发、_save_state 泛洪撤销栈
            try:
                self.tree_widget.itemChanged.disconnect()
            except TypeError:
                pass
            self.tree_widget.itemChanged.connect(self.on_item_changed)

    def _add_tree_item(self, parent, node: BOMNode):
        """
        递归添加树节点

        Args:
            parent: 父节点（QTreeWidget 或 QTreeWidgetItem）
            node: BOM 节点
        """
        item = QTreeWidgetItem()

        # 设置标志：可编辑、可勾选（备注列支持双击编辑）
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
        item.setCheckState(0, Qt.Unchecked)

        # 设置列数据（列0是复选框）
        item.setText(1, node.material_id)
        item.setText(2, node.name)
        item.setText(3, node.drawing_no)
        item.setText(4, node.specification)
        # 数量显示为整数
        qty = int(node.quantity) if node.quantity == int(node.quantity) else node.quantity
        item.setText(5, str(qty))
        item.setText(6, node.expand_status)
        # 发运主体/发运方式/备注
        item.setText(7, self._get_entity_display_name(node.shipping_entity) if node.shipping_entity else '')
        item.setText(8, self._get_method_display_name(node.shipping_method) if node.shipping_method else '')
        item.setText(9, node.remark if node.remark else '')

        # 设置列flag：可启用、可选中、可勾选、可编辑
        base_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEditable
        item.setFlags(base_flags)

        # 存储节点引用
        item.setData(1, Qt.UserRole, node)

        # 添加到父节点
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)

        # 状态显示 + 背景色（添加到树之后，确保parent正确）
        self._update_item_style(item, node)

        # 检查是否有祖先节点设置了"是否展开=否"
        if self._is_node_hidden(node):
            item.setHidden(True)

        # 递归添加子节点
        for child in node.children:
            self._add_tree_item(item, child)

        # 如果"是否展开=否"且不是顶级节点，隐藏展开箭头和所有子节点
        if node.expand_status == '否' and node.level > 0:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            self._hide_children(item)

    def _update_item_style(self, item, node):
        """
        更新节点的背景色和状态显示

        Args:
            item: 树节点项
            node: BOM 节点
        """
        if node.is_shipping_unit:
            status = "发运单元"
            bg = QColor(76, 175, 80)
        elif node.expand_status == ExpandStatus.NO:
            status = "边界节点"
            bg = QColor(253, 246, 227)
        else:
            status = "展开节点"
            bg = QColor(255, 255, 255)

        for col in range(0, 11):
            item.setBackground(col, bg)
        item.setText(10, status)

    def _is_node_hidden(self, node):
        """
        检查节点是否被隐藏（祖先节点expand_status='否'）

        Args:
            node: BOM 节点

        Returns:
            是否被隐藏
        """
        current = node
        while current.parent:
            if current.parent.expand_status == '否':
                return True
            current = current.parent
        return False

    def _hide_children(self, item):
        """
        隐藏所有子节点

        Args:
            item: 树节点项
        """
        for i in range(item.childCount()):
            child = item.child(i)
            child.setHidden(True)
            # 禁用子节点的编辑和勾选
            child.setFlags(child.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsUserCheckable)
            self._hide_children(child)

    def _show_children(self, item, recursive=True):
        """
        显示子节点

        Args:
            item: 树节点项
            recursive: 是否递归显示
        """
        # 恢复展开箭头
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        for i in range(item.childCount()):
            child = item.child(i)
            child.setHidden(False)
            # 恢复子节点的交互（包括可编辑）
            base_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEditable
            child.setFlags(base_flags)
            if recursive:
                self._show_children(child, recursive=True)

    def _has_children_with_config(self, node):
        """
        检查是否有子孙节点已维护发运配置或展开状态为是

        Args:
            node: BOM 节点

        Returns:
            是否有子孙节点有配置
        """
        for child in node.children:
            if child.shipping_entity or child.shipping_method or child.remark or child.expand_status == '是':
                return True
            if self._has_children_with_config(child):
                return True
        return False

    def _clear_children_config(self, node):
        """
        递归清除所有子孙节点的发运配置和展开状态

        Args:
            node: BOM 节点
        """
        for child in node.children:
            child.shipping_entity = ''
            child.shipping_method = ''
            child.remark = ''
            child.expand_status = '否'
            self._clear_children_config(child)

    def _update_children_display(self, item):
        """
        递归更新所有子节点的显示

        Args:
            item: 树节点项
        """
        for i in range(item.childCount()):
            child = item.child(i)
            node = child.data(1, Qt.UserRole)
            if node:
                child.setText(7, self._get_entity_display_name(node.shipping_entity) if node.shipping_entity else '')
                child.setText(8, self._get_method_display_name(node.shipping_method) if node.shipping_method else '')
                child.setText(9, node.remark if node.remark else '')
                child.setText(6, node.expand_status)
                self._update_item_style(child, node)
                self._update_children_display(child)

    def _restore_expand_state(self):
        """恢复树的展开状态：展开所有expand_status='是'的节点（只展开下一级）"""
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            self._restore_item_expand(item)

    def _restore_item_expand(self, item):
        """
        递归恢复单个节点的展开状态

        Args:
            item: 树节点项
        """
        node = item.data(1, Qt.UserRole)
        if node and node.expand_status == '是':
            self._show_children(item)
            self.tree_widget.expandItem(item)
            # 递归处理子节点
            for i in range(item.childCount()):
                self._restore_item_expand(item.child(i))

    def expand_all_children(self, item):
        """
        展开所有子节点

        Args:
            item: 树节点项
        """
        def expand_recursive(item):
            item.setExpanded(True)
            for i in range(item.childCount()):
                expand_recursive(item.child(i))
        expand_recursive(item)

    def collapse_all_children(self, item):
        """
        折叠所有子节点

        Args:
            item: 树节点项
        """
        def collapse_recursive(item):
            for i in range(item.childCount()):
                collapse_recursive(item.child(i))
            item.setExpanded(False)
        collapse_recursive(item)

    def _update_item_remark(self, item, target_node, text):
        """
        递归查找并更新节点的备注显示

        Args:
            item: 树节点项
            target_node: 目标 BOM 节点
            text: 新的备注文本

        Returns:
            是否找到并更新
        """
        node = item.data(1, Qt.UserRole)
        if node and node is target_node:
            item.setText(9, text)
            return True
        for i in range(item.childCount()):
            if self._update_item_remark(item.child(i), target_node, text):
                return True
        return False

    def _uncheck_ancestors(self, item):
        """
        取消指定节点所有祖先的勾选状态

        规则：勾选子节点后，父节点自动取消勾选，避免批量操作时冲突

        Args:
            item: 树节点项
        """
        parent = item.parent()
        while parent:
            if parent.checkState(0) == Qt.Checked:
                parent.setCheckState(0, Qt.Unchecked)
            parent = parent.parent()
