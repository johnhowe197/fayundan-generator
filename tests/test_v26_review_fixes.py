# -*- coding: utf-8 -*-
"""
v2.6 代码审查缺陷修复测试

覆盖 01_architect_plan.md 中第一批 A（A1-A10，含 A2-1）与
第二/三批 B（B1-B9）的关键行为。

用法（无显示环境）：
    QT_QPA_PLATFORM=offscreen python -X utf8 tests/test_v26_review_fixes.py

每个用例都对应一个“修复前会失败”的断言，避免测试只是复述实现。
"""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
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


# ============ Qt 环境与对话框拦截 ============
from PyQt5.QtWidgets import (QApplication, QMessageBox, QDialog, QInputDialog,
                             QFileDialog, QComboBox, QLineEdit, QTableWidget)
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

dialog_log = []
question_queue = []
exec_behavior = {'fn': lambda dlg: QDialog.Rejected}
input_return = {'value': ('', True)}
file_behavior = {'open': ('', ''), 'save': ('', '')}


def _fake_information(parent, title, text, *args, **kwargs):
    dialog_log.append(('information', title, text))
    return QMessageBox.Ok


def _fake_warning(parent, title, text, *args, **kwargs):
    dialog_log.append(('warning', title, text))
    return QMessageBox.Ok


def _fake_question(parent, title, text, *args, **kwargs):
    dialog_log.append(('question', title, text))
    return question_queue.pop(0) if question_queue else QMessageBox.Yes


def _fake_critical(parent, title, text, *args, **kwargs):
    dialog_log.append(('critical', title, text))
    return QMessageBox.Ok


QMessageBox.information = _fake_information
QMessageBox.warning = _fake_warning
QMessageBox.question = _fake_question
QMessageBox.critical = _fake_critical
QDialog.exec_ = lambda self: exec_behavior['fn'](self)
QInputDialog.getText = staticmethod(lambda *a, **k: input_return['value'])
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: file_behavior['open'])
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: file_behavior['save'])

import pandas as pd

from core.bom_parser import BOMParser, parse_level
from core.tree_builder import TreeBuilder
from core.calculator import ShippingCalculator
from core.exporter import ShippingExporter
from core.entity_config import EntityConfigManager
from core.progress_config import ProgressFileManager
from models.bom_node import BOMNode
from ui.main_window import MainWindow
from ui.entity_mixin import _cell_text, _entity_code


def _node(mid, level, expand, parent=None, entity='', method='',
          remark='', qty=1):
    """构造节点并通过 add_child 建立父子关系"""
    node = BOMNode(
        material_id=mid,
        parent_id=parent.material_id if parent else '',
        name=mid,
        level=level,
        expand_status=expand,
        shipping_entity=entity,
        shipping_method=method,
        remark=remark,
        quantity=qty,
    )
    if parent:
        parent.add_child(node)
    return node


def make_window():
    """合成一棵结构正常的树

    ROOT(0,是)
    ├── A(1,是)
    │   └── A1(2,否, 01/A)
    └── B(1,否, 01/A)
    """
    w = MainWindow()
    root = _node('ROOT', 0, '是', qty=1)
    a = _node('A', 1, '是', root, qty=2)
    a1 = _node('A1', 2, '否', a, entity='01', method='A', qty=3)
    b = _node('B', 1, '否', root, entity='01', method='A', qty=1)
    w.tree_builder.root = root
    w.tree_builder.all_nodes = [root, a, a1, b]
    w.refresh_tree()
    return w, {'root': root, 'a': a, 'a1': a1, 'b': b}


def find_item(w, uid):
    """按节点 uid 查找树控件项（含隐藏项）"""
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


def check_item(w, uid):
    item = find_item(w, uid)
    item.setCheckState(0, Qt.Checked)
    return item


def bom_df(rows):
    """构造 BOM 清洗输入（列顺序固定）"""
    return pd.DataFrame(
        rows,
        columns=['层号', '子物料号', '父物料号', '名称', '数量', '子物料净重'])


def _set_batch_dialog(expand=None, entity=None, method=None, remark=''):
    """构造 batch_config 的假对话框行为"""
    def _fn(dlg):
        combos = dlg.findChildren(QComboBox)
        for combo in combos:
            items = [combo.itemText(i) for i in range(combo.count())]
            if '是' in items and '否' in items:
                if expand is not None:
                    combo.setCurrentText(expand)
            elif entity is not None and any('-' in t for t in items):
                combo.setCurrentText(entity)
            elif method is not None and any('散装' in t for t in items):
                combo.setCurrentText(method)
        for edit in dlg.findChildren(QLineEdit):
            edit.setText(remark)
        return QDialog.Accepted
    exec_behavior['fn'] = _fn


# ==================== A1 层号解析 ====================
print()
print("== A1 层号解析与根节点层级 ==")
check('parse_level(0.0)==0', parse_level(0.0) == 0)
check('parse_level(1.0)==1', parse_level(1.0) == 1)
check('parse_level(2.0)==2', parse_level(2.0) == 2)
check("parse_level('.2')==2", parse_level('.2') == 2)
check("parse_level('..3')==3", parse_level('..3') == 3)
check("parse_level('0')==0", parse_level('0') == 0)
check("parse_level('')==0", parse_level('') == 0)

try:
    parse_level('第二层')
    bad_level_raised = False
except ValueError as e:
    bad_level_raised = '第二层' in str(e)
check('无法识别的层号抛 ValueError 且带原值', bad_level_raised)

parser = BOMParser()
cleaned = parser._clean_data(bom_df([
    (0.0, 'R', '', '根', 1, 1),
    (1.0, 'C', 'R', '子', 2, 1),
]).copy())
builder = TreeBuilder()
root = builder.build_from_dataframe(cleaned)
child = [n for n in builder.all_nodes if n.material_id == 'C'][0]
child.expand_status = '否'
child.shipping_entity = '01'
child.shipping_method = 'A'
check('0.0 层号的根节点 level==0', root.level == 0, f'level={root.level}')
check('根节点是否展开=是', root.expand_status == '是')
check('发运单元数 > 0', len(builder.get_all_shipping_units()) > 0)


# ==================== A3 数量/净重校验 ====================
print()
print("== A3 非法数量/净重阻断、空值口径 ==")

for bad_value in ('1,000', '2套'):
    try:
        BOMParser()._clean_data(bom_df([
            (0, 'R', '', '根', 1, 1),
            (1, 'C', 'R', '子', bad_value, 1),
        ]).copy())
        a3_raised = False
        a3_msg = ''
    except ValueError as e:
        a3_raised = True
        a3_msg = str(e)
    check(f'数量 {bad_value!r} 导入即报错', a3_raised, a3_msg)
    check(f'错误信息包含原值与行号（{bad_value!r}）',
          bad_value in a3_msg and '第3行' in a3_msg, a3_msg)

cleaned = BOMParser()._clean_data(bom_df([
    (0, 'R', '', '根', 1, None),
    (1, 'C', 'R', '子', 2, None),
]).copy())
check('空净重按 0 处理',
      float(cleaned.loc[cleaned['子物料号'] == 'C', '子物料净重'].iloc[0]) == 0.0)

try:
    BOMParser()._clean_data(bom_df([
        (0, 'R', '', '根', 1, 1),
        (1, 'C', 'R', '子', 2, 'abc'),
    ]).copy())
    a3_weight_raised = False
except ValueError:
    a3_weight_raised = True
check('非空非法净重同样阻断', a3_weight_raised)

# 非顶级空数量保留 NaN，交给计算引擎现有守卫报错
cleaned = BOMParser()._clean_data(bom_df([
    (0, 'R', '', '根', 1, 1),
    (1, 'C', 'R', '子', None, 1),
]).copy())
builder = TreeBuilder()
builder.build_from_dataframe(cleaned)
for node in builder.all_nodes:
    if node.material_id != 'R':
        node.expand_status = '否'
        node.shipping_entity = '01'
        node.shipping_method = 'A'
try:
    ShippingCalculator(builder).generate_shipping_order()
    a3_nan_raised = False
    a3_nan_msg = ''
except ValueError as e:
    a3_nan_raised = True
    a3_nan_msg = str(e)
check('非顶级空数量在计算时抛既有空数量错误',
      a3_nan_raised and '空数量' in a3_nan_msg, a3_nan_msg)

cleaned = BOMParser()._clean_data(bom_df([
    (0, 'R', '', '根', 1, 1),
    (1, 'C', 'R', '子', 2, 0.5),
]).copy())
check('合法数据数值不变',
      list(cleaned['数量']) == [1, 2]
      and float(cleaned['子物料净重'].iloc[1]) == 0.5)


# ==================== A2-1 结构检测与计算前确认 ====================
print()
print("== A2-1 孤儿节点/多根检测与计算前确认 ==")
builder = TreeBuilder()
builder.build_from_dataframe(pd.DataFrame({
    '子物料号': ['R', 'C1', 'C2'],
    '父物料号': ['', 'MISSING', 'R'],
    '名称': ['根', '孤儿', '正常'],
    '数量': [1, 2, 3],
    '子物料净重': [1, 1, 1],
    'level': [0, 1, 1],
}))
check('检测到孤儿节点', any(n.material_id == 'C1' for n in builder.orphan_nodes),
      f"{[n.material_id for n in builder.orphan_nodes]}")
check('结构问题列表非空', len(builder.structure_issues) > 0,
      f"{builder.structure_issues}")

builder2 = TreeBuilder()
builder2.build_from_dataframe(pd.DataFrame({
    '子物料号': ['R1', 'R2'],
    '父物料号': ['', ''],
    '名称': ['根1', '根2'],
    '数量': [1, 1],
    '子物料净重': [1, 1],
    'level': [0, 0],
}))
check('检测到多个顶级节点',
      any('顶级节点' in issue for issue in builder2.structure_issues),
      f"{builder2.structure_issues}")

w, nodes = make_window()
orphan = BOMNode(material_id='ORPHAN', parent_id='NOPE', name='孤儿', level=1)
w.tree_builder.all_nodes.append(orphan)
w.tree_builder.validate_structure()
question_queue[:] = [QMessageBox.No]
dialog_log.clear()
w.calculate()
check('孤儿存在时计算前询问', any(t == 'question' for t, _, _ in dialog_log))
check('用户取消后不生成发运单', w.current_shipping_order is None)
check('取消后没有成功提示',
      not any(t == 'information' and '计算完成' in txt for t, _, txt in dialog_log))


# ==================== A4 总重写数值 ====================
print()
print("== A4 导出 H 列写数值、口径一致 ==")
export_df = pd.DataFrame([{
    '序号': 1, '物料号': 'M1', '图号': 'D1', '规格': 'S1', '名称': '零件',
    '数量': 3, '净重': 1.5, '总重(kg)': 4.5,
    '发运类型': 'A', '发运主体': '01-机头', '备注': '',
}])
with tempfile.TemporaryDirectory() as tmp:
    xlsx = Path(tmp) / 'out.xlsx'
    ShippingExporter().export_to_excel(export_df, str(xlsx), total_weight=4.5)
    import openpyxl
    ws = openpyxl.load_workbook(xlsx)['发运单']
    h_cell = ws.cell(7, 8)
    check('H 列不是公式', h_cell.data_type != 'f', f"data_type={h_cell.data_type}")
    check('H 列数值等于 calculator 总重', abs(float(h_cell.value) - 4.5) < 1e-9,
          f"value={h_cell.value!r}")
    check('数量 number_format=0', ws.cell(7, 6).number_format == '0')
    check('总重 number_format=0.00', h_cell.number_format == '0.00')
    check('H4 项目总重与逐行同源', str(ws['H4'].value) == '4 kg',
          f"H4={ws['H4'].value!r}")
    csv_path = Path(tmp) / 'out.csv'
    ShippingExporter().export_to_csv(export_df, str(csv_path))
    csv_df = pd.read_csv(csv_path)
    check('CSV 总重与 Excel 同值',
          abs(float(csv_df['总重(kg)'].iloc[0]) - 4.5) < 1e-9)


# ==================== A5 NaN 清洗 ====================
print()
print("== A5 配置空单元格不写成 nan ==")
builder = TreeBuilder()
builder.build_from_dataframe(pd.DataFrame({
    '子物料号': ['R', 'C'],
    '父物料号': ['', 'R'],
    '名称': ['根', '子'],
    '数量': [1, 2],
    '子物料净重': [1, 1],
    'level': [0, 1],
}))
with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / 'cfg.xlsx'
    pd.DataFrame([{
        '父物料号': 'R', '物料号': 'C', '是否展开': None,
        '发运主体': None, '发运方式': None, '备注': None,
    }]).to_excel(cfg, index=False)
    builder.load_config(str(cfg))
    child = [n for n in builder.all_nodes if n.material_id == 'C'][0]
    check('发运主体不写 nan', child.shipping_entity == '', repr(child.shipping_entity))
    check('发运方式不写 nan', child.shipping_method == '', repr(child.shipping_method))
    check('备注不写 nan', child.remark == '', repr(child.remark))
    check('是否展开保持默认否', child.expand_status == '否', repr(child.expand_status))


# ==================== A6 配置匹配规范化 ====================
print()
print("== A6 配置匹配规范化与同键多实例 ==")
builder = TreeBuilder()
builder.build_from_dataframe(pd.DataFrame({
    '子物料号': ['R', '12345', '12345'],
    '父物料号': ['', 'R', 'R'],
    '名称': ['根', '拆分1', '拆分2'],
    '数量': [1, 2, 3],
    '子物料净重': [1, 1, 1],
    'level': [0, 1, 1],
}))
with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / 'cfg.xlsx'
    pd.DataFrame([
        {'父物料号': 'R', '物料号': '12345.0', '发运主体': '1', '发运方式': 'A'},
        {'父物料号': 'R', '物料号': '12345', '发运主体': '98', '发运方式': 'B'},
        {'父物料号': 'X', '物料号': 'ZZZ', '发运主体': '02'},
    ]).to_excel(cfg, index=False)
    builder.load_config(str(cfg))
instances = [n for n in builder.all_nodes if n.material_id == '12345']
check('12345.0 能匹配 12345', len(instances) == 2)
check('同父同物料两实例分别恢复',
      instances[0].shipping_entity == '01' and instances[1].shipping_entity == '98',
      f"{[n.shipping_entity for n in instances]}")
check('发运主体 1 规范化为 01', instances[0].shipping_entity == '01')
check('未匹配配置行进入 warnings', len(builder.config_load_warnings) > 0,
      f"{builder.config_load_warnings}")


# ==================== A7 长物料号精度 ====================
print()
print("== A7 19 位物料号精度与父子关系 ==")
root_id = '9000000000000000001'
child_id = '1234567890123456789'
with tempfile.TemporaryDirectory() as tmp:
    csv_path = Path(tmp) / 'bom.csv'
    pd.DataFrame({
        '层号': ['0', '1'],
        '子物料号': [root_id, child_id],
        '父物料号': ['', root_id],
        '名称': ['根', '子'],
        '数量': [1, 2],
        '子物料净重': [1, 1],
    }).to_csv(csv_path, index=False, encoding='utf-8-sig')
    df = BOMParser().parse(str(csv_path))
    check('CSV 长物料号逐字符一致',
          list(df['子物料号']) == [root_id, child_id],
          f"{list(df['子物料号'])}")
    builder = TreeBuilder()
    root = builder.build_from_dataframe(df)
    child = [n for n in builder.all_nodes if n.material_id == child_id][0]
    check('长物料号父子关系建立',
          child.parent is root and root.material_id == root_id)

    progress_dir = Path(tmp) / 'progress'
    mgr = ProgressFileManager(progress_dir)
    pfile = progress_dir / 'p.xlsx'
    mgr.save(str(pfile), [root, child],
             {'项目名称': '测试'}, hidden_checker=lambda n: False)
    loaded = mgr.load(str(pfile))['dataframe']
    check('进度文件长物料号逐字符一致',
          list(loaded['子物料号'].astype(str)) == [root_id, child_id],
          f"{list(loaded['子物料号'])}")


# ==================== A8 配置读取健壮性 ====================
print()
print("== A8 损坏 JSON 不崩溃、备份并使用默认值 ==")
with tempfile.TemporaryDirectory() as tmp:
    cfg_dir = Path(tmp)
    mgr = EntityConfigManager(cfg_dir)  # 先构造（播种默认文件），再覆盖为损坏内容

    mgr._entity_file.write_text('{invalid json', encoding='utf-8')
    defs = mgr.load_definitions()
    check('损坏 JSON 返回默认定义', isinstance(defs, list) and len(defs) > 0)
    check('损坏 JSON 记录 last_load_error', bool(mgr.last_load_error))
    check('损坏 JSON 生成 .corrupt.*.bak',
          len(list(cfg_dir.glob('entity_definition.json.corrupt.*.bak'))) >= 1)

    # 带 BOM 的合法 JSON 可读取
    mgr._entity_file.write_text(
        '﻿' + json.dumps([['01', '机头', '']], ensure_ascii=False),
        encoding='utf-8')
    defs = mgr.load_definitions()
    check('带 BOM JSON 可正常读取', defs[0][0] == '01', f"{defs[:1]}")
    check('正常读取不记录错误', mgr.last_load_error == '')

    # 合法 JSON 但结构错误（dict）
    mgr._entity_file.write_text('{"a": 1}', encoding='utf-8')
    defs = mgr.load_definitions()
    check('结构错误的 JSON 不崩溃并回退默认', isinstance(defs, list) and len(defs) > 0)
    check('结构错误记录 last_load_error', bool(mgr.last_load_error))

    # 预设结构错误
    mgr._preset_file.write_text('{"presets": []}', encoding='utf-8')
    presets = mgr.load_presets()
    check('预设结构错误返回默认结构',
          isinstance(presets.get('presets'), dict))
    check('预设结构错误记录 last_load_error', bool(mgr.last_load_error))
    check('预设结构错误生成备份',
          len(list(cfg_dir.glob('shipping_presets.json.corrupt.*.bak'))) >= 1)

    # 修复后保存正常
    check('修复后保存定义成功', mgr.save_definitions([('01', '机头', '')]) is True)
    saved = json.loads(mgr._entity_file.read_text(encoding='utf-8-sig'))
    check('保存内容可读回', saved == [['01', '机头', '']], f"{saved}")


# ==================== A9 实体模板导入 ====================
print()
print("== A9 实体模板代码规范化 ==")
check("_entity_code(1)=='01'", _entity_code(1) == '01')
check("_entity_code(1.0)=='01'", _entity_code(1.0) == '01')
check("_entity_code('01')=='01'", _entity_code('01') == '01')
check("_entity_code(98)=='98'", _entity_code(98) == '98')
check("_entity_code(None)==''", _entity_code(None) == '')
check("_cell_text(nan)==''", _cell_text(float('nan')) == '')
check("_cell_text('nan')==''", _cell_text('nan') == '')

w, _ = make_window()
with tempfile.TemporaryDirectory() as tmp:
    tpl = Path(tmp) / 'tpl.xlsx'
    pd.DataFrame([
        {'代码': 1, '名称': None, '说明': None},
        {'代码': None, '名称': '空代码行', '说明': None},
    ]).to_excel(tpl, index=False)
    table = QTableWidget()
    table.setColumnCount(3)
    file_behavior['open'] = (str(tpl), '')
    dialog_log.clear()
    w._import_entity_template(table)
    check('导入后只保留有效代码行', table.rowCount() == 1, f"{table.rowCount()}")
    check("代码 1 规范化为 '01'", table.item(0, 0).text() == '01',
          repr(table.item(0, 0).text()))
    check('空名称不写 nan', table.item(0, 1).text() == '',
          repr(table.item(0, 1).text()))
    check('分组排序命中 01',
          EntityConfigManager.get_group_sort(table.item(0, 0).text()) == 1)


# ==================== A10 公式注入防护 ====================
print()
print("== A10 Excel/CSV 公式注入防护 ==")
inject_df = pd.DataFrame([{
    '序号': 1, '物料号': 'M1', '图号': 'D1', '规格': 'S1', '名称': '=1+1',
    '数量': 1, '净重': 1, '总重(kg)': 1,
    '发运类型': 'A', '发运主体': '01-机头', '备注': '+x',
}])
with tempfile.TemporaryDirectory() as tmp:
    xlsx = Path(tmp) / 'inj.xlsx'
    ShippingExporter().export_to_excel(inject_df, str(xlsx), total_weight=1)
    import openpyxl
    ws = openpyxl.load_workbook(xlsx)['发运单']
    name_cell = ws.cell(7, 5)
    check('Excel 中 =1+1 保留原文', name_cell.value == '=1+1', repr(name_cell.value))
    check('Excel 中 =1+1 标记为字符串', name_cell.data_type == 's',
          f"data_type={name_cell.data_type}")

    csv_path = Path(tmp) / 'inj.csv'
    ShippingExporter().export_to_csv(inject_df, str(csv_path))
    out = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    check('CSV 中转义 = 前缀', out['名称'].iloc[0].startswith("'="),
          repr(out['名称'].iloc[0]))
    check('CSV 中转义 + 前缀', out['备注'].iloc[0].startswith("'+"),
          repr(out['备注'].iloc[0]))


# ==================== B1 undo/redo 置 dirty ====================
print()
print("== B1 undo/redo 保持 dirty ==")
w, _ = make_window()
w._save_state()
w.undo()
check('撤销到栈空仍标记未保存', w._dirty is True)
w._dirty = False
w.redo()
check('redo 后标记未保存', w._dirty is True)


# ==================== B2 批量备注单快照 ====================
print()
print("== B2 批量备注只产生 1 个撤销点 ==")
w = MainWindow()
root = _node('R', 0, '是', qty=1)
leaves = [_node(f'L{i}', 1, '否', root, entity='01', method='A', qty=1)
          for i in range(20)]
w.tree_builder.root = root
w.tree_builder.all_nodes = [root] + leaves
w.refresh_tree()
for leaf in leaves:
    check_item(w, leaf.uid)
input_return['value'] = ('批量备注', True)
stack_before = len(w._undo_stack)
dialog_log.clear()
w._set_remark_to_checked()
check('20 个节点批量备注只增加 1 个撤销点',
      len(w._undo_stack) == stack_before + 1,
      f"before={stack_before}, after={len(w._undo_stack)}")
check('全部节点备注已更新', all(n.remark == '批量备注' for n in leaves))
check('树控件备注列已更新',
      all(find_item(w, n.uid).text(9) == '批量备注' for n in leaves))


# ==================== B3 叶子节点批量"展开=是"拦截 ====================
print()
print("== B3 叶子节点不能被批量设为展开=是 ==")
w, nodes = make_window()
leaf = nodes['b']
check_item(w, leaf.uid)
_set_batch_dialog(expand='是', remark='不应写入')
dialog_log.clear()
w.batch_config()
check('叶子节点展开状态保持否', leaf.expand_status == '否', leaf.expand_status)
check('叶子节点配置未被清空',
      leaf.shipping_entity == '01' and leaf.shipping_method == 'A')
check('提示中包含叶子节点跳过数',
      any('叶子节点' in txt for _, _, txt in dialog_log))


# ==================== B4 计算失败清空旧结果 ====================
print()
print("== B4 计算异常后清空旧发运单 ==")
w, _ = make_window()
w.current_shipping_order = pd.DataFrame([
    {'物料号': 'OLD', '发运主体': '01-机头', '总重(kg)': 99}])
w.refresh_table()
orig_generate = ShippingCalculator.generate_shipping_order
ShippingCalculator.generate_shipping_order = (
    lambda self: (_ for _ in ()).throw(RuntimeError('模拟计算失败')))
dialog_log.clear()
try:
    w.calculate()
finally:
    ShippingCalculator.generate_shipping_order = orig_generate
check('失败后 current_shipping_order 为 None', w.current_shipping_order is None)
check('失败后表格被清空', w.table_widget.rowCount() == 0)
check('失败后总重归零', w.lbl_total_weight.text() == '0 kg',
      w.lbl_total_weight.text())
check('失败后弹出错误提示',
      any(t == 'critical' for t, _, _ in dialog_log))


# ==================== B5 保存返回值与路径 ====================
print()
print("== B5 save_progress 返回值/失败不缓存路径 ==")
w, _ = make_window()
imported = []
w.save_progress = lambda: False
w._do_import_bom = lambda path: imported.append(path)
w._last_progress_path = Path('旧的假路径.xlsx')  # 旧实现会据此误判“已保存”
file_behavior['open'] = ('dummy_bom.xlsx', '')
question_queue[:] = [QMessageBox.Yes, QMessageBox.No]
dialog_log.clear()
w.import_bom_data()
check('保存失败时必弹继续导入确认',
      any('继续导入' in txt for _, _, txt in dialog_log), f"{dialog_log}")
check('选择否时不执行导入', imported == [], f"{imported}")

w2, _ = make_window()
with tempfile.TemporaryDirectory() as tmp:
    file_behavior['save'] = (str(Path(tmp) / 'p.xlsx'), '')
    orig_save = ProgressFileManager.save
    ProgressFileManager.save = (
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError('写盘失败')))
    dialog_log.clear()
    try:
        result = w2.save_progress()
    finally:
        ProgressFileManager.save = orig_save
    check('保存失败返回 False', result is False)
    check('保存失败不缓存路径', not getattr(w2, '_last_progress_path', None),
          repr(getattr(w2, '_last_progress_path', None)))


# ==================== B6 勾选不入栈、批量空操作 ====================
print()
print("== B6 勾选不污染撤销栈；空批量无变更 ==")
w, nodes = make_window()
w._dirty = False
stack_before = len(w._undo_stack)
item = find_item(w, nodes['a1'].uid)
item.setSelected(True)
w.tree_widget.setCurrentItem(item)
w.check_selected_items()
check('勾选不压撤销栈', len(w._undo_stack) == stack_before)
check('勾选不置 dirty', w._dirty is False)

w2, nodes2 = make_window()
check_item(w2, nodes2['b'].uid)
_set_batch_dialog(expand=None, entity=None, method=None, remark='')
w2._dirty = False
stack_before = len(w2._undo_stack)
dialog_log.clear()
w2.batch_config()
check('空批量不推快照', len(w2._undo_stack) == stack_before,
      f"after={len(w2._undo_stack)}")
check('空批量不置 dirty', w2._dirty is False)
check('空批量提示未做任何修改',
      any('未做任何修改' in txt for _, _, txt in dialog_log), f"{dialog_log}")


# ==================== B7 刷新后锚点失效 ====================
print()
print("== B7 刷新后 last_clicked_item 重置 ==")
w, nodes = make_window()
old_item = find_item(w, nodes['a'].uid)
w.last_clicked_item = old_item
w.refresh_tree()
check('refresh_tree 后锚点为 None', w.last_clicked_item is None)

new_item = find_item(w, nodes['b'].uid)
raised = None
try:
    w._check_range(old_item, new_item, True)
except Exception as e:  # noqa: BLE001 - 测试要求不抛异常
    raised = e
check('用已销毁锚点调用区间勾选不抛异常', raised is None, repr(raised))
check('终点仍被勾选', new_item.checkState(0) == Qt.Checked)


# ==================== B8 配置变更统一失效预览 ====================
print()
print("== B8 配置变更后清空旧发运单 ==")
w, nodes = make_window()
dialog_log.clear()
w.calculate()
check('前置：计算得到发运单', w.current_shipping_order is not None
      and not w.current_shipping_order.empty)

w.set_node_entity(nodes['b'], '02')
check('设置主体后发运单失效', w.current_shipping_order is None)
check('设置主体后标记未保存', w._dirty is True)
check('设置主体后预览表格清空', w.table_widget.rowCount() == 0)

w.calculate()
check('重新计算后恢复', w.current_shipping_order is not None
      and not w.current_shipping_order.empty)
w.undo()
check('撤销后发运单失效', w.current_shipping_order is None)

w.calculate()
check_item(w, nodes['b'].uid)
question_queue[:] = [QMessageBox.Yes]
w.delete_checked_nodes()
check('批量删除后发运单失效', w.current_shipping_order is None)


# ==================== B9-1 边界感知展开 ====================
print()
print("== B9-1 重新展开时边界节点后代仍隐藏 ==")
w = MainWindow()
root = _node('R', 0, '是', qty=1)
a = _node('A', 1, '是', root)
b = _node('B', 2, '否', a)
c = _node('C', 3, '是', b)
d = _node('D', 4, '否', c)
w.tree_builder.root = root
w.tree_builder.all_nodes = [root, a, b, c, d]
w.refresh_tree()

item_a = find_item(w, a.uid)
w._hide_children(item_a)
w._show_children(item_a, recursive=True)
item_b = find_item(w, b.uid)
item_c = find_item(w, c.uid)
item_d = find_item(w, d.uid)
check('边界节点 B 可见', item_b.isHidden() is False)
check('边界节点 B 可编辑', bool(item_b.flags() & Qt.ItemIsEditable))
check('边界后代 C 仍隐藏', item_c.isHidden() is True)
check('边界后代 C 不可编辑', not (item_c.flags() & Qt.ItemIsEditable))
check('边界后代 D 仍隐藏', item_d.isHidden() is True)


# ==================== B9-2 置否确认后清空子孙配置 ====================
print()
print("== B9-2 由是变否：确认清空 / 拒绝保留 ==")
def make_collapse_window():
    w = MainWindow()
    root = _node('R', 0, '是', qty=1)
    a = _node('A', 1, '是', root, qty=1)
    b = _node('B', 2, '否', a, entity='01', method='A', qty=1)
    w.tree_builder.root = root
    w.tree_builder.all_nodes = [root, a, b]
    w.refresh_tree()
    return w, a, b

w, a, b = make_collapse_window()
question_queue[:] = [QMessageBox.Yes]
dialog_log.clear()
stack_before = len(w._undo_stack)
w.set_node_entity(a, '02')
check('确认后 A 成为发运单元', a.expand_status == '否')
check('确认后 A 主体已设置', a.shipping_entity == '02')
check('确认后子孙配置被清空',
      b.shipping_entity == '' and b.shipping_method == '',
      f"B={b.shipping_entity!r}/{b.shipping_method!r}")
check('确认提交后标记未保存（P1-1）', w._dirty is True)
check('确认提交后产生 1 个撤销点', len(w._undo_stack) == stack_before + 1)

w2, a2, b2 = make_collapse_window()
question_queue[:] = [QMessageBox.No]
stack_before2 = len(w2._undo_stack)
w2.set_node_entity(a2, '02')
check('拒绝后 A 主体不变', a2.shipping_entity == '', repr(a2.shipping_entity))
check('拒绝后 A 仍为展开', a2.expand_status == '是')
check('拒绝后子孙配置保留',
      b2.shipping_entity == '01' and b2.shipping_method == 'A')
check('拒绝后不残留撤销点', len(w2._undo_stack) == stack_before2,
      f"after={len(w2._undo_stack)}")
check('拒绝后不误置 dirty', w2._dirty is False)

w3, a3, b3 = make_collapse_window()
question_queue[:] = [QMessageBox.Yes]
w3.set_node_method(a3, 'B')
check('设置方式确认后清空子孙配置',
      a3.shipping_method == 'B' and b3.shipping_entity == '')

w4, a4, b4 = make_collapse_window()
check_item(w4, a4.uid)
_set_batch_dialog(expand='否', remark='')
question_queue[:] = [QMessageBox.Yes]
dialog_log.clear()
w4.batch_config()
check('批量置否确认后清空子孙配置',
      a4.expand_status == '否' and b4.shipping_entity == '',
      f"A={a4.expand_status}, B={b4.shipping_entity!r}")


# ==================== P2-1 列编辑确认取消回滚 ====================
print()
print("== P2-1 列编辑确认框取消后不残留撤销点/dirty ==")
w5, nodes5 = make_window()
item_a5 = find_item(w5, nodes5['a'].uid)
w5._dirty = False
stack_before5 = len(w5._undo_stack)
question_queue[:] = [QMessageBox.No]
dialog_log.clear()
w5.current_shipping_order = 'SENTINEL'  # 模拟已有预览结果
item_a5.setText(6, '否')  # 触发 on_item_changed -> 确认框
check('取消时弹出确认框', any(t == 'question' for t, _, _ in dialog_log))
check('取消后展开状态不变', nodes5['a'].expand_status == '是')
check('取消后树文本回滚', item_a5.text(6) == '是')
check('取消后预览数据未被提前清空', w5.current_shipping_order == 'SENTINEL')
check('取消后不残留撤销点', len(w5._undo_stack) == stack_before5,
      f"after={len(w5._undo_stack)}")
check('取消后不误置 dirty', w5._dirty is False)
check('取消后子节点配置保留', nodes5['a1'].shipping_entity == '01')


# ==================== P1-1 closeEvent 未保存提示 ====================
print()
print("== P1-1 右键设置后关窗提示未保存 ==")
w6, nodes6 = make_window()
w6.set_node_entity(nodes6['b'], '02')  # 走 _push_undo_snapshot
check('右键设置主体后 dirty=True', w6._dirty is True)


class _FakeCloseEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


close_probe = {}


def _fake_close_exec(dlg):
    esc = dlg.escapeButton()
    close_probe['escape'] = esc.text() if esc else None
    dialog_log.append(('close_prompt', dlg.windowTitle(), dlg.text()))
    return 0


prev_exec_fn = exec_behavior['fn']
exec_behavior['fn'] = _fake_close_exec
ev = _FakeCloseEvent()
dialog_log.clear()
try:
    w6.closeEvent(ev)
finally:
    exec_behavior['fn'] = prev_exec_fn
check('关窗时弹出未保存提示',
      any(t == 'close_prompt' and '未保存' in txt
          for t, _, txt in dialog_log), f"{dialog_log}")
check('未保存且未选择保存时不直接关闭', ev.accepted is False)
check('Esc 绑定为“返回编辑”而非“不保存并退出”', close_probe.get('escape') == '返回编辑', f"{close_probe}")


def _click_close_button(text):
    """模拟用户点击关闭确认框中的指定按钮"""
    def _fn(dlg):
        for btn in dlg.buttons():
            if btn.text() == text:
                btn.click()
                return 0
        return 0
    return _fn


# 点“返回编辑”：必须留在程序内
exec_behavior['fn'] = _click_close_button('返回编辑')
ev = _FakeCloseEvent()
w6.closeEvent(ev)
check('点“返回编辑”不关闭窗口', ev.accepted is False and ev.ignored is True)

# 点“不保存并退出”：直接关闭
exec_behavior['fn'] = _click_close_button('不保存并退出')
ev = _FakeCloseEvent()
w6.closeEvent(ev)
check('点“不保存并退出”关闭窗口', ev.accepted is True)

# 点“保存并退出”但保存被取消/失败：留在程序内
exec_behavior['fn'] = _click_close_button('保存并退出')
w6.save_progress = lambda: False
ev = _FakeCloseEvent()
w6.closeEvent(ev)
check('保存失败或取消时不关闭', ev.accepted is False and ev.ignored is True)

# 点“保存并退出”且保存成功：关闭
exec_behavior['fn'] = _click_close_button('保存并退出')
w6.save_progress = lambda: True
ev = _FakeCloseEvent()
w6.closeEvent(ev)
check('保存成功后关闭', ev.accepted is True)
exec_behavior['fn'] = prev_exec_fn


# ==================== 循环引用防护 ====================
print()
print("== 循环引用防护 ==")
cy_a = BOMNode(material_id='CY-A', parent_id='CY-B', level=1)
cy_b = BOMNode(material_id='CY-B', parent_id='CY-A', level=1)
cy_a.add_child(cy_b)
cy_b.add_child(cy_a)  # 人为构造互为父子
tb_cycle = w6.tree_builder.__class__()
tb_cycle.all_nodes = [cy_a, cy_b]
try:
    tb_cycle._raise_on_parent_cycles()
    check('循环引用被检测', False, '未抛出异常')
except ValueError as e:
    check('循环引用被检测', '循环引用' in str(e), str(e))
tb_cycle._recompute_subtree(cy_a)  # 带 visited 防护，不应无限递归
check('循环子树重算可终止', True)


# ==================== 多根文件提示 ====================
print()
print("== 多根文件提示 ==")
tb_multi = w6.tree_builder.__class__()
df_multi = pd.DataFrame([
    {'子物料号': 'MR1', '父物料号': '', '数量': 1, '子物料净重': 0, 'level': 0},
    {'子物料号': 'MR2', '父物料号': '', '数量': 1, '子物料净重': 0, 'level': 0},
])
tb_multi.build_from_dataframe(df_multi)
issues_multi = tb_multi.validate_structure()
check('多根被检测并说明只处理第一个',
      any('仅处理第一个顶级节点' in s and '一个文件只能包含一个顶层产品' in s
          for s in issues_multi), f'{issues_multi}')


print()
print(f"总计: {passed + failed} 项, 通过 {passed}, 失败 {failed}")
sys.exit(1 if failed else 0)
