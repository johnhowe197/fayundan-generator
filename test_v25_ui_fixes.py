# -*- coding: utf-8 -*-
"""
v2.5 界面交互修复回归测试

覆盖 2026-08-07 六个界面交互问题：
- 问题1：Delete 快捷键收紧为树控件 WidgetShortcut（不再劫持文本输入）
- 问题2：勾选操作可撤销、标脏，撤销快照携带勾选集合 checked_uids
- 问题3：refresh_tree 信号重连 try/finally 保护（异常自愈）
- 问题5：预设下拉刷新 blockSignals 保护（不覆盖表格未保存编辑）
- 问题6：BatchConfigDialog 死代码已删除
（问题4 _busy 忙碌状态以行为验证为主，手工冒烟覆盖）

用法：python test_v25_ui_fixes.py
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
from PyQt5.QtWidgets import QApplication, QMessageBox, QInputDialog
from PyQt5.QtCore import Qt, QEvent, QPoint
from PyQt5.QtGui import QMouseEvent

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
QInputDialog.getText = lambda *a, **k: ('新预设', True)

from ui.main_window import MainWindow
from models.bom_node import BOMNode
import ui.config_dialog as config_dialog_module


def make_window():
    """构造 MainWindow 并挂载合成 BOM 树

    ROOT (0, 是)
    ├── A (1, 是)
    │   └── A1 (2, 否)     用于勾选撤销/祖先联动测试
    └── B (1, 否)
    """
    w = MainWindow()
    root = BOMNode(material_id='ROOT', parent_id='', name='ROOT', level=0, expand_status='是')
    a = BOMNode(material_id='A', parent_id='ROOT', name='A', level=1, expand_status='是')
    a1 = BOMNode(material_id='A1', parent_id='A', name='A1', level=2, expand_status='否')
    b = BOMNode(material_id='B', parent_id='ROOT', name='B', level=1, expand_status='否')
    root.children.append(a)
    a.parent = root
    a.children.append(a1)
    a1.parent = a
    root.children.append(b)
    b.parent = root
    nodes = {'root': root, 'a': a, 'a1': a1, 'b': b}
    w.tree_builder.root = root
    w.tree_builder.all_nodes = [root, a, a1, b]
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


def state_of(w, uid):
    """返回指定 uid 节点当前的勾选状态（树重建后按 uid 重新查找）"""
    item = find_item(w, uid)
    return item.checkState(0) if item else None


def click_checkbox(w, uid, mod=Qt.NoModifier):
    """展开祖先确保可见后，合成与源码同款定位的复选框点击并调用 eventFilter"""
    item = find_item(w, uid)
    p = item.parent()
    while p:
        p.setExpanded(True)
        p = p.parent()
    from PyQt5.QtWidgets import QStyleOptionViewItem, QStyle
    item_rect = w.tree_widget.visualItemRect(item)
    opt = QStyleOptionViewItem()
    opt.rect = item_rect
    opt.state = QStyle.State_Enabled | QStyle.State_Item
    opt.checkState = item.checkState(0)
    opt.features = QStyleOptionViewItem.HasCheckIndicator
    indicator = w.tree_widget.style().subElementRect(
        QStyle.SE_ItemViewItemCheckIndicator, opt, w.tree_widget)
    cx = indicator.center().x() if indicator.isValid() and indicator.width() > 0 else item_rect.left() + 14
    cy = indicator.center().y() if indicator.isValid() and indicator.width() > 0 else item_rect.center().y()
    pos = QPoint(int(cx), int(cy))
    ev = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, mod)
    return w.eventFilter(w.tree_widget.viewport(), ev)


# ============ 1. Delete 快捷键上下文 ============
print("== 1. Delete 快捷键限定为树控件 WidgetShortcut ==")
w1, n1 = make_window()
check('存在 _delete_shortcut 引用', hasattr(w1, '_delete_shortcut'))
check('上下文为 Qt.WidgetShortcut',
      w1._delete_shortcut.context() == Qt.WidgetShortcut,
      f"context={w1._delete_shortcut.context()}")
check('parent 为 tree_widget', w1._delete_shortcut.parent() == w1.tree_widget)


# ============ 2. 勾选撤销（核心组） ============
print()
print("== 2. 勾选操作可撤销、标脏，快照携带 checked_uids ==")
# 2a. 快照 checked_uids 与手工 setCheckState 一致
w2, n2 = make_window()
find_item(w2, n2['a1'].uid).setCheckState(0, Qt.Checked)
snap = w2._save_state_snapshot()
check('快照 checked_uids 与手工勾选一致', snap['checked_uids'] == {n2['a1'].uid},
      f"{snap['checked_uids']}")
find_item(w2, n2['a1'].uid).setCheckState(0, Qt.Unchecked)

# 2b. 普通点击：栈+1、标脏、勾选生效
w2._dirty = False
stack_before = len(w2._undo_stack)
click_ok = click_checkbox(w2, n2['a1'].uid)
check('eventFilter 拦截复选框点击', click_ok is True)
check('勾选点击压入撤销栈', len(w2._undo_stack) == stack_before + 1,
      f"before={stack_before}, after={len(w2._undo_stack)}")
check('勾选点击标记未保存', w2._dirty is True)
check('点击后 A1 被勾选', state_of(w2, n2['a1'].uid) == Qt.Checked)

# 2c. undo 还原勾选（A1 勾选时祖先 A/ROOT 未被勾选，撤销后全部未勾选）
w2.undo()
check('undo 后 A1 还原为未勾选', state_of(w2, n2['a1'].uid) == Qt.Unchecked)
check('undo 后无任何勾选', w2._collect_checked_uids() == set(),
      f"{w2._collect_checked_uids()}")

# 2d. 先勾选祖先再勾选子节点 → undo 还原祖先勾选（祖先联动）
click_checkbox(w2, n2['a'].uid)
check('前置：A 被勾选', state_of(w2, n2['a'].uid) == Qt.Checked)
click_checkbox(w2, n2['a1'].uid)
check('勾选 A1 后祖先 A 自动取消', state_of(w2, n2['a'].uid) == Qt.Unchecked
      and state_of(w2, n2['a1'].uid) == Qt.Checked)
w2.undo()
check('undo 还原祖先联动（A 勾选、A1 未勾选）',
      state_of(w2, n2['a'].uid) == Qt.Checked and state_of(w2, n2['a1'].uid) == Qt.Unchecked,
      f"A={state_of(w2, n2['a'].uid)}, A1={state_of(w2, n2['a1'].uid)}")

# 2e. redo 重现
w2.redo()
check('redo 重现（A 未勾选、A1 勾选）',
      state_of(w2, n2['a'].uid) == Qt.Unchecked and state_of(w2, n2['a1'].uid) == Qt.Checked)

# 2f. Ctrl 路径
w3, n3 = make_window()
stack_before = len(w3._undo_stack)
check('Ctrl 点击被拦截', click_checkbox(w3, n3['a1'].uid, Qt.ControlModifier) is True)
check('Ctrl 路径压栈+1', len(w3._undo_stack) == stack_before + 1)
check('Ctrl 路径 A1 勾选', state_of(w3, n3['a1'].uid) == Qt.Checked)
w3.undo()
check('Ctrl 路径 undo 还原', state_of(w3, n3['a1'].uid) == Qt.Unchecked)

# 2g. Shift 区间路径（区间 [A1..B] 为无父子冲突的兄弟项，
#      勾选子项会按规则自动取消祖先勾选，故 A 保持未勾选）
w4, n4 = make_window()
w4.last_clicked_item = find_item(w4, n4['a1'].uid)
stack_before = len(w4._undo_stack)
check('Shift 点击被拦截', click_checkbox(w4, n4['b'].uid, Qt.ShiftModifier) is True)
check('Shift 区间 A1 与 B 均勾选',
      state_of(w4, n4['a1'].uid) == Qt.Checked and state_of(w4, n4['b'].uid) == Qt.Checked)
check('Shift 区间祖先 A 按规则自动取消勾选', state_of(w4, n4['a'].uid) == Qt.Unchecked)
check('Shift 路径压栈+1', len(w4._undo_stack) == stack_before + 1)
w4.undo()
check('Shift 路径 undo 全部还原',
      state_of(w4, n4['a1'].uid) == Qt.Unchecked and state_of(w4, n4['b'].uid) == Qt.Unchecked)

# 2h. F2/F3：无目标不产生空快照；有目标压栈可撤销
w5, n5 = make_window()
stack_before = len(w5._undo_stack)
w5.tree_widget.clearSelection()
w5.tree_widget.setCurrentItem(None)
w5.check_selected_items()
w5.uncheck_selected_items()
check('F2/F3 无目标项不产生空快照', len(w5._undo_stack) == stack_before,
      f"before={stack_before}, after={len(w5._undo_stack)}")
sel_item = find_item(w5, n5['a1'].uid)
sel_item.setSelected(True)
w5.tree_widget.setCurrentItem(sel_item)
w5.check_selected_items()
check('F2 有目标项压栈+1', len(w5._undo_stack) == stack_before + 1)
check('F2 后 A1 被勾选', state_of(w5, n5['a1'].uid) == Qt.Checked)
w5.undo()
check('F2 可撤销', state_of(w5, n5['a1'].uid) == Qt.Unchecked)
w5.tree_widget.setCurrentItem(find_item(w5, n5['a1'].uid))
w5.uncheck_selected_items()
check('F3 有目标项压栈+1', len(w5._undo_stack) == stack_before + 1)

# 2i. 旧格式快照（无 checked_uids）恢复兼容
w6, n6 = make_window()
find_item(w6, n6['a1'].uid).setCheckState(0, Qt.Checked)
old_state = w6._save_state_snapshot()
old_state.pop('checked_uids', None)
w6._restore_state(old_state)
check('旧格式快照恢复不报错且全部未勾选', w6._collect_checked_uids() == set(),
      f"{w6._collect_checked_uids()}")


# ============ 3. refresh_tree 信号重连自愈 ============
print()
print("== 3. refresh_tree 异常时信号仍重连（自愈） ==")
w7, n7 = make_window()
orig_add = w7._add_tree_item


def boom(parent, node):
    raise RuntimeError('模拟建树异常')


w7._add_tree_item = boom
try:
    w7.refresh_tree()
except RuntimeError:
    pass
check('建树异常后 itemChanged 仍连接',
      w7.tree_widget.receivers(w7.tree_widget.itemChanged) > 0)
w7._add_tree_item = orig_add
w7.refresh_tree()
check('恢复后再次刷新正常且未重复连接',
      w7.tree_widget.receivers(w7.tree_widget.itemChanged) == 1)


# ============ 4. 预设下拉 blockSignals 保护 ============
print()
print("== 4. 新建/删除预设不覆盖表格未保存编辑 ==")
import ui.entity_mixin as entity_mixin_module


class FakeEntityConfigManager:
    """EntityConfigManager 桩：模拟新建/删除预设，且新预设立即存在"""
    LOCKED_CODES = {'00'}

    def __init__(self):
        self._names = ['默认', '预设B']
        self._presets = {
            '默认': {'entities': {'00': '全部', '01': '甲'}},
            '预设B': {'entities': {'00': '全部', '02': '乙'}},
            '新预设': {'entities': {'00': '全部', '09': '覆盖我'}},
        }
        self.last_error = None

    def get_preset_names(self):
        return self._names

    def get_preset(self, name):
        return self._presets.get(name)

    def create_preset(self, name):
        return True

    def delete_preset(self, name):
        return True

    def get_current_preset_name(self):
        return '默认'

    def set_current_preset(self, name):
        pass

    @staticmethod
    def _ensure_locked_codes(d):
        return dict(d)


orig_mgr = entity_mixin_module.EntityConfigManager
entity_mixin_module.EntityConfigManager = FakeEntityConfigManager

from PyQt5.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem

w8 = MainWindow()
combo = QComboBox()
table = QTableWidget()
table.setColumnCount(3)
table.setRowCount(2)
table.setItem(0, 0, QTableWidgetItem('03'))
table.setItem(0, 1, QTableWidgetItem('丙'))
table.setItem(1, 0, QTableWidgetItem('04'))
table.setItem(1, 1, QTableWidgetItem('丁'))
# 与真实对话框同款连接：currentTextChanged 会加载预设到表格
combo.currentTextChanged.connect(lambda name: w8._load_preset_to_table(name, table) if name else None)


def snapshot_rows(t):
    """返回表格内容快照（行数 + 首行两格文本），空表时首行为 '-'"""
    if t.rowCount() == 0:
        return (0, '-', '-')
    return (t.rowCount(), t.item(0, 0).text(), t.item(0, 1).text())


base = snapshot_rows(table)
w8._create_new_preset(combo)
check('新建预设后表格内容不变', snapshot_rows(table) == base,
      f"{snapshot_rows(table)}")

combo2 = QComboBox()
combo2.addItems(['默认', '预设B'])
combo2.setCurrentText('预设B')  # 连接前初始化，模拟真实对话框时序
table2 = QTableWidget()
table2.setColumnCount(3)
table2.setRowCount(2)
table2.setItem(0, 0, QTableWidgetItem('03'))
table2.setItem(0, 1, QTableWidgetItem('丙'))
table2.setItem(1, 0, QTableWidgetItem('04'))
table2.setItem(1, 1, QTableWidgetItem('丁'))
combo2.currentTextChanged.connect(lambda name: w8._load_preset_to_table(name, table2) if name else None)
base2 = snapshot_rows(table2)
w8._delete_preset(combo2)
check('删除预设后表格内容不变', snapshot_rows(table2) == base2,
      f"{snapshot_rows(table2)}")
entity_mixin_module.EntityConfigManager = orig_mgr


# ============ 5. 死代码清理 ============
print()
print("== 5. BatchConfigDialog 死代码已删除 ==")
check('config_dialog 模块不存在 BatchConfigDialog',
      not hasattr(config_dialog_module, 'BatchConfigDialog'))


print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
