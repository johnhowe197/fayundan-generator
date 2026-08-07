# -*- coding: utf-8 -*-
"""
v2.5 拆分挂载与顶级删除修复回归测试

覆盖 2026-08-05 全面审查发现的两个数据正确性缺陷：

缺陷一（拆分物料数量算错 + 父引用缺失）：
- split_material 拆分"非顶级"叶子节点时，第二部分节点在挂载前按顶级节点
  计算最终数量（parent=None → final_quantity=自身数量），漏乘父节点倍数；
- node2.parent 从未设置，导致隐藏判断（祖先"否"边界）失效、后续引用异常；
- node2 未复制备注。

缺陷二（删除顶级节点后仍显示并参与计算）：
- delete_material / delete_checked_nodes 删除顶级节点后，tree_builder.root
  仍指向已删除节点，refresh_tree 继续显示整个子树，计算仍包含被删数据。

另覆盖配套修复：拆分顶级叶子节点改为明确禁止（原实现静默丢失第二部分）。

用法：python tests/test_v232_fixes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'  [PASS] {name}')
    else:
        failed += 1
        print(f'  [FAIL] {name}  {detail}')


from PyQt5.QtWidgets import QApplication, QMessageBox, QComboBox, QDoubleSpinBox, QDialog
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

dialog_log = []
question_answer = {'value': QMessageBox.Yes}


def _fake_information(parent, title, text, *args, **kwargs):
    dialog_log.append(('information', title, text))
    return QMessageBox.Ok


def _fake_warning(parent, title, text, *args, **kwargs):
    dialog_log.append(('warning', title, text))
    return QMessageBox.Ok


def _fake_question(parent, title, text, *args, **kwargs):
    dialog_log.append(('question', title, text))
    return question_answer['value']


QMessageBox.information = _fake_information
QMessageBox.warning = _fake_warning
QMessageBox.question = _fake_question

from ui.main_window import MainWindow
from models.bom_node import BOMNode


def make_node(mid, level, expand='否', parent=None, entity='', method='', remark='', quantity=0):
    """构造测试用 BOM 节点"""
    node = BOMNode(
        material_id=mid,
        parent_id=parent.material_id if parent else '',
        name=mid,
        level=level,
        expand_status=expand,
        shipping_entity=entity,
        shipping_method=method,
        remark=remark,
        quantity=quantity,
    )
    if parent:
        parent.add_child(node)
    return node


def make_window():
    """构造 MainWindow 并挂载合成 BOM 树

    ROOT (0, 是, 数量1)
    └── A (1, 是, 数量2)
        └── A1 (2, 否, 数量3, 01/A, 备注"测试备注")
    """
    w = MainWindow()
    root = make_node('ROOT', 0, '是')
    a = make_node('A', 1, '是', root, quantity=2)
    a1 = make_node('A1', 2, '否', a, entity='01', method='A', remark='测试备注')
    # 手动补数量（make_node 默认 quantity=0，add_child 已按 0 计算，此处自顶向下重算）
    root.quantity = 1
    root.calculate_final_quantity()
    a.quantity = 2
    a.calculate_final_quantity()
    a1.quantity = 3
    a1.calculate_final_quantity()
    w.tree_builder.root = root
    w.tree_builder.all_nodes = [root, a, a1]
    w.refresh_tree()
    return w, {'root': root, 'a': a, 'a1': a1}


def find_item_by_uid(w, uid):
    """按节点 uid 查找树控件项"""
    def walk(item):
        node = item.data(1, Qt.UserRole)
        if node and node.uid == uid:
            return item
        for i in range(item.childCount()):
            r = walk(item.child(i))
            if r:
                return r
        return None
    for i in range(w.tree_widget.topLevelItemCount()):
        r = walk(w.tree_widget.topLevelItem(i))
        if r:
            return r
    return None


# ============ 1. 拆分挂载修复 ============
print('== 1. 拆分非顶级叶子节点：第二部分数量/父引用/备注 ==')
w, nodes = make_window()
a1_item = find_item_by_uid(w, nodes['a1'].uid)
check('找到 A1 树项', a1_item is not None)


def _fake_split_exec(self):
    """模拟拆分对话框确认：第一部分保留 01/A，第二部分 02/B"""
    for c in self.findChildren(QComboBox):
        items = [c.itemText(i) for i in range(c.count())]
        if 'A-散装' in items and 'B-打捆' in items:
            # 发运方式下拉框
            if not c.currentText():
                c.setCurrentText('B-打捆')
        elif any(t.startswith('01-') for t in items) or any(t.startswith('02-') for t in items):
            # 发运主体下拉框
            if not c.currentText():
                c.setCurrentText('02-左过渡槽')
    for s in self.findChildren(QDoubleSpinBox):
        s.setValue(split_q1['value'])
    return QDialog.Accepted


split_q1 = {'value': 1}
_real_exec = QDialog.exec_
QDialog.exec_ = _fake_split_exec
dialog_log.clear()
try:
    w.split_material(nodes['a1'], a1_item)
finally:
    QDialog.exec_ = _real_exec

check('拆分后 A1.quantity=1', nodes['a1'].quantity == 1, f"实际 {nodes['a1'].quantity}")
check('拆分后 A1.final_quantity=2（1×2×1）', nodes['a1'].final_quantity == 2, f"实际 {nodes['a1'].final_quantity}")

node2 = None
for n in w.tree_builder.all_nodes:
    if n.name == 'A1-2':
        node2 = n
        break
check('第二部分节点已加入 all_nodes', node2 is not None)
if node2:
    check('node2.quantity=2', node2.quantity == 2, f"实际 {node2.quantity}")
    check('node2.final_quantity=4（2×2×1）', node2.final_quantity == 4, f"实际 {node2.final_quantity}")
    check('node2.parent 已设置（指向 A）', node2.parent is nodes['a'], f"实际 parent={node2.parent}")
    check('node2.parent_id=A', node2.parent_id == 'A')
    check('node2 已挂入 A.children', node2 in nodes['a'].children)
    check('node2.remark 已复制', node2.remark == '测试备注', f"实际 {node2.remark!r}")
    check('node2 未被隐藏（A 展开=是）', not w._is_node_hidden(node2))
    check('node2 可在树中显示', find_item_by_uid(w, node2.uid) is not None)
    # 计算正确性：发运单元集合包含 A1 与 A1-2，数量合计 6（1×2 + 2×2）
    units = w.tree_builder.get_all_shipping_units()
    qty_sum = sum(u.final_quantity for u in units)
    check('发运单元数量合计=6', qty_sum == 6, f"实际 {qty_sum}")

# ============ 2. 拆分顶级节点被禁止 ============
print('== 2. 拆分顶级叶子节点：明确禁止 ==')
w2, nodes2 = make_window()
# 把 ROOT 的子树移除，构造"顶级叶子"
root2 = nodes2['root']
root2.children.clear()
# 清理 A/A1 引用，让 root 成为叶子（数量 5，可拆成 2+3 通过数量检查）
root2.quantity = 5
root2.calculate_final_quantity()
w2.tree_builder.all_nodes = [root2]
w2.refresh_tree()
root_item = find_item_by_uid(w2, root2.uid)
check('顶级叶子可定位', root_item is not None)

dialog_log.clear()
split_q1['value'] = 2
_real_exec2 = QDialog.exec_
QDialog.exec_ = _fake_split_exec
try:
    w2.split_material(root2, root_item)
finally:
    QDialog.exec_ = _real_exec2
check('弹出了顶级不能拆分警告', any('顶级节点不能拆分' in txt for _, _, txt in dialog_log),
      f"日志 {[x[2][:20] for x in dialog_log]}")
check('数据未被修改（仍只有 root）', len(w2.tree_builder.all_nodes) == 1)
check('root.quantity 未变', root2.quantity == 5)

# ============ 3. 删除顶级节点（单个） ============
print('== 3. 删除顶级节点：root 清空、树清空 ==')
w3, nodes3 = make_window()
dialog_log.clear()
question_answer['value'] = QMessageBox.Yes
w3.delete_material(nodes3['root'])
check('tree_builder.root 已清空', w3.tree_builder.root is None)
check('all_nodes 已清空', len(w3.tree_builder.all_nodes) == 0, f"实际 {len(w3.tree_builder.all_nodes)}")
check('树控件无顶级项', w3.tree_widget.topLevelItemCount() == 0)
check('发运单元集合为空', w3.tree_builder.get_all_shipping_units() == [])

# ============ 4. 批量删除顶级节点 ============
print('== 4. 批量删除顶级节点：root 清空 ==')
w4, nodes4 = make_window()
# 勾选 root（含子孙）
root_item4 = find_item_by_uid(w4, nodes4['root'].uid)
root_item4.setCheckState(0, Qt.Checked)
dialog_log.clear()
w4.delete_checked_nodes()
check('批量删除后 tree_builder.root 已清空', w4.tree_builder.root is None)
check('批量删除后 all_nodes 已清空', len(w4.tree_builder.all_nodes) == 0)
check('批量删除后树控件无顶级项', w4.tree_widget.topLevelItemCount() == 0)

# ============ 5. set_node_expand 设"否"：确认后清除子孙配置 ============
print('== 5. set_node_expand 设"否"：与列点击路径一致，确认后清子孙配置 ==')
w5, nodes5 = make_window()
# A 的子孙 A1 已维护 01/A 配置
check('前置：A1 有配置', nodes5['a1'].shipping_entity == '01')
dialog_log.clear()
question_answer['value'] = QMessageBox.Yes
w5.set_node_expand(nodes5['a'], '否')
check('A.expand_status=否', nodes5['a'].expand_status == '否')
check('确认对话框已弹出', any(t == '确认设置' for _, t, _ in dialog_log))
check('A1 发运主体被清除', nodes5['a1'].shipping_entity == '', f"实际 {nodes5['a1'].shipping_entity!r}")
check('A1 发运方式被清除', nodes5['a1'].shipping_method == '')
check('A1 展开状态=否（不复活为发运单元）', nodes5['a1'].expand_status == '否')

# ============ 6. set_node_expand 设"否"：取消确认则不改动 ============
print('== 6. set_node_expand 设"否"：用户取消则不改动 ==')
w6, nodes6 = make_window()
dialog_log.clear()
question_answer['value'] = QMessageBox.No
w6.set_node_expand(nodes6['a'], '否')
check('A.expand_status 保持"是"', nodes6['a'].expand_status == '是')
check('A1 配置保留', nodes6['a1'].shipping_entity == '01')

# ============ 7. set_node_expand 设"是"：含备注节点被拦截 ============
print('== 7. set_node_expand 设"是"：拦截含备注的节点 ==')
w7, nodes7 = make_window()
remark_node = make_node('R', 1, '否', nodes7['root'], remark='仅备注')
remark_leaf = make_node('R1', 2, '否', remark_node)
nodes7['root'].children.append(remark_node)
w7.tree_builder.all_nodes.append(remark_node)
w7.tree_builder.all_nodes.append(remark_leaf)
w7.refresh_tree()
dialog_log.clear()
question_answer['value'] = QMessageBox.Yes
w7.set_node_expand(remark_node, '是')
check('弹出拦截提示', any('已配置发运主体/方式/备注' in txt for _, _, txt in dialog_log))
check('expand_status 未被修改', remark_node.expand_status == '否')
check('备注未被清空', remark_node.remark == '仅备注')

# ============ 8. batch_config 批量设"展开=是"：清空配置、备注不写入 ============
print('== 8. 批量设置"展开=是"：清空配置、备注不写入 ==')
w8, nodes8 = make_window()
a1_item8 = find_item_by_uid(w8, nodes8['a1'].uid)
a1_item8.setCheckState(0, Qt.Checked)
check('前置：A1 已勾选', len(w8.get_checked_nodes()) == 1)


def _fake_batch_exec(self):
    from PyQt5.QtWidgets import QLineEdit
    for c in self.findChildren(QComboBox):
        items = [c.itemText(i) for i in range(c.count())]
        if '否' in items and '是' in items:
            c.setCurrentText('是')  # 展开=是
    for e in self.findChildren(QLineEdit):
        e.setText('不应写入的备注')
    return QDialog.Accepted


dialog_log.clear()
_real_batch_exec = QDialog.exec_
QDialog.exec_ = _fake_batch_exec
try:
    w8.batch_config()
finally:
    QDialog.exec_ = _real_batch_exec
check('A1.expand_status=是', nodes8['a1'].expand_status == '是')
check('A1 发运主体被清空', nodes8['a1'].shipping_entity == '')
check('A1 发运方式被清空', nodes8['a1'].shipping_method == '')
check('A1 备注未被写入', nodes8['a1'].remark == '', f"实际 {nodes8['a1'].remark!r}")

# ============ 9. _restore_state 恢复后统一重算数量 ============
print('== 9. 撤销恢复后自顶向下重算最终数量 ==')
w9, nodes9 = make_window()
# 修改前的快照（root.quantity=1）
snapshot = w9._save_state_snapshot()
# 模拟用户修改顶级节点数量：1 → 3（此场景旧实现恢复后数量残留放大）
nodes9['root'].quantity = 3
nodes9['root'].calculate_final_quantity()
nodes9['a'].calculate_final_quantity()
nodes9['a1'].calculate_final_quantity()
check('前置：放大后 A1.final=18', nodes9['a1'].final_quantity == 18, f"实际 {nodes9['a1'].final_quantity}")
dialog_log.clear()
w9._restore_state(snapshot)
check('恢复后 root.final=1', nodes9['root'].final_quantity == 1, f"实际 {nodes9['root'].final_quantity}")
check('恢复后 A.final=2', nodes9['a'].final_quantity == 2, f"实际 {nodes9['a'].final_quantity}")
check('恢复后 A1.final=6', nodes9['a1'].final_quantity == 6, f"实际 {nodes9['a1'].final_quantity}")
# 再次验证：非拓扑行序下子孙数量也正确（先挂孙再挂父，修复依赖最终整树重算）
w10, nodes10 = make_window()
snapshot10 = w10._save_state_snapshot()
nodes10['root'].quantity = 3
nodes10['root'].calculate_final_quantity()
nodes10['a'].calculate_final_quantity()
nodes10['a1'].calculate_final_quantity()
# 构造非拓扑 tree_structure：A1 排在 A 前
snap10 = dict(snapshot10)
snap10['tree_structure'] = [
    item for item in snapshot10['tree_structure'] if item['node_key'] == nodes10['a1'].uid
] + [
    item for item in snapshot10['tree_structure'] if item['node_key'] != nodes10['a1'].uid
]
w10._restore_state(snap10)
check('非拓扑序恢复后 A1.final=6', nodes10['a1'].final_quantity == 6, f"实际 {nodes10['a1'].final_quantity}")

print()
print(f'总计: {passed} 项, 通过 {passed}, 失败 {failed}')
sys.exit(0 if failed == 0 else 1)
