# -*- coding: utf-8 -*-
"""
v2.5.3 批量设置同级同父校验回归测试

覆盖 2026-08-08 新增校验：批量设置（batch_config）仅允许修改同一层级
且同父物料的勾选节点，防止跨层级操作把父节点"是否展开"改为"否"导致
其下整棵子树被折叠隐藏（界面表现为"下面没了"）。

用法：python tests/test_v253_batch_sibling_guard.py
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
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")


# ============ Qt 环境与对话框拦截 ============
from PyQt5.QtWidgets import (QApplication, QMessageBox, QDialog)
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

dialog_log = []
exec_count = {'n': 0}


def _fake_information(parent, title, text, *args, **kwargs):
    dialog_log.append(('information', title, text))
    return QMessageBox.Ok


def _fake_warning(parent, title, text, *args, **kwargs):
    dialog_log.append(('warning', title, text))
    return QMessageBox.Ok


def _fake_question(parent, title, text, *args, **kwargs):
    dialog_log.append(('question', title, text))
    return QMessageBox.Yes


def _fake_critical(parent, title, text, *args, **kwargs):
    dialog_log.append(('critical', title, text))
    return QMessageBox.Ok


def _fake_exec(self):
    exec_count['n'] += 1
    return QDialog.Rejected


QMessageBox.information = _fake_information
QMessageBox.warning = _fake_warning
QMessageBox.question = _fake_question
QMessageBox.critical = _fake_critical

from ui.main_window import MainWindow
from models.bom_node import BOMNode


def make_window():
    """构造 MainWindow 并挂载合成 BOM 树

    ROOT (0, 是)
    ├── A (1, 是)
    │   └── A1 (2, 否)
    ├── B (1, 否)
    └── C (1, 是)
        └── C1 (2, 否)
    """
    w = MainWindow()
    root = BOMNode(material_id='ROOT', parent_id='', name='ROOT', level=0, expand_status='是')
    a = BOMNode(material_id='A', parent_id='ROOT', name='A', level=1, expand_status='是')
    a1 = BOMNode(material_id='A1', parent_id='A', name='A1', level=2, expand_status='否')
    b = BOMNode(material_id='B', parent_id='ROOT', name='B', level=1, expand_status='否')
    c = BOMNode(material_id='C', parent_id='ROOT', name='C', level=1, expand_status='是')
    c1 = BOMNode(material_id='C1', parent_id='C', name='C1', level=2, expand_status='否')
    root.children = [a, b, c]
    for child in (a, b, c):
        child.parent = root
    a.children = [a1]
    a1.parent = a
    c.children = [c1]
    c1.parent = c
    w.tree_builder.root = root
    w.tree_builder.all_nodes = [root, a, a1, b, c, c1]
    w.refresh_tree()
    return w, {'root': root, 'a': a, 'a1': a1, 'b': b, 'c': c, 'c1': c1}


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


def check_items(w, uids):
    """勾选指定 uid 的节点"""
    for uid in uids:
        find_item(w, uid).setCheckState(0, Qt.Checked)


# ============ 1. 校验函数单元测试 ============
print()
print("== 1. _validate_batch_nodes_same_sibling 分组校验 ==")
w, nodes = make_window()
root2 = BOMNode(material_id='ROOT2', parent_id='', name='ROOT2', level=0, expand_status='是')

ok, detail = w._validate_batch_nodes_same_sibling([nodes['a'], nodes['b']])
check('兄弟节点（同层同父）通过', ok is True, detail)

ok, detail = w._validate_batch_nodes_same_sibling([nodes['a']])
check('单节点通过', ok is True, detail)

ok, detail = w._validate_batch_nodes_same_sibling([nodes['root'], root2])
check('多个顶层节点通过（同层同父空）', ok is True, detail)

ok, detail = w._validate_batch_nodes_same_sibling([nodes['a'], nodes['a1']])
check('父子跨层级被拒绝', ok is False, detail)

ok, detail = w._validate_batch_nodes_same_sibling([nodes['a1'], nodes['c1']])
check('同层级不同父被拒绝', ok is False, detail)

ok, detail = w._validate_batch_nodes_same_sibling([nodes['root'], nodes['a']])
check('顶层+子级跨层级被拒绝', ok is False, detail)


# ============ 2. batch_config 失败路径：跨层级直接阻止 ============
print()
print("== 2. batch_config 跨层级勾选被阻止 ==")
w2, nodes2 = make_window()
check_items(w2, [nodes2['a'].uid, nodes2['a1'].uid])
check('前置：勾选 2 个跨层级节点', len(w2.get_checked_nodes()) == 2,
      f"{len(w2.get_checked_nodes())}")

dialog_log.clear()
exec_count['n'] = 0
_real_exec = QDialog.exec_
QDialog.exec_ = _fake_exec
try:
    w2.batch_config()
finally:
    QDialog.exec_ = _real_exec
check('弹出警告提示', any(title == '警告' for _, title, _ in dialog_log),
      f"{dialog_log}")
check('未打开设置对话框', exec_count['n'] == 0, f"exec={exec_count['n']}")
check('未修改任何节点配置',
      nodes2['a'].shipping_entity == '' and nodes2['a1'].shipping_entity == '',
      f"a={nodes2['a'].shipping_entity!r} a1={nodes2['a1'].shipping_entity!r}")


# ============ 3. batch_config 成功路径：兄弟节点可打开对话框 ============
print()
print("== 3. batch_config 兄弟节点正常打开设置对话框 ==")
w3, nodes3 = make_window()
check_items(w3, [nodes3['a'].uid, nodes3['b'].uid])
check('前置：勾选 2 个兄弟节点', len(w3.get_checked_nodes()) == 2,
      f"{len(w3.get_checked_nodes())}")

dialog_log.clear()
exec_count['n'] = 0
QDialog.exec_ = _fake_exec
try:
    w3.batch_config()
finally:
    QDialog.exec_ = _real_exec
check('未弹警告', not any(title == '警告' for _, title, _ in dialog_log),
      f"{dialog_log}")
check('已打开设置对话框', exec_count['n'] == 1, f"exec={exec_count['n']}")


print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
