# -*- coding: utf-8 -*-
"""
v2.4 粘贴格式与"是否展开"修复回归测试

覆盖 2026-08-05 两个生产缺陷：
- 缺陷一：复制"否+主体+方式"格式后粘贴到勾选的顶级/高层节点，
  导致整棵树塌缩隐藏、只剩最高级。
  修复：粘贴前逐节点过滤（顶级/隐藏/叶子/子孙已维护），跳过并分类提示。
- 缺陷二：已维护发运配置的节点，右键菜单/快捷键无法改回"是否展开=是"，
  拦截提示要求的"清空发运配置"入口不存在。
  修复：右键菜单新增"清空发运配置"，先清空再改"是"；拦截文案同步更新。
另覆盖配套修复：
- 批量操作（勾选收集/全选/反选）排除隐藏节点；
- refresh_tree 展开状态恢复改以稳定 uid 为键（同物料号多实例不串位）。

用法：python test_v24_paste_expand_fixes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

passed = 0
failed = 0


def check(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")


# ============ Qt 环境与对话框拦截 ============
from PyQt5.QtWidgets import QApplication, QMessageBox
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


def _fake_critical(parent, title, text, *args, **kwargs):
    dialog_log.append(('critical', title, text))
    return QMessageBox.Ok


QMessageBox.information = _fake_information
QMessageBox.warning = _fake_warning
QMessageBox.question = _fake_question
QMessageBox.critical = _fake_critical

from ui.main_window import MainWindow
from models.bom_node import BOMNode


def make_node(mid, level, expand='否', parent=None, entity='', method='', remark=''):
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
    )
    if parent:
        node.parent = parent
        parent.children.append(node)
    return node


def make_window():
    """构造 MainWindow 并挂载合成 BOM 树

    ROOT (0, 是)
    ├── A (1, 是)
    │   ├── A1 (2, 是)
    │   │   └── A1a (3, 否, 01/A)      已维护的发运单元
    │   │       └── A1a1 (4, 否)       "否"边界下的隐藏节点
    │   └── DUP (2, 是)                重复物料号实例1
    │       └── DUP1C (3, 否)
    └── B (1, 是)
        ├── B1 (2, 是)
        │   └── B1a (3, 否)            干净的叶子节点
        └── DUP (2, 否)                重复物料号实例2（发运单元边界）
            └── DUP2C (3, 否)
    """
    w = MainWindow()
    root = make_node('ROOT', 0, '是')
    a = make_node('A', 1, '是', root)
    a1 = make_node('A1', 2, '是', a)
    a1a = make_node('A1a', 3, '否', a1, entity='01', method='A')
    a1a1 = make_node('A1a1', 4, '否', a1a)
    dup1 = make_node('DUP', 2, '是', a)
    dup1c = make_node('DUP1C', 3, '否', dup1)
    b = make_node('B', 1, '是', root)
    b1 = make_node('B1', 2, '是', b)
    b1a = make_node('B1a', 3, '否', b1)
    dup2 = make_node('DUP', 2, '否', b)
    dup2c = make_node('DUP2C', 3, '否', dup2)
    nodes = {
        'root': root, 'a': a, 'a1': a1, 'a1a': a1a, 'a1a1': a1a1,
        'dup1': dup1, 'dup1c': dup1c,
        'b': b, 'b1': b1, 'b1a': b1a, 'dup2': dup2, 'dup2c': dup2c,
    }
    w.tree_builder.root = root
    w.tree_builder.all_nodes = list(nodes.values())
    w.refresh_tree()
    return w, nodes


def find_item(w, uid):
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


def set_checked(w, uids):
    """清空全部勾选后，勾选指定 uid 的节点"""
    def clear(item):
        item.setCheckState(0, Qt.Unchecked)
        for i in range(item.childCount()):
            clear(item.child(i))
    for i in range(w.tree_widget.topLevelItemCount()):
        clear(w.tree_widget.topLevelItem(i))
    for uid in uids:
        item = find_item(w, uid)
        if item:
            item.setCheckState(0, Qt.Checked)


def last_dialog(kind=None):
    for entry in reversed(dialog_log):
        if kind is None or entry[0] == kind:
            return entry
    return None


# ============ 1. 粘贴"否"格式的节点保护 ============
print("== 1. 粘贴'否'格式：跳过顶级/隐藏/子孙已维护节点 ==")
w, n = make_window()
w._copy_format(n['a1a'])  # 复制格式：否 + 01 + A
# 勾选：ROOT(顶级)、A1a1(隐藏)、A(子孙已维护)、B1(干净)、B1a(干净叶子)
set_checked(w, [n['root'].uid, n['a1a1'].uid, n['a'].uid, n['b1'].uid, n['b1a'].uid])
dialog_log.clear()
undo_before = len(w._undo_stack)
w._paste_format_to_checked()

check('顶级节点 ROOT 被跳过且未被修改',
      n['root'].expand_status == '是' and n['root'].shipping_entity == '')
check('隐藏节点 A1a1 未被修改',
      n['a1a1'].shipping_entity == '' and n['a1a1'].expand_status == '否')
check('子孙已维护的节点 A 被跳过',
      n['a'].expand_status == '是' and n['a'].shipping_entity == '')
check('子孙节点 A1a 的既有配置未被波及',
      n['a1a'].shipping_entity == '01' and n['a1a'].shipping_method == 'A')
check('干净节点 B1 被正确应用',
      n['b1'].expand_status == '否' and n['b1'].shipping_entity == '01'
      and n['b1'].shipping_method == 'A')
check('干净叶子 B1a 被正确应用（否格式允许叶子）',
      n['b1a'].expand_status == '否' and n['b1a'].shipping_entity == '01')
info = last_dialog('information')
check('结果提示包含应用数量与跳过数量',
      info is not None and '2 个节点' in info[2] and '跳过 2 个' in info[2],
      f'dialog={info}')
check('撤销快照仅压入一次', len(w._undo_stack) == undo_before + 1,
      f'before={undo_before}, after={len(w._undo_stack)}')

root_item = w.tree_widget.topLevelItem(0)
check('粘贴后树未塌缩：ROOT 子节点仍可见',
      root_item.childCount() >= 2 and not root_item.child(0).isHidden())
a1a1_item = find_item(w, n['a1a1'].uid)
check('A1a 的发运单元边界保持：A1a1 仍隐藏', a1a1_item.isHidden())


# ============ 2. 粘贴"是"格式：跳过叶子节点 ============
print()
print("== 2. 粘贴'是'格式：叶子节点被跳过、已有配置被清空 ==")
w2, n2 = make_window()
# 直接改数据不刷新树，保持 B1a 项可见（模拟粘贴前的真实界面状态）
n2['b1'].expand_status = '否'
n2['b1'].shipping_entity = '98'
n2['b1'].shipping_method = 'B'
w2._copy_format(n2['a'])  # 复制格式：是（无配置）
set_checked(w2, [n2['root'].uid, n2['b1'].uid, n2['dup1c'].uid])
dialog_log.clear()
w2._paste_format_to_checked()

check('B1 粘贴"是"成功且原配置被清空',
      n2['b1'].expand_status == '是' and n2['b1'].shipping_entity == ''
      and n2['b1'].shipping_method == '')
check('叶子节点 DUP1C 被跳过（保持原状）', n2['dup1c'].expand_status == '否')
check('顶级 ROOT 被跳过',
      n2['root'].expand_status == '是' and n2['root'].shipping_entity == '')
info = last_dialog('information')
check('提示中说明跳过 2 个节点（顶级+叶子）',
      info is not None and '跳过 2 个' in info[2], f'dialog={info}')


# ============ 3. 批量操作排除隐藏节点 ============
print()
print("== 3. 勾选收集/全选/反选排除隐藏节点 ==")
w3, n3 = make_window()
hidden_item = find_item(w3, n3['a1a1'].uid)
check('前置：A1a1 项处于隐藏状态', hidden_item.isHidden())
hidden_item.setCheckState(0, Qt.Checked)
find_item(w3, n3['b1'].uid).setCheckState(0, Qt.Checked)

checked = w3.get_checked_nodes()
check('get_checked_nodes 不返回隐藏节点', all(x.uid != n3['a1a1'].uid for x in checked))
check('get_checked_nodes 返回可见勾选节点', any(x.uid == n3['b1'].uid for x in checked))

# 还原隐藏节点的勾选状态，便于断言全选/反选不会触碰它
hidden_item.setCheckState(0, Qt.Unchecked)

w3.select_all_nodes()
check('全选后隐藏节点仍保持未勾选', hidden_item.checkState(0) == Qt.Unchecked)
check('全选后可见节点均被勾选',
      find_item(w3, n3['a'].uid).checkState(0) == Qt.Checked
      and find_item(w3, n3['b'].uid).checkState(0) == Qt.Checked)

w3.invert_select_nodes()
check('反选后隐藏节点仍保持未勾选', hidden_item.checkState(0) == Qt.Unchecked)
check('反选后可见节点被取消勾选',
      find_item(w3, n3['b1'].uid).checkState(0) == Qt.Unchecked)


# ============ 4. 清空发运配置入口与改回"是" ============
print()
print("== 4. 拦截保持 + 清空发运配置后可改回'是' ==")
w4, n4 = make_window()
x = n4['a1a']  # 否 + 01 + A，有子节点 A1a1
dialog_log.clear()
w4.set_node_expand(x, '是')
check('有配置的节点改"是"仍被拦截',
      x.expand_status == '否' and x.shipping_entity == '01')
warn = last_dialog('warning')
check('拦截提示指向"清空发运配置"入口',
      warn is not None and '清空发运配置' in warn[2], f'dialog={warn}')

undo_before = len(w4._undo_stack)
dialog_log.clear()
w4._clear_node_shipping_config(x)
check('确认后配置被清空',
      x.shipping_entity == '' and x.shipping_method == '' and x.remark == '')
check('清空配置不改变"是否展开"状态', x.expand_status == '否')
check('清空操作压入撤销快照', len(w4._undo_stack) == undo_before + 1)

w4.set_node_expand(x, '是')
check('清空配置后可改回"是"', x.expand_status == '是')
a1a1_item = find_item(w4, n4['a1a1'].uid)
check('改回"是"后子节点恢复可见',
      a1a1_item is not None and not a1a1_item.isHidden())

# 取消分支：点"否"时不得修改
b1n = n4['b1']
b1n.shipping_entity = '02'
b1n.shipping_method = 'A'
b1n.expand_status = '否'
question_answer['value'] = QMessageBox.No
w4._clear_node_shipping_config(b1n)
check('取消清空时配置保持不变', b1n.shipping_entity == '02')
question_answer['value'] = QMessageBox.Yes


# ============ 5. 展开状态按 uid 恢复（重复物料号不串位） ============
print()
print("== 5. refresh_tree 展开状态按 uid 恢复 ==")
w5, n5 = make_window()
check('前置：两个实例物料号相同但 uid 不同',
      n5['dup1'].material_id == n5['dup2'].material_id
      and n5['dup1'].uid != n5['dup2'].uid)
dup1_item = find_item(w5, n5['dup1'].uid)
dup2_item = find_item(w5, n5['dup2'].uid)
dup1_item.setExpanded(True)
dup2_item.setExpanded(False)
w5.refresh_tree(preserve_expand_state=True)
dup1_after = find_item(w5, n5['dup1'].uid)
dup2_after = find_item(w5, n5['dup2'].uid)
check('展开的实例1刷新后保持展开', dup1_after.isExpanded())
check('折叠的实例2未被串位展开', not dup2_after.isExpanded())


# ============ 6. 塌缩后的撤销/恢复 ============
print()
print("== 6. 塌缩后的撤销/恢复 ==")


def visible_names(win):
    """收集树中所有未隐藏节点的物料号"""
    out = []
    def walk(item):
        node = item.data(1, Qt.UserRole)
        if not item.isHidden():
            out.append(node.material_id)
        for i in range(item.childCount()):
            walk(item.child(i))
    for i in range(win.tree_widget.topLevelItemCount()):
        walk(win.tree_widget.topLevelItem(i))
    return out


# 6a. 塌缩 → 撤销还原 → redo 重现
w6, n6 = make_window()
find_item(w6, n6['a'].uid).setExpanded(True)
find_item(w6, n6['b'].uid).setExpanded(True)
w6._save_state()  # 模拟粘贴操作前压入的快照
# 直接改写数据模拟旧版粘贴造成的塌缩
n6['root'].expand_status = '否'
n6['root'].shipping_entity = '01'
n6['root'].shipping_method = 'A'
w6.refresh_tree(preserve_expand_state=True)
check('前置：塌缩复现（仅剩顶级可见）', visible_names(w6) == ['ROOT'])

w6.undo()
check('撤销后 ROOT 数据还原',
      n6['root'].expand_status == '是' and n6['root'].shipping_entity == '')
# 注意：A1a1/DUP2C 位于各自的"否"边界之下，塌缩前就是隐藏的，属正常业务隐藏
check('撤销后整棵子树重新可见（恢复到塌缩前的可见状态）',
      sorted(visible_names(w6)) == sorted(['ROOT', 'A', 'A1', 'A1a', 'DUP',
                                           'DUP1C', 'B', 'B1', 'B1a', 'DUP']),
      f'visible={visible_names(w6)}')
check('撤销后有状态栏反馈', '已撤销' in w6.statusBar().currentMessage())

w6.redo()
check('redo 后塌缩状态重现',
      n6['root'].expand_status == '否' and visible_names(w6) == ['ROOT'])
check('redo 后有状态栏反馈', '已恢复' in w6.statusBar().currentMessage())

# 6b. 深度：塌缩后又做了 8 步操作，仍能一路撤销回塌缩前
w7, n7 = make_window()
w7._save_state()
n7['root'].expand_status = '否'
n7['root'].shipping_entity = '01'
n7['root'].shipping_method = 'A'
w7.refresh_tree(preserve_expand_state=True)
for i in range(8):
    w7._save_state()
    n7['a1a'].remark = f'r{i}'
    w7.refresh_tree(preserve_expand_state=True)
for i in range(9):
    w7.undo()
check('深度足够：塌缩后 8 步操作仍可全部撤销回塌缩前',
      n7['root'].expand_status == '是' and n7['root'].shipping_entity == ''
      and n7['a1a'].remark == '')
check('撤销栈耗尽后按钮禁用', not w7.btn_undo.isEnabled())

# 6c. 恢复过程异常时：大声报错、栈不被污染、可重试
w8, n8 = make_window()
w8._save_state()
n8['b1'].shipping_entity = '98'
w8.refresh_tree(preserve_expand_state=True)
stack_before = len(w8._undo_stack)
redo_before = len(w8._redo_stack)
orig_restore = w8._restore_state


def boom(state):
    raise RuntimeError('模拟恢复失败')


w8._restore_state = boom
dialog_log.clear()
w8.undo()
check('恢复失败时弹出错误提示', any(k == 'critical' for k, _, _ in dialog_log))
check('失败后撤销栈未被消耗', len(w8._undo_stack) == stack_before)
check('失败后恢复栈未被污染', len(w8._redo_stack) == redo_before)
check('失败后数据保持原状', n8['b1'].shipping_entity == '98')
w8._restore_state = orig_restore
w8.undo()
check('排除故障后重试撤销成功', n8['b1'].shipping_entity == '')


print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
