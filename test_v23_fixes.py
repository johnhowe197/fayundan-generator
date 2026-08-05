# -*- coding: utf-8 -*-
"""
v2.3 修复针对性回归测试

验证 2026-07-22 审查报告中的两个打包阻塞 P0 及撤销系统重建的关键行为：
- P0-2：发运主体名"双前缀"（get_entity_display_name 应返回单前缀）
- P0-1：配置/日志可写目录解析与出厂配置播种
- 撤销系统：uid 唯一性、快照键、幽灵节点清理、跨数据集清栈

补充说明：pre_commit_verify.py 只检查符号存在性，无法发现上述值格式/路径类
缺陷，故本文件作为针对性的行为级回归测试。

用法：python test_v23_fixes.py
"""
import sys
import tempfile
from pathlib import Path

# 确保能导入项目模块
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


# ============ P0-2：发运主体名双前缀 ============
print("== P0-2 发运主体名双前缀 ==")
from core.entity_config import EntityConfigManager
from models.bom_node import get_entity_name, get_entity_display_name

# 模拟全新进程：清空类级缓存，强制走懒加载默认路径
EntityConfigManager._cached_entity_map = None
disp = EntityConfigManager.get_entity_display_name('01')
check("get_entity_display_name('01') 返回单前缀", disp == '01-机头', f"实际={disp!r}")
name = EntityConfigManager.get_entity_name('01')
check("get_entity_name('01') 返回纯名称", name == '机头', f"实际={name!r}")

# 静态缓存值应为不带前缀的纯名称（契约统一）
EntityConfigManager._cached_entity_map = None
m = EntityConfigManager.get_static_entity_map()
check("静态缓存值为纯名称（无前缀）", m.get('01') == '机头', f"实际={m.get('01')!r}")

# 委托函数同样正确
check("bom_node.get_entity_display_name('98')", get_entity_display_name('98') == '98-捆装发运类',
      f"实际={get_entity_display_name('98')!r}")
check("bom_node.get_entity_name('98')", get_entity_name('98') == '捆装发运类',
      f"实际={get_entity_name('98')!r}")

# 含前缀入参的幂等性
check("含前缀入参不重复加前缀", EntityConfigManager.get_entity_display_name('01-机头') == '01-机头',
      f"实际={EntityConfigManager.get_entity_display_name('01-机头')!r}")


# ============ P0-1：可写目录与播种 ============
print("== P0-1 配置可写目录与播种 ==")
from utils.helpers import get_writable_app_dir, get_bundle_dir, is_frozen, seed_file_from_bundle

check("开发环境判定为非 frozen", is_frozen() is False)
wdir = get_writable_app_dir()
check("可写应用目录存在", wdir.exists(), str(wdir))
check("开发环境可写目录==项目根目录", wdir == Path(__file__).parent, f"{wdir} vs {Path(__file__).parent}")
check("开发环境只读资源目录==项目根目录", get_bundle_dir() == Path(__file__).parent)

# 播种逻辑：目标缺失则复制；目标存在则不覆盖（保护用户数据）
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    bundle = td / 'bundle.json'
    bundle.write_text('出厂默认', encoding='utf-8')
    target = td / 'sub' / 'target.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    seed_file_from_bundle(bundle, target)
    check("播种：目标缺失时从资源目录复制",
          target.exists() and target.read_text(encoding='utf-8') == '出厂默认')
    target.write_text('用户自定义', encoding='utf-8')
    seed_file_from_bundle(bundle, target)
    check("播种：目标已存在时不覆盖", target.read_text(encoding='utf-8') == '用户自定义')

# EntityConfigManager 默认配置目录应落在可写应用目录下
mgr = EntityConfigManager()
check("配置目录位于可写应用目录下", mgr.config_dir == get_writable_app_dir() / 'config',
      str(mgr.config_dir))


# ============ 撤销系统：uid 唯一性 ============
print("== 撤销系统 uid 唯一性 ==")
from models.bom_node import BOMNode

n1 = BOMNode(material_id='M1', parent_id='P')
n2 = BOMNode(material_id='M1', parent_id='P')  # 同父同物料（拆分/多实例场景）
check("同父同物料的两个节点 uid 不同", n1.uid != n2.uid, f"{n1.uid} vs {n2.uid}")
check("uid 自动分配为正整数", n1.uid > 0 and n2.uid > 0)

# 从快照回填旧 uid：保持原值，且计数器领先避免后续冲突
old_uid = n1.uid
n3 = BOMNode(material_id='M2', parent_id='P', uid=old_uid)
check("回填的 uid 被保留", n3.uid == old_uid)
n4 = BOMNode(material_id='M3', parent_id='P')
check("回填后自动分配的 uid 不回退冲突", n4.uid != old_uid and n4.uid > old_uid,
      f"{n4.uid} vs {old_uid}")


# ============ 撤销系统：快照键 / 幽灵清理 / 清栈 ============
print("== 撤销系统快照与恢复 ==")
from ui.undo_mixin import UndoMixin
from core.tree_builder import TreeBuilder


class FakeButton:
    def __init__(self):
        self.enabled = False

    def setEnabled(self, v):
        self.enabled = v


class FakeStatusBar:
    """状态栏桩：记录 showMessage 内容"""
    def __init__(self):
        self.message = ''

    def showMessage(self, msg, *args):
        self.message = msg


class FakeWindow(UndoMixin):
    """无 Qt 依赖的最小宿主，仅驱动撤销逻辑"""
    def __init__(self):
        self.tree_builder = TreeBuilder()
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo = 5
        self._dirty = False
        self.btn_undo = FakeButton()
        self.btn_redo = FakeButton()
        self._fake_status_bar = FakeStatusBar()

    def statusBar(self):
        return self._fake_status_bar

    def refresh_tree(self, preserve_expand_state=False):
        pass

    def update_status_bar(self):
        pass

    def _update_title(self):
        pass


check("UndoMixin._node_key 使用稳定 uid", UndoMixin._node_key(n1) == n1.uid)

# 幽灵节点清理：撤销"添加物料"后，被添加节点应被移出 all_nodes
w = FakeWindow()
root = BOMNode(material_id='ROOT', parent_id='', level=0)
w.tree_builder.root = root
w.tree_builder.all_nodes.append(root)
w._save_state()                       # 快照：仅含 root
added = BOMNode(material_id='ADD', parent_id='ROOT', level=1)
root.add_child(added)
w.tree_builder.all_nodes.append(added)
check("添加后 all_nodes 含 2 个节点", len(w.tree_builder.all_nodes) == 2)
w.undo()                              # 恢复到仅含 root 的快照
check("撤销添加后幽灵节点被清理", len(w.tree_builder.all_nodes) == 1,
      f"剩余={len(w.tree_builder.all_nodes)}")
check("撤销后保留 root 节点", w.tree_builder.all_nodes[0].material_id == 'ROOT')

# 撤销属性修改：修改后撤销应还原
w2 = FakeWindow()
r2 = BOMNode(material_id='ROOT', parent_id='', level=0)
w2.tree_builder.root = r2
w2.tree_builder.all_nodes.append(r2)
w2._save_state()
r2.remark = '已修改'
w2._save_state()
r2.remark = '再修改'
w2.undo()
check("撤销属性修改可还原", r2.remark == '已修改', f"实际={r2.remark!r}")

# 跨数据集清栈
w._save_state()
w._save_state()
check("清栈前存在撤销历史", len(w._undo_stack) > 0)
w._clear_undo_redo()
check("清栈后撤销/恢复栈均空", len(w._undo_stack) == 0 and len(w._redo_stack) == 0)
check("清栈后撤销/恢复按钮禁用", w.btn_undo.enabled is False and w.btn_redo.enabled is False)


# ============ 撤销：选择发运主体可撤销（Qt offscreen 行为级） ============
# 回归 QA 发现的 P1：_set_item_value 曾先改 node 再 setText，导致选择发运主体/方式
# 这一高频操作的快照是"改后"状态、永远撤不回。此处用真实信号链路验证修复。
print("== 撤销：选择发运主体可撤销（Qt offscreen） ==")
try:
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication, QTreeWidgetItem
    from PyQt5.QtCore import Qt as _Qt
    _app = QApplication.instance() or QApplication([])
    from ui.main_window import MainWindow
    from models.bom_node import BOMNode as _BOMNode

    _w = MainWindow()
    _root = _BOMNode(material_id='ROOT', parent_id='', level=0)
    _child = _BOMNode(material_id='C1', parent_id='ROOT', level=1)
    _root.add_child(_child)
    _w.tree_builder.root = _root
    _w.tree_builder.all_nodes = [_root, _child]

    # 构建一个承载 _child 的树项（blockSignals 避免初始化阶段误触发快照）
    _w.tree_widget.blockSignals(True)
    _item = QTreeWidgetItem(_w.tree_widget)
    _item.setData(1, _Qt.UserRole, _child)
    _item.setText(7, '')
    _w.tree_widget.blockSignals(False)

    # 经真实信号链路选择发运主体 01
    _w._set_item_value(_item, 7, '01-机头')
    check("选择发运主体后节点已更新为 01", _child.shipping_entity == '01',
          f"实际={_child.shipping_entity!r}")
    # 撤销应还原到选择前的空值
    _w.undo()
    check("撤销后节点发运主体还原为空", _child.shipping_entity == '',
          f"实际={_child.shipping_entity!r}")
except Exception as e:
    check("Qt offscreen 撤销行为测试可执行", False, f"异常: {type(e).__name__}: {e}")


print("\n" + "=" * 50)
print(f"通过 {passed}，失败 {failed}")
if failed:
    print("存在失败项！")
    sys.exit(1)
print("全部通过")
