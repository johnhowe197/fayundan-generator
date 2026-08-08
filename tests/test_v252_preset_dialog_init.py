# -*- coding: utf-8 -*-
"""
v2.5.2 发运主体对话框初始化不同步修复回归测试

覆盖 2026-08-08 修复：打开"发运主体定义"对话框时，下拉框初始化为当前
预设，但明细表格初始内容却来自全局发运主体定义（load_definitions），
导致"下拉显示转载机、明细显示输送机"，必须手动切换下拉才刷新。

修复后：表格初始内容优先加载当前预设，无当前预设时回退全局定义。

用法：python tests/test_v252_preset_dialog_init.py
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
from PyQt5.QtWidgets import (QApplication, QComboBox, QTableWidget)

app = QApplication.instance() or QApplication(sys.argv)

# show_entity_definition 内部 exec_() 会阻塞：替换 QDialog 捕获实例并跳过事件循环
import ui.entity_mixin as entity_mixin_module

captured_dialogs = []
_orig_qdialog = entity_mixin_module.QDialog


class CaptureDialog(_orig_qdialog):
    def exec_(self):
        captured_dialogs.append(self)
        return 0


entity_mixin_module.QDialog = CaptureDialog


def find_widgets(layout, cls):
    """递归查找布局中的指定类型控件"""
    result = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is not None:
            if isinstance(w, cls):
                result.append(w)
            wl = w.layout()
            if wl is not None:
                result.extend(find_widgets(wl, cls))
        sub = item.layout()
        if sub is not None:
            result.extend(find_widgets(sub, cls))
    return result


# ============ 测试环境：真实 EntityConfigManager + 临时配置目录 ============
TMP_DIR = Path(tempfile.mkdtemp(prefix='v252_preset_'))

ZHUANZAI_PRESET_ENTITIES = {
    "01": "转载机机头", "02": "悬空段", "03": "左过渡槽3", "05": "右挡板",
    "06": "前挡板", "07": "后挡板", "08": "上挡板", "09": "下挡板",
    "10": "侧挡板", "90": "增供件", "91": "液压管路", "96": "换面件",
    "98": "捆装发运类", "99": "整合装箱类", "00": "无序号特殊发运",
}
# 全局发运主体定义（输送机特征，区别于转载机预设）
GLOBAL_DEFINITIONS = [
    ["01", "机头", ""], ["02", "左过渡槽", ""], ["98", "捆装发运类", ""],
    ["00", "无序号特殊发运", ""],
]


def setup_presets(current_preset):
    config = {
        "presets": {
            "输送机发运": {"description": "输送机发运配置", "entities": {"01": "机头", "98": "捆装发运类", "00": "无序号特殊发运"}},
            "转载机发运": {"description": "转载机发运配置", "entities": dict(ZHUANZAI_PRESET_ENTITIES)},
        },
        "current_preset": current_preset,
    }
    (TMP_DIR / 'shipping_presets.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')


(TMP_DIR / 'entity_definition.json').write_text(
    json.dumps(GLOBAL_DEFINITIONS, ensure_ascii=False, indent=2), encoding='utf-8')

orig_mgr = entity_mixin_module.EntityConfigManager


class TestManager(orig_mgr):
    """真实 EntityConfigManager 子类：无参构造时指向临时配置目录"""

    def __init__(self):
        super().__init__(config_dir=TMP_DIR)


entity_mixin_module.EntityConfigManager = TestManager

from ui.main_window import MainWindow


def table_rows(table):
    """返回表格全部 (code, name) 列表"""
    rows = []
    for r in range(table.rowCount()):
        code = table.item(r, 0).text() if table.item(r, 0) else ''
        name = table.item(r, 1).text() if table.item(r, 1) else ''
        rows.append((code, name))
    return rows


# ============ 1. 当前预设存在：表格初始内容 == 当前预设 ============
print()
print("== 1. 打开对话框：表格初始内容与下拉框（当前预设）一致 ==")
setup_presets('转载机发运')
captured_dialogs.clear()
w = MainWindow()
w.show_entity_definition()
check('对话框已构造', len(captured_dialogs) == 1, f"{len(captured_dialogs)}")
dialog = captured_dialogs[0]
combos = find_widgets(dialog.layout(), QComboBox)
tables = find_widgets(dialog.layout(), QTableWidget)
check('对话框含 1 个下拉框', len(combos) == 1, f"{len(combos)}")
check('对话框含 1 个明细表格', len(tables) == 1, f"{len(tables)}")
combo, table = combos[0], tables[0]
check('下拉框初始为当前预设（转载机发运）', combo.currentText() == '转载机发运',
      f"combo={combo.currentText()}")
rows = table_rows(table)
check('表格首行为转载机预设首项（01-转载机机头）', rows[0] == ('01', '转载机机头'),
      f"{rows[0]}")
check('表格不含全局定义特征（左过渡槽）', all(n != '左过渡槽' for _, n in rows),
      f"{rows}")
check('锁定代码已补齐（95-液压管路）', ('95', '液压管路') in rows,
      f"{rows}")
check('表格行数 = 预设 15 条 + 补 95/97 共 17', len(rows) == 17,
      f"rows={len(rows)}")


# ============ 2. 当前预设不存在：回退全局定义 ============
print()
print("== 2. 当前预设不存在：表格回退全局发运主体定义 ==")
setup_presets('不存在的预设')
captured_dialogs.clear()
w.show_entity_definition()
dialog = captured_dialogs[0]
combo = find_widgets(dialog.layout(), QComboBox)[0]
table = find_widgets(dialog.layout(), QTableWidget)[0]
rows = table_rows(table)
check('表格显示全局定义（含左过渡槽）', any(n == '左过渡槽' for _, n in rows),
      f"{rows}")
check('表格首行为全局定义首项（01-机头）', rows[0] == ('01', '机头'),
      f"{rows[0]}")


entity_mixin_module.QDialog = _orig_qdialog
entity_mixin_module.EntityConfigManager = orig_mgr
shutil.rmtree(TMP_DIR, ignore_errors=True)

print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)