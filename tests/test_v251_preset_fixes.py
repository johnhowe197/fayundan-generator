# -*- coding: utf-8 -*-
"""
v2.5.1 发运主体预设缺陷修复回归测试

覆盖 2026-08-08 四处缺陷修复：
- 缺陷 A：新建预设后未设为当前预设（v2.5 blockSignals 回归）→ 修复后
  _create_new_preset 显式 set_current_preset，随后的"保存"把内容写入新预设
- 缺陷 B：重置预设后下拉框未刷新、残留陈旧项 → 修复后下拉与文件一致，
  切换不再报"预设不存在"
- 缺陷 C：save_presets/save_definitions 非原子写入 → 修复后先写临时文件
  再 os.replace 原子替换，写入中断不损坏原配置
- 缺陷 D：名称输入框"确定但为空"静默返回 → 修复后明确提示，避免误以为已保存

用法：python tests/test_v251_preset_fixes.py
"""
import sys
import json
import shutil
import tempfile
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
from PyQt5.QtWidgets import (QApplication, QMessageBox, QInputDialog,
                             QComboBox, QTableWidget, QTableWidgetItem,
                             QDialog)

app = QApplication.instance() or QApplication(sys.argv)

dialog_log = []
question_answer = {'value': QMessageBox.Yes}
input_answer = {'name': '新预设', 'ok': True}


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
QInputDialog.getText = lambda *a, **k: (input_answer['name'], input_answer['ok'])

import ui.entity_mixin as entity_mixin_module
from ui.main_window import MainWindow


# ============ 测试环境：真实 EntityConfigManager + 临时配置目录 ============
TMP_DIR = Path(tempfile.mkdtemp(prefix='v251_preset_'))

INITIAL_CONFIG = {
    "presets": {
        "输送机发运": {
            "description": "输送机发运配置",
            "entities": {"01": "机头", "98": "捆装发运类", "99": "整合装箱类", "00": "无序号特殊发运"}
        },
        "转载机发运": {
            "description": "转载机发运配置",
            "entities": {"01": "转载机机头", "98": "捆装发运类", "00": "无序号特殊发运"}
        },
        "自定义": {
            "description": "自定义发运配置",
            "entities": {}
        },
    },
    "current_preset": "输送机发运",
}
(TMP_DIR / 'shipping_presets.json').write_text(
    json.dumps(INITIAL_CONFIG, ensure_ascii=False, indent=2), encoding='utf-8')

orig_mgr = entity_mixin_module.EntityConfigManager


class TestManager(orig_mgr):
    """真实 EntityConfigManager 子类：无参构造时指向临时配置目录"""

    def __init__(self):
        super().__init__(config_dir=TMP_DIR)


entity_mixin_module.EntityConfigManager = TestManager

w = MainWindow()


def snapshot_rows(t):
    """返回表格内容快照（行数 + 首行两格文本），空表时首行为 '-'"""
    if t.rowCount() == 0:
        return (0, '-', '-')
    return (t.rowCount(), t.item(0, 0).text(), t.item(0, 1).text())


def make_combo_table(mgr, current):
    """构造与真实对话框同款的 combo + table 连接（先初始化再连接，模拟真实时序）"""
    combo = QComboBox()
    combo.addItems(mgr.get_preset_names())
    if current in mgr.get_preset_names():
        combo.setCurrentText(current)
    table = QTableWidget()
    table.setColumnCount(3)
    table.setRowCount(1)
    table.setItem(0, 0, QTableWidgetItem('03'))
    table.setItem(0, 1, QTableWidgetItem('丙'))
    combo.currentTextChanged.connect(
        lambda name: w._load_preset_to_table(name, table) if name else None)
    return combo, table


# ============ 1. 缺陷 A：新建预设即设为当前 ============
print()
print("== 1. 新建预设后 current_preset 正确（缺陷 A）==")
dialog_log.clear()
combo, table = make_combo_table(TestManager(), '输送机发运')
base = snapshot_rows(table)
input_answer['name'] = '新预设'
input_answer['ok'] = True
w._create_new_preset(combo)
mgr = TestManager()
check('新建后 current_preset == 新预设',
      mgr.get_current_preset_name() == '新预设',
      f"actual={mgr.get_current_preset_name()}")
check('表格内容未被新建动作覆盖', snapshot_rows(table) == base,
      f"{snapshot_rows(table)}")
check('新预设已出现在下拉并选中', combo.currentText() == '新预设',
      f"combo={combo.currentText()}")

# 模拟用户编辑表格后点"保存"：内容应写入新预设，而不是旧预设
table.setRowCount(2)
table.setItem(1, 0, QTableWidgetItem('04'))
table.setItem(1, 1, QTableWidgetItem('丁'))
w._save_entity_definition(table, QDialog())
mgr = TestManager()
saved = mgr.get_preset('新预设').get('entities', {})
check('保存后新预设包含编辑内容', saved.get('04') == '丁',
      f"{saved}")
check('旧预设未被误写', '04' not in mgr.get_preset('输送机发运').get('entities', {}),
      f"{mgr.get_preset('输送机发运').get('entities', {})}")


# ============ 2. 缺陷 B：重置后下拉与文件一致 ============
print()
print("== 2. 重置预设后下拉刷新（缺陷 B）==")
dialog_log.clear()
combo2, table2 = make_combo_table(mgr, mgr.get_current_preset_name())
question_answer['value'] = QMessageBox.Yes
w._reset_presets(combo2)
mgr = TestManager()
names = [combo2.itemText(i) for i in range(combo2.count())]
check('重置后下拉 == 文件预设集', names == mgr.get_preset_names() == ['输送机发运'],
      f"combo={names} file={mgr.get_preset_names()}")
# 修复前：下拉残留陈旧项，切换旧项会报"预设不存在"；修复后只剩文件中的预设
dialog_log.clear()
w._load_preset_to_table('输送机发运', table2)
check('加载唯一剩余预设无"不存在"弹窗',
      not any('不存在' in t for _, _, t in dialog_log),
      f"{dialog_log}")


# ============ 3. 缺陷 C：原子写入 ============
print()
print("== 3. save_presets/save_definitions 原子写入（缺陷 C）==")
import core.entity_config as ec_module
orig_dump = ec_module.json.dump


def boom(*a, **k):
    raise IOError('模拟写入中断')


# 重置后的文件内容（只有输送机发运）作为"原文件"基线
after_reset = json.loads((TMP_DIR / 'shipping_presets.json').read_text(encoding='utf-8'))

ec_module.json.dump = boom
try:
    ok = mgr.save_presets({'presets': {'新配置': {}}, 'current_preset': '新配置'})
finally:
    ec_module.json.dump = orig_dump
check('写入中断时 save_presets 返回 False', ok is False)
check('原配置文件内容完好',
      json.loads((TMP_DIR / 'shipping_presets.json').read_text(encoding='utf-8')) == after_reset,
      '原文件被破坏')
check('tmp 残留不影响读取', mgr.load_presets() == after_reset)

# save_definitions 同样验证
(TMP_DIR / 'entity_definition.json').write_text(
    json.dumps([['01', '机头', '物理分组']], ensure_ascii=False), encoding='utf-8')
ec_module.json.dump = boom
try:
    ok2 = mgr.save_definitions([['02', '左过渡槽', '物理分组']])
finally:
    ec_module.json.dump = orig_dump
check('写入中断时 save_definitions 返回 False', ok2 is False)
check('原定义文件完好',
      json.loads((TMP_DIR / 'entity_definition.json').read_text(encoding='utf-8'))
      == [['01', '机头', '物理分组']])

# 正常写入仍成功
ok3 = mgr.save_presets({'presets': {'正常': {'entities': {'01': '机头'}}}, 'current_preset': '正常'})
check('正常写入成功', ok3 is True
      and json.loads((TMP_DIR / 'shipping_presets.json').read_text(encoding='utf-8'))
      .get('current_preset') == '正常')


# ============ 4. 缺陷 D：空名提示 / 取消静默 ============
print()
print("== 4. 名称空/取消不再静默（缺陷 D）==")
mgr = TestManager()
combo4, table4 = make_combo_table(mgr, '正常')
before_names = set(mgr.get_preset_names())

# 场景1：保存为预设，确定但空名 → warning 且未写入
dialog_log.clear()
input_answer['name'] = ''
input_answer['ok'] = True
w._save_table_as_preset('', table4, combo4)
mgr = TestManager()
check('空名保存弹 warning', any(title == '警告' for _, title, _ in dialog_log),
      f"{dialog_log}")
check('空名保存未写入新预设', set(mgr.get_preset_names()) == before_names,
      f"{mgr.get_preset_names()}")

# 场景2：新建预设，确定但空名 → warning 且未创建
dialog_log.clear()
w._create_new_preset(combo4)
mgr = TestManager()
check('空名新建弹 warning', any(title == '警告' for _, title, _ in dialog_log),
      f"{dialog_log}")
check('空名新建未创建预设', set(mgr.get_preset_names()) == before_names,
      f"{mgr.get_preset_names()}")

# 场景3：用户取消 → 静默且未写入
dialog_log.clear()
input_answer['name'] = '取消测试'
input_answer['ok'] = False
w._save_table_as_preset('', table4, combo4)
w._create_new_preset(combo4)
mgr = TestManager()
check('取消后无任何弹窗', len(dialog_log) == 0, f"{dialog_log}")
check('取消后未创建/未写入', '取消测试' not in mgr.get_preset_names(),
      f"{mgr.get_preset_names()}")


# ============ 5. 回归：覆盖保存后下拉与 current_preset 仍正确 ============
print()
print("== 5. 覆盖保存回归 ==")
dialog_log.clear()
question_answer['value'] = QMessageBox.Yes
input_answer['name'] = '正常'
input_answer['ok'] = True
combo5, table5 = make_combo_table(mgr, mgr.get_current_preset_name())
table5.setRowCount(2)
table5.setItem(1, 0, QTableWidgetItem('05'))
table5.setItem(1, 1, QTableWidgetItem('戊'))
w._save_table_as_preset('正常', table5, combo5)
mgr = TestManager()
check('覆盖保存后 current_preset 正确', mgr.get_current_preset_name() == '正常',
      f"actual={mgr.get_current_preset_name()}")
check('下拉含目标预设且选中', combo5.currentText() == '正常',
      f"combo={combo5.currentText()}")
check('覆盖保存后文件含编辑内容', mgr.get_preset('正常').get('entities', {}).get('05') == '戊',
      f"{mgr.get_preset('正常').get('entities', {})}")


entity_mixin_module.EntityConfigManager = orig_mgr
shutil.rmtree(TMP_DIR, ignore_errors=True)

print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
