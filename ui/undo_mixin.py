"""
撤销/恢复 Mixin

提供操作历史的撤销和恢复功能

状态快照格式：
- node_data: {uid: {所有字段}} — 用于恢复节点属性（以稳定 uid 为键）
- tree_structure: [{node_key, children_keys}] — 用于重建树结构（node_key 即 uid）
- root_key: 顶级节点的 uid

修复说明（v2.3）：
- 快照键由 (父物料号_物料号) 复合键改为节点稳定 uid，消除拆分物料、
  同物料多实例场景下的键冲突（旧实现会互相覆盖、丢失或错置节点）。
- _restore_state 会清理"快照中不存在的多余节点"，避免撤销添加/拆分后
  幽灵节点残留在 all_nodes 中污染计算、保存与统计。
"""

from PyQt5.QtWidgets import QMessageBox

from models.bom_node import BOMNode


class UndoMixin:
    """撤销/恢复 Mixin"""

    @staticmethod
    def _node_key(node):
        """生成节点的快照键（使用稳定唯一 uid）"""
        return node.uid

    def _save_state_snapshot(self):
        """生成当前状态快照（不压栈，仅返回）"""
        node_data = {}
        for node in self.tree_builder.all_nodes:
            key = self._node_key(node)
            node_data[key] = {
                'uid': node.uid,
                'material_id': node.material_id,
                'parent_id': node.parent_id,
                'project_id': node.project_id,
                'drawing_no': node.drawing_no,
                'specification': node.specification,
                'name': node.name,
                'quantity': node.quantity,
                'weight': node.weight,
                'level': node.level,
                'seq_no': node.seq_no,
                'expand_status': node.expand_status,
                'shipping_entity': node.shipping_entity,
                'shipping_method': node.shipping_method,
                'remark': node.remark,
            }

        tree_structure = []
        root_key = None
        for node in self.tree_builder.all_nodes:
            children_keys = [self._node_key(c) for c in node.children]
            tree_structure.append({
                'node_key': self._node_key(node),
                'children_keys': children_keys,
            })
            if node.level == 0 or not node.parent_id:
                root_key = self._node_key(node)

        return {
            'node_data': node_data,
            'tree_structure': tree_structure,
            'root_key': root_key,
        }

    def _save_state(self):
        """保存当前状态到撤销栈（完整快照：节点数据 + 树结构）"""
        self._undo_stack.append(self._save_state_snapshot())
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_redo_buttons()
        # 标记文档为未保存并更新标题：凡产生可撤销变更的操作都会调用 _save_state，
        # 统一在此置 dirty，确保关窗时 closeEvent 能正确提示"未保存"，
        # 避免右键设置/拆分/删除等操作后忘记保存而静默丢失改动
        self._dirty = True
        self._update_title()

    def _push_undo_snapshot(self, state):
        """
        将一个预先捕获的快照推入撤销栈

        用于"先捕获快照、确认操作成功后再提交"的场景（如对话框编辑：
        编辑前 _save_state_snapshot() 捕获，用户确认后才推入），
        避免取消或失败的操作产生无意义的撤销点。
        """
        self._undo_stack.append(state)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _restore_state(self, state):
        """
        从状态快照恢复（节点属性 + 树结构）

        Args:
            state: 状态快照字典
        """
        node_data = state['node_data']
        tree_structure = state['tree_structure']

        # 0. 清理快照中不存在的多余节点（修复幽灵节点：撤销"添加/拆分"后
        #    被添加的节点若残留在 all_nodes，会继续参与计算/保存/统计）
        snapshot_keys = set(node_data.keys())
        self.tree_builder.all_nodes = [
            n for n in self.tree_builder.all_nodes if self._node_key(n) in snapshot_keys
        ]

        # 1. 重建节点查找表
        node_map = {}
        for n in self.tree_builder.all_nodes:
            key = self._node_key(n)
            node_map[key] = n

        # 2. 恢复被删除的节点（状态中有但当前没有的），保留原 uid
        for key, data in node_data.items():
            if key not in node_map:
                new_node = BOMNode(
                    material_id=data['material_id'],
                    parent_id=data['parent_id'],
                    project_id=data.get('project_id', ''),
                    drawing_no=data.get('drawing_no', ''),
                    specification=data.get('specification', ''),
                    name=data.get('name', ''),
                    quantity=data.get('quantity', 0),
                    weight=data.get('weight', 0),
                    level=data.get('level', 0),
                    seq_no=data.get('seq_no', 0),
                    expand_status=data.get('expand_status', '是'),
                    shipping_entity=data.get('shipping_entity', ''),
                    shipping_method=data.get('shipping_method', ''),
                    remark=data.get('remark', ''),
                    uid=data.get('uid', 0),
                )
                self.tree_builder.all_nodes.append(new_node)
                node_map[key] = new_node

        # 3. 恢复所有节点属性（不仅是配置字段）
        for node in self.tree_builder.all_nodes:
            key = self._node_key(node)
            if key in node_data:
                s = node_data[key]
                node.material_id = s.get('material_id', node.material_id)
                node.parent_id = s.get('parent_id', node.parent_id)
                node.project_id = s.get('project_id', '')
                node.drawing_no = s.get('drawing_no', '')
                node.specification = s.get('specification', '')
                node.name = s.get('name', '')
                node.quantity = s.get('quantity', 0)
                node.weight = s.get('weight', 0)
                node.level = s.get('level', 0)
                node.seq_no = s.get('seq_no', 0)
                node.expand_status = s.get('expand_status', '是')
                node.shipping_entity = s.get('shipping_entity', '')
                node.shipping_method = s.get('shipping_method', '')
                node.remark = s.get('remark', '')

        # 4. 清空所有父子关系
        for node in self.tree_builder.all_nodes:
            node.children = []
            node.parent = None

        # 5. 重建树结构（用 add_child 确保 parent 引用正确）
        for item in tree_structure:
            node_key = item['node_key']
            children_keys = item.get('children_keys', [])
            if node_key in node_map:
                parent_node = node_map[node_key]
                for child_key in children_keys:
                    if child_key in node_map:
                        child_node = node_map[child_key]
                        parent_node.add_child(child_node)

        # 6. 设置根节点
        root_key = state.get('root_key')
        if root_key and root_key in node_map:
            self.tree_builder.root = node_map[root_key]
        else:
            # fallback: 找 level=0 的节点
            self.tree_builder.root = None
            for node in self.tree_builder.all_nodes:
                if node.level == 0 or not node.parent_id:
                    self.tree_builder.root = node
                    break

        # 7. 恢复后自顶向下统一重算最终数量：
        # 快照不保存 final_quantity，add_child 仅重算被挂载的节点自身；
        # 若顶级节点数量曾被修改或输入行序非拓扑，root/中间层会残留旧值，
        # 导致子孙数量全部算错。与 TreeBuilder.build 的 _recompute_subtree
        # 保持同一逻辑，保证撤销/恢复后数量与快照一致。
        if self.tree_builder.root:
            self.tree_builder._recompute_subtree(self.tree_builder.root)

        # 8. 刷新 UI
        self.refresh_tree(preserve_expand_state=True)
        self.update_status_bar()

    def undo(self):
        """撤销上一步操作

        先尝试恢复、成功后才移动快照：若恢复中途异常，旧实现会先把快照
        移入恢复栈再失败，导致栈与实际数据脱节、后续撤销/恢复全部失灵。
        现在失败时保持栈不变并弹窗报错（失败要大声），用户可重试。
        """
        if not self._undo_stack:
            return
        prev_state = self._undo_stack[-1]
        current_state = self._save_state_snapshot()
        try:
            self._restore_state(prev_state)
        except Exception as e:
            QMessageBox.critical(self, '撤销失败',
                '撤销时发生错误，本次撤销未生效，数据保持原状。\n'
                '建议立即保存当前进度，若问题持续出现请重新加载最近保存的进度。\n\n'
                f'错误信息：{e}')
            return
        self._undo_stack.pop()
        self._redo_stack.append(current_state)
        self._update_undo_redo_buttons()
        self.statusBar().showMessage(f'已撤销（还可撤销 {len(self._undo_stack)} 步）')

    def redo(self):
        """恢复上一步撤销（失败处理同 undo）"""
        if not self._redo_stack:
            return
        next_state = self._redo_stack[-1]
        current_state = self._save_state_snapshot()
        try:
            self._restore_state(next_state)
        except Exception as e:
            QMessageBox.critical(self, '恢复失败',
                '恢复时发生错误，本次恢复未生效，数据保持原状。\n'
                '建议立即保存当前进度，若问题持续出现请重新加载最近保存的进度。\n\n'
                f'错误信息：{e}')
            return
        self._redo_stack.pop()
        self._undo_stack.append(current_state)
        self._update_undo_redo_buttons()
        self.statusBar().showMessage(f'已恢复（还可恢复 {len(self._redo_stack)} 步）')

    def _clear_undo_redo(self):
        """
        清空撤销/恢复栈

        在切换数据集（导入新 BOM、加载进度文件）后调用，
        避免旧数据集的快照被撤销操作复活进当前数据，造成跨数据集污染。
        """
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self):
        """更新撤销/恢复按钮状态"""
        self.btn_undo.setEnabled(len(self._undo_stack) > 0)
        self.btn_redo.setEnabled(len(self._redo_stack) > 0)
