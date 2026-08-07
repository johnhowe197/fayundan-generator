# -*- coding: utf-8 -*-
"""
v2.3.1 发运主体配置"保存后丢失"修复回归测试

覆盖缺陷：打包 EXE 在不可写目录下运行时，发运主体定义/预设写入失败，
但界面仍提示"保存成功"，用户重开程序后配置丢失（静默失败）。

修复要点：
- save_definitions/save_presets 失败时记录 last_error 并写入 error.log；
- _save_entity_definition 检查写入结果：失败时弹错误框（含原因与配置目录）、
  不关闭对话框，绝不谎报成功；
- 新建预设失败时区分"已存在"与"写入失败"。

用法：python tests/test_v231_fixes.py
"""
import sys
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


from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

dialog_log = []
QMessageBox.information = lambda parent, title, text, *a, **k: (
    dialog_log.append(('information', title, text)), QMessageBox.Ok)[1]
QMessageBox.warning = lambda parent, title, text, *a, **k: (
    dialog_log.append(('warning', title, text)), QMessageBox.Ok)[1]
QMessageBox.question = lambda parent, title, text, *a, **k: (
    dialog_log.append(('question', title, text)), QMessageBox.Yes)[1]
QMessageBox.critical = lambda parent, title, text, *a, **k: (
    dialog_log.append(('critical', title, text)), QMessageBox.Ok)[1]

from core.entity_config import EntityConfigManager


# ============ 1. 数据层：写入失败必须返回 False 并记录原因 ============
print("== 1. 数据层：写入失败返回 False 并记录 last_error ==")
tmp = Path(tempfile.mkdtemp())
mgr = EntityConfigManager(config_dir=tmp / 'config')

# 把目标文件位置占成目录，强制写入失败（先删除构造时播种出来的出厂文件）
if mgr._entity_file.exists():
    mgr._entity_file.unlink()
mgr._entity_file.mkdir(parents=True, exist_ok=True)
ok = mgr.save_definitions([('01', '机头', '物理分组')])
check('save_definitions 写入失败返回 False', ok is False)
check('失败原因记录到 last_error', bool(mgr.last_error), f'last_error={mgr.last_error!r}')

mgr._preset_file.parent.mkdir(parents=True, exist_ok=True)
if mgr._preset_file.exists():
    mgr._preset_file.unlink()
mgr._preset_file.mkdir(parents=True, exist_ok=True)
ok = mgr.save_presets({'presets': {}, 'current_preset': ''})
check('save_presets 写入失败返回 False', ok is False)
check('预设失败原因记录到 last_error', bool(mgr.last_error))


# ============ 2. 数据层：成功写入后 last_error 清空、内容可回读 ============
print()
print("== 2. 数据层：成功写入后 last_error 清空、内容可回读 ==")
mgr2 = EntityConfigManager(config_dir=tmp / 'config2')
mgr2.last_error = '残留错误'
ok = mgr2.save_definitions([('01', '测试机头', '物理分组'), ('98', '捆装发运类', '特殊')])
check('可写目录下保存成功', ok is True)
check('成功后 last_error 被清空', mgr2.last_error == '')
loaded = mgr2.load_definitions()
loaded_map = {code: name for code, name, desc in loaded}
check('回读内容与保存一致', loaded_map.get('01') == '测试机头')
check('锁定代码自动补齐', '99' in loaded_map and '00' in loaded_map)


# ============ 3. UI层：保存失败时绝不谎报成功 ============
print()
print("== 3. UI层：保存失败不谎报成功、不关闭对话框 ==")
from ui.main_window import MainWindow


class FakeItem:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def rowCount(self):
        return len(self._rows)

    def item(self, row, col):
        return FakeItem(self._rows[row][col])


class FakeDialog:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


window = MainWindow()
fake_table = FakeTable([('01', '机头', '物理分组')])
fake_dialog = FakeDialog()

orig_save_def = EntityConfigManager.save_definitions
EntityConfigManager.save_definitions = lambda self, entities: False
dialog_log.clear()
window._save_entity_definition(fake_table, fake_dialog)
EntityConfigManager.save_definitions = orig_save_def

check('保存失败时弹出错误框', any(k == 'critical' for k, _, _ in dialog_log))
crit = next((t for k, _, t in dialog_log if k == 'critical'), '')
check('错误框包含真实失败原因', '配置目录' in crit or '失败' in crit, f'text={crit[:80]!r}')
check('失败时不显示"已保存"成功提示',
      not any(k == 'information' and '已保存' in t for k, _, t in dialog_log))
check('失败时对话框保持打开（便于用户处理后重试）', fake_dialog.closed is False)


# ============ 4. UI层：保存成功时正常提示并关闭 ============
print()
print("== 4. UI层：保存成功正常提示并关闭（回归） ==")
saved_calls = []
cached_backup = EntityConfigManager._cached_entity_map
EntityConfigManager.save_definitions = lambda self, entities: (
    saved_calls.append(('definitions', list(entities))), True)[1]
orig_save_preset = EntityConfigManager.save_preset
EntityConfigManager.save_preset = lambda self, name, entities: (
    saved_calls.append(('preset', name)), True)[1]

fake_dialog2 = FakeDialog()
dialog_log.clear()
try:
    window._save_entity_definition(fake_table, fake_dialog2)
finally:
    EntityConfigManager.save_definitions = orig_save_def
    EntityConfigManager.save_preset = orig_save_preset
    EntityConfigManager._cached_entity_map = cached_backup

check('成功时显示保存成功提示',
      any(k == 'information' and '已保存' in t for k, _, t in dialog_log))
check('成功时对话框关闭', fake_dialog2.closed is True)
check('定义与当前预设均已写入',
      any(c[0] == 'definitions' for c in saved_calls), f'calls={saved_calls}')


print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
