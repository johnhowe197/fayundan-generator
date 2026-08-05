"""
主窗口模块

应用程序的主窗口，包含：
- 工具栏
- BOM树结构视图
- 发运单预览表格
- 状态栏
"""

import sys
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTreeWidget, QTreeWidgetItem,
                             QTableWidget, QTableWidgetItem, QFileDialog,
                             QMessageBox, QSplitter, QGroupBox, QStatusBar,
                             QHeaderView, QDialog, QDialogButtonBox,
                             QFormLayout, QLabel, QLineEdit, QComboBox,
                             QMenu, QAction, QInputDialog)
from PyQt5.QtCore import Qt, QSize, QEvent
from PyQt5.QtGui import QIcon, QFont, QColor, QTextOption

from models.bom_node import BOMNode, ExpandStatus, get_entity_name, update_entity_name_map
from core.tree_builder import TreeBuilder
from core.calculator import ShippingCalculator
from core.exporter import ShippingExporter
from core.bom_parser import BOMParser
from core.entity_config import EntityConfigManager
from ui.config_dialog import ConfigDialog
from PyQt5.QtWidgets import QStyledItemDelegate, QPlainTextEdit

# 导入所有 Mixin
from ui.tree_mixin import TreeMixin
from ui.config_mixin import ConfigMixin
from ui.batch_mixin import BatchMixin
from ui.undo_mixin import UndoMixin
from ui.progress_mixin import ProgressMixin
from ui.preview_mixin import PreviewMixin
from ui.entity_mixin import EntityMixin


class ComboBoxDelegate(QStyledItemDelegate):
    """下拉框代理"""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(self.items)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.DisplayRole)
        if value:
            for item in self.items:
                if item == value:
                    editor.setCurrentText(item)
                    return
                if item.startswith(value + '-') or value.startswith(item):
                    editor.setCurrentText(item)
                    return
            editor.setCurrentText(value)
        else:
            editor.setCurrentText('')

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)

    def paint(self, painter, option, index):
        painter.save()
        painter.fillRect(option.rect, QColor(240, 246, 255))
        super().paint(painter, option, index)
        painter.restore()


class EditableColumnDelegate(QStyledItemDelegate):
    """可编辑列代理 - 浅色背景区分"""

    def paint(self, painter, option, index):
        painter.save()
        painter.fillRect(option.rect, QColor(240, 246, 255))
        super().paint(painter, option, index)
        painter.restore()


class PlainTextEditDelegate(QStyledItemDelegate):
    """多行文本编辑代理（支持粘贴多行文本）"""

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setWordWrapMode(QTextOption.WrapAnywhere)
        editor.setMinimumHeight(60)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.DisplayRole) or ''
        editor.setPlainText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class MainWindow(QMainWindow, TreeMixin, ConfigMixin, BatchMixin,
                 UndoMixin, ProgressMixin, PreviewMixin, EntityMixin):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.tree_builder = TreeBuilder()
        self.calculator = None
        self.exporter = ShippingExporter()
        self.current_shipping_order = None
        self._current_file = None
        self._dirty = False
        self.entity_map = self._load_entity_map()
        self._undo_stack = []
        self._redo_stack = []
        # 撤销深度 30：实测 5000 节点的树单个快照约 0.5MB，30 步约 16MB，可接受。
        # 旧值 5 太浅：事故（如误粘贴导致树塌缩）后用户尝试自救的每一步操作
        # 都会把事故前的快照挤出栈外，导致撤销永远回不到事故前状态。
        self._max_undo = 30
        self.init_ui()

    def closeEvent(self, event):
        """关闭窗口时检查未保存"""
        if self._dirty:
            msg = QMessageBox(self)
            msg.setWindowTitle('确认退出')
            msg.setText('当前有未保存的修改，确定要退出吗？')
            msg.setIcon(QMessageBox.Question)
            btn_save = msg.addButton('保存', QMessageBox.AcceptRole)
            btn_discard = msg.addButton('不保存', QMessageBox.RejectRole)
            btn_cancel = msg.addButton('取消', QMessageBox.NoRole)
            msg.setDefaultButton(btn_save)
            msg.exec_()
            clicked = msg.clickedButton()
            if clicked == btn_save:
                # 仅在保存确实成功后才退出；用户取消或保存失败则留在程序内，
                # 避免未保存就退出导致数据丢失
                if self.save_progress():
                    event.accept()
                else:
                    event.ignore()
            elif clicked == btn_discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def _get_all_entity_codes(self):
        """获取所有发运主体代码"""
        if hasattr(self, 'entity_map') and self.entity_map:
            return sorted(self.entity_map.keys())
        return ['00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10',
                '90', '91', '96', '98', '99']

    def _load_entity_map(self):
        """加载实体映射"""
        entity_mgr = EntityConfigManager()
        return entity_mgr.get_entity_map()

    def _get_entity_display_name(self, entity_code):
        """获取发运主体显示名称"""
        if not entity_code:
            return ''
        code = entity_code.split('-')[0] if '-' in entity_code else entity_code
        if hasattr(self, 'entity_map') and code in self.entity_map:
            return self.entity_map[code]
        from models.bom_node import get_entity_display_name
        return get_entity_display_name(code)

    def _get_method_display_name(self, method_code):
        """获取发运方式显示名称"""
        if not method_code:
            return ''
        if '-' in method_code:
            return method_code
        method_map = {'A': 'A-散装', 'B': 'B-打捆', 'C': 'C-装箱', 'D': 'D-特殊'}
        return method_map.get(method_code, method_code)

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle('发运单生成器')
        self.setGeometry(100, 100, 1500, 900)
        self.setMinimumSize(1200, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        self.create_toolbar(main_layout)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = self.create_tree_panel()
        splitter.addWidget(left_widget)

        right_widget = self.create_preview_panel()
        splitter.addWidget(right_widget)

        splitter.setSizes([500, 900])

        main_layout.addWidget(splitter)

        self.create_status_bar()

        self.apply_styles()

    def eventFilter(self, obj, event):
        """事件过滤器"""
        if obj == self.tree_widget.viewport() and event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                item = self.tree_widget.itemAt(event.pos())
                if item:
                    column = self.tree_widget.columnAt(event.pos().x())
                    if column in [1, 2, 3, 4, 5, 10]:
                        if item.isExpanded():
                            self.tree_widget.collapseItem(item)
                        else:
                            self.tree_widget.expandItem(item)
                        return True
                    if column in [6, 7, 8]:
                        return True

        if obj == self.tree_widget.viewport() and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                item = self.tree_widget.itemAt(event.pos())
                if item:
                    column = self.tree_widget.columnAt(event.pos().x())

                    if column in [6, 7, 8]:
                        node = item.data(1, Qt.UserRole)
                        if node and not self._is_node_hidden(node):
                            global_pos = self.tree_widget.viewport().mapToGlobal(event.pos())
                            self._show_selection_menu(item, column, global_pos)
                            return True

                    if column == 0:
                        item_rect = self.tree_widget.visualItemRect(item)
                        click_x = event.pos().x()
                        # 用当前样式动态定位复选框指示器的真实区域（Fusion 下约在项左侧），
                        # 替代硬编码命中区 (20,45)——原硬编码与指示器错位，导致点复选框本身
                        # 不触发"勾选子节点自动取消祖先"的父子联动
                        from PyQt5.QtWidgets import QStyleOptionViewItem, QStyle
                        opt = QStyleOptionViewItem()
                        opt.rect = item_rect
                        opt.state = QStyle.State_Enabled | QStyle.State_Item
                        opt.checkState = item.checkState(0)
                        # 必须声明 HasCheckIndicator 特征位，否则 Fusion 等样式下
                        # subElementRect 恒返回空矩形，导致动态定位失效、只能靠回退分支
                        opt.features = QStyleOptionViewItem.HasCheckIndicator
                        indicator = self.tree_widget.style().subElementRect(
                            QStyle.SE_ItemViewItemCheckIndicator, opt, self.tree_widget)
                        if indicator.isValid() and indicator.width() > 0:
                            in_checkbox = (indicator.left() - 2 <= click_x <= indicator.right() + 4)
                        else:
                            # 回退：项左侧区域视为复选框
                            in_checkbox = 0 < (click_x - item_rect.left()) < 28

                        if in_checkbox:
                            modifiers = event.modifiers()

                            if modifiers & Qt.ShiftModifier:
                                if self.last_clicked_item:
                                    self._check_range(self.last_clicked_item, item, True)
                                else:
                                    item.setCheckState(0, Qt.Checked)
                                    self._uncheck_ancestors(item)
                            elif modifiers & Qt.ControlModifier:
                                current_state = item.checkState(0)
                                new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
                                item.setCheckState(0, new_state)
                                if new_state == Qt.Checked:
                                    self._uncheck_ancestors(item)
                            else:
                                current_state = item.checkState(0)
                                new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
                                item.setCheckState(0, new_state)
                                if new_state == Qt.Checked:
                                    self._uncheck_ancestors(item)

                            self.last_clicked_item = item
                            self.update_status_bar()
                            return True

        # Ctrl+滚轮：缩放树控件字体
        if obj == self.tree_widget.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                current_size = self.tree_widget.font().pointSize()
                if delta > 0:
                    new_size = min(30, current_size + 1)
                else:
                    new_size = max(6, current_size - 1)
                font = QFont("Microsoft YaHei", new_size)
                self.tree_widget.setFont(font)
                self.statusBar().showMessage(f'树字体: {new_size}pt', 2000)
                event.accept()
                return True

        return False

    def create_toolbar(self, parent_layout):
        """创建工具栏"""
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(5)

        self.btn_import_bom = QPushButton('📂 导入BOM')
        self.btn_import_bom.setMinimumHeight(35)
        self.btn_import_bom.setToolTip('导入多级BOM数据文件')
        self.btn_import_bom.clicked.connect(self.import_bom_data)
        toolbar_layout.addWidget(self.btn_import_bom)

        separator = QLabel('|')
        separator.setStyleSheet("color: #ccc; font-size: 20px;")
        toolbar_layout.addWidget(separator)

        self.btn_batch_config = QPushButton('📋 批量设置')
        self.btn_batch_config.setMinimumHeight(35)
        self.btn_batch_config.setToolTip('批量设置勾选节点的发运配置 (F1)')
        self.btn_batch_config.clicked.connect(self.batch_config)
        toolbar_layout.addWidget(self.btn_batch_config)

        self.btn_delete_checked = QPushButton('🗑️ 删除勾选')
        self.btn_delete_checked.setMinimumHeight(35)
        self.btn_delete_checked.setToolTip('删除所有勾选的节点 (Delete)')
        self.btn_delete_checked.clicked.connect(self.delete_checked_nodes)
        toolbar_layout.addWidget(self.btn_delete_checked)

        separator1 = QLabel('|')
        separator1.setStyleSheet("color: #ccc; font-size: 20px;")
        toolbar_layout.addWidget(separator1)

        self.btn_check_selected = QPushButton('✅ 勾选选中')
        self.btn_check_selected.setMinimumHeight(35)
        self.btn_check_selected.setToolTip('对光标选中的行进行勾选 (F2)')
        self.btn_check_selected.clicked.connect(self.check_selected_items)
        toolbar_layout.addWidget(self.btn_check_selected)

        self.btn_uncheck_selected = QPushButton('❎ 取消选中')
        self.btn_uncheck_selected.setMinimumHeight(35)
        self.btn_uncheck_selected.setToolTip('取消光标选中行的勾选 (F3)')
        self.btn_uncheck_selected.clicked.connect(self.uncheck_selected_items)
        toolbar_layout.addWidget(self.btn_uncheck_selected)

        separator2 = QLabel('|')
        separator2.setStyleSheet("color: #ccc; font-size: 20px;")
        toolbar_layout.addWidget(separator2)

        self.btn_calculate = QPushButton('🔢 计算')
        self.btn_calculate.setMinimumHeight(35)
        self.btn_calculate.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_calculate.clicked.connect(self.calculate)
        toolbar_layout.addWidget(self.btn_calculate)

        self.btn_preview = QPushButton('👁️ 预览')
        self.btn_preview.setMinimumHeight(35)
        self.btn_preview.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.btn_preview.clicked.connect(self.show_preview)
        toolbar_layout.addWidget(self.btn_preview)

        self.btn_validate = QPushButton('✅ 检验')
        self.btn_validate.setMinimumHeight(35)
        self.btn_validate.setStyleSheet("background-color: #E91E63; color: white; font-weight: bold;")
        self.btn_validate.setToolTip('检验所有层级是否维护完毕')
        self.btn_validate.clicked.connect(self.validate_config)
        toolbar_layout.addWidget(self.btn_validate)

        separator3 = QLabel('|')
        separator3.setStyleSheet("color: #ccc; font-size: 20px;")
        toolbar_layout.addWidget(separator3)

        self.btn_export_excel = QPushButton('📊 导出Excel')
        self.btn_export_excel.setMinimumHeight(35)
        self.btn_export_excel.clicked.connect(self.export_excel)
        toolbar_layout.addWidget(self.btn_export_excel)

        self.btn_export_csv = QPushButton('📄 导出CSV')
        self.btn_export_csv.setMinimumHeight(35)
        self.btn_export_csv.clicked.connect(self.export_csv)
        toolbar_layout.addWidget(self.btn_export_csv)

        toolbar_layout.addStretch()

        parent_layout.addLayout(toolbar_layout)

        # 第二行工具栏（进度管理）
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(5)

        progress_label = QLabel('进度管理:')
        progress_label.setStyleSheet("font-weight: bold; color: #333;")
        progress_layout.addWidget(progress_label)

        self.btn_save_progress = QPushButton('💾 保存')
        self.btn_save_progress.setMinimumHeight(25)
        self.btn_save_progress.setMaximumWidth(80)
        self.btn_save_progress.setStyleSheet("background-color: #FF9800; color: white; font-size: 11px;")
        self.btn_save_progress.setToolTip('保存当前工作进度 (Ctrl+S)')
        self.btn_save_progress.clicked.connect(self.save_progress)
        progress_layout.addWidget(self.btn_save_progress)

        self.btn_load_progress = QPushButton('📂 加载')
        self.btn_load_progress.setMinimumHeight(25)
        self.btn_load_progress.setMaximumWidth(80)
        self.btn_load_progress.setStyleSheet("background-color: #9C27B0; color: white; font-size: 11px;")
        self.btn_load_progress.setToolTip('加载之前保存的工作进度')
        self.btn_load_progress.clicked.connect(self.load_progress)
        progress_layout.addWidget(self.btn_load_progress)

        separator_undo = QLabel('|')
        separator_undo.setStyleSheet("color: #ccc; font-size: 15px;")
        progress_layout.addWidget(separator_undo)

        self.btn_undo = QPushButton('↩️ 撤销')
        self.btn_undo.setMinimumHeight(25)
        self.btn_undo.setMinimumWidth(70)
        self.btn_undo.setToolTip('撤销上一步操作 (Ctrl+Z)')
        self.btn_undo.clicked.connect(self.undo)
        self.btn_undo.setEnabled(False)
        progress_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton('↪️ 恢复')
        self.btn_redo.setMinimumHeight(25)
        self.btn_redo.setMinimumWidth(70)
        self.btn_redo.setToolTip('恢复上一步撤销 (Ctrl+Y)')
        self.btn_redo.clicked.connect(self.redo)
        self.btn_redo.setEnabled(False)
        progress_layout.addWidget(self.btn_redo)

        separator_progress = QLabel('|')
        separator_progress.setStyleSheet("color: #ccc; font-size: 15px;")
        progress_layout.addWidget(separator_progress)

        self.btn_entity_def = QPushButton('🏷️ 发运主体')
        self.btn_entity_def.setMinimumHeight(25)
        self.btn_entity_def.setMaximumWidth(100)
        self.btn_entity_def.setStyleSheet("font-size: 11px;")
        self.btn_entity_def.setToolTip('查看/编辑发运主体定义')
        self.btn_entity_def.clicked.connect(self.show_entity_definition)
        progress_layout.addWidget(self.btn_entity_def)

        self.btn_custom_config = QPushButton('⚡ F4快捷')
        self.btn_custom_config.setMinimumHeight(25)
        self.btn_custom_config.setMaximumWidth(80)
        self.btn_custom_config.setStyleSheet("font-size: 11px;")
        self.btn_custom_config.setToolTip('定义并应用自定义发运配置 (F4)')
        self.btn_custom_config.clicked.connect(self._on_custom_config_btn)
        progress_layout.addWidget(self.btn_custom_config)

        separator_f4 = QLabel('|')
        separator_f4.setStyleSheet("color: #ccc; font-size: 15px;")
        progress_layout.addWidget(separator_f4)

        self.btn_expand_all = QPushButton('▼ 全部展开')
        self.btn_expand_all.setMinimumHeight(25)
        self.btn_expand_all.setMaximumWidth(100)
        self.btn_expand_all.setStyleSheet("font-size: 11px;")
        self.btn_expand_all.setToolTip('展开所有节点')
        self.btn_expand_all.clicked.connect(lambda: self.tree_widget.expandAll())
        progress_layout.addWidget(self.btn_expand_all)

        self.btn_collapse_all = QPushButton('▶ 全部折叠')
        self.btn_collapse_all.setMinimumHeight(25)
        self.btn_collapse_all.setMaximumWidth(100)
        self.btn_collapse_all.setStyleSheet("font-size: 11px;")
        self.btn_collapse_all.setToolTip('折叠所有节点')
        self.btn_collapse_all.clicked.connect(lambda: self.tree_widget.collapseAll())
        progress_layout.addWidget(self.btn_collapse_all)

        progress_layout.addStretch()

        parent_layout.addLayout(progress_layout)

    def create_tree_panel(self) -> QWidget:
        """创建BOM树结构面板"""
        group = QGroupBox("BOM树结构")
        layout = QVBoxLayout()

        hint_label = QLabel('提示: 点击"是否展开"、"发运主体"、"发运方式"列可直接选择')
        hint_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint_label)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(['选择', '物料号', '名称', '图号', '规格', '数量', '是否展开', '发运主体', '发运方式', '备注', '状态'])
        self.tree_widget.setColumnWidth(0, 120)
        self.tree_widget.setColumnWidth(1, 150)
        self.tree_widget.setColumnWidth(2, 200)
        self.tree_widget.setColumnWidth(3, 150)
        self.tree_widget.setColumnWidth(4, 120)
        self.tree_widget.setColumnWidth(5, 60)
        self.tree_widget.setColumnWidth(6, 70)
        self.tree_widget.setColumnWidth(7, 100)
        self.tree_widget.setColumnWidth(8, 70)
        self.tree_widget.setColumnWidth(9, 100)
        self.tree_widget.setColumnWidth(10, 70)
        self.tree_widget.setAlternatingRowColors(False)

        from PyQt5.QtGui import QPalette
        pal = self.tree_widget.palette()
        pal.setColor(QPalette.Base, Qt.white)
        pal.setColor(QPalette.AlternateBase, Qt.white)
        self.tree_widget.setPalette(pal)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree_widget.itemChanged.connect(self.on_item_changed)

        self.tree_widget.setEditTriggers(QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed)
        self.tree_widget.setSelectionMode(QTreeWidget.ExtendedSelection)

        self.last_clicked_item = None

        expand_delegate = ComboBoxDelegate(['是', '否'], self.tree_widget)
        self.tree_widget.setItemDelegateForColumn(6, expand_delegate)

        entity_items = [''] + [self._get_entity_display_name(e) for e in self._get_all_entity_codes()]
        self.entity_delegate = ComboBoxDelegate(entity_items, self.tree_widget)
        self.tree_widget.setItemDelegateForColumn(7, self.entity_delegate)

        method_delegate = ComboBoxDelegate(['', 'A-散装', 'B-打捆', 'C-装箱', 'D-特殊'], self.tree_widget)
        self.tree_widget.setItemDelegateForColumn(8, method_delegate)

        remark_delegate = EditableColumnDelegate(self.tree_widget)
        self.tree_widget.setItemDelegateForColumn(9, remark_delegate)

        self.tree_widget.viewport().installEventFilter(self)

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence.Redo, self, self.redo)
        QShortcut(QKeySequence('F1'), self, self.batch_config)
        QShortcut(QKeySequence('F2'), self, self.check_selected_items)
        QShortcut(QKeySequence('F3'), self, self.uncheck_selected_items)
        QShortcut(QKeySequence('F4'), self, self._apply_custom_config)
        QShortcut(QKeySequence('F5'), self, lambda: self._quick_apply_entity('98', 'B'))
        QShortcut(QKeySequence('F6'), self, lambda: self._quick_apply_entity('99', 'C'))
        # Y/N 快捷设置展开：限定为树控件获得焦点时生效，避免劫持"项目名称"等
        # 文本输入框里的 y/n 字符（默认 WindowShortcut 上下文会全局拦截字母键）
        _y_shortcut = QShortcut(QKeySequence('Y'), self.tree_widget, lambda: self._quick_set_expand('是'))
        _y_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        _n_shortcut = QShortcut(QKeySequence('N'), self.tree_widget, lambda: self._quick_set_expand('否'))
        _n_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence('Delete'), self, self._delete_key_handler)
        QShortcut(QKeySequence.Save, self, self.save_progress)
        QShortcut(QKeySequence('Ctrl+Shift+C'), self, self._shortcut_copy_format)
        QShortcut(QKeySequence('Ctrl+Shift+V'), self, self._paste_format_to_checked)

        self._clipboard_config = None
        self._custom_config = {'shipping_entity': '', 'shipping_method': ''}

        layout.addWidget(self.tree_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_refresh = QPushButton('刷新')
        btn_refresh.clicked.connect(self.refresh_tree)
        btn_layout.addWidget(btn_refresh)

        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def create_preview_panel(self) -> QWidget:
        """创建发运单预览面板"""
        self.preview_group = QGroupBox("发运单预览")
        layout = QVBoxLayout()

        info_label = QLabel('发运说明：A:散装发运；B:打捆发运；C:装箱发运；D:特殊发运。')
        info_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(info_label)

        project_layout = QHBoxLayout()

        project_layout.addWidget(QLabel('项目名称:'))
        self.edit_project_name = QLineEdit()
        self.edit_project_name.setPlaceholderText('请输入项目名称')
        self.edit_project_name.setMaximumWidth(200)
        project_layout.addWidget(self.edit_project_name)

        project_layout.addWidget(QLabel('项目图号:'))
        self.edit_project_drawing = QLineEdit()
        self.edit_project_drawing.setPlaceholderText('请输入项目图号')
        self.edit_project_drawing.setMaximumWidth(150)
        project_layout.addWidget(self.edit_project_drawing)

        project_layout.addWidget(QLabel('施工号:'))
        self.edit_project_construction = QLineEdit()
        self.edit_project_construction.setPlaceholderText('请输入施工号')
        self.edit_project_construction.setMaximumWidth(150)
        project_layout.addWidget(self.edit_project_construction)

        project_layout.addWidget(QLabel('制作:'))
        self.edit_maker = QLineEdit()
        self.edit_maker.setPlaceholderText('制作人')
        self.edit_maker.setMaximumWidth(100)
        project_layout.addWidget(self.edit_maker)

        project_layout.addWidget(QLabel('审核:'))
        self.edit_reviewer = QLineEdit()
        self.edit_reviewer.setPlaceholderText('审核人')
        self.edit_reviewer.setMaximumWidth(100)
        project_layout.addWidget(self.edit_reviewer)

        project_layout.addWidget(QLabel('总重:'))
        self.lbl_total_weight = QLabel('0 kg')
        self.lbl_total_weight.setStyleSheet("font-weight: bold; color: #333; background-color: #f0f0f0; padding: 2px 8px; border: 1px solid #ccc;")
        self.lbl_total_weight.setMinimumWidth(120)
        project_layout.addWidget(self.lbl_total_weight)

        layout.addLayout(project_layout)

        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(11)
        self.table_widget.setHorizontalHeaderLabels([
            '序号', '物料号', '图号', '规格', '名称', '数量', '净重', '总重(kg)', '发运类型', '发运主体', '备注'
        ])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_widget.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.table_widget)

        bottom_layout = QHBoxLayout()
        self.lbl_stats = QLabel("共 0 条记录")
        self.lbl_stats.setStyleSheet("color: #666; padding: 5px;")
        bottom_layout.addWidget(self.lbl_stats)

        bottom_layout.addStretch()

        btn_close_preview = QPushButton('关闭预览')
        btn_close_preview.clicked.connect(self.close_preview)
        bottom_layout.addWidget(btn_close_preview)

        layout.addLayout(bottom_layout)

        self.preview_group.setLayout(layout)
        self.preview_group.setVisible(False)

        return self.preview_group

    def create_status_bar(self):
        """创建状态栏"""
        self.statusBar().showMessage('就绪')

        self.lbl_data_count = QLabel('数据: 0 条')
        self.lbl_config_count = QLabel('已配置: 0 个')
        self.lbl_shipping_units = QLabel('发运单元: 0 个')

        self.statusBar().addPermanentWidget(self.lbl_data_count)
        self.statusBar().addPermanentWidget(self.lbl_config_count)
        self.statusBar().addPermanentWidget(self.lbl_shipping_units)

    def apply_styles(self):
        """应用样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                padding: 5px 15px;
                border: 1px solid #ddd;
                border-radius: 3px;
                background-color: white;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QTreeWidget, QTableWidget {
                border: 1px solid #ddd;
                border-radius: 3px;
                gridline-color: #e0e0e0;
            }
            QTreeWidget::item:selected, QTableWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                border: 1px solid #ddd;
                border-right: 1px solid #ccc;
                padding: 5px;
                font-weight: bold;
            }
        """)

    def on_item_double_clicked(self, item, column):
        """双击项目事件"""
        if column not in (0, 9):
            if item.isExpanded():
                self.tree_widget.collapseItem(item)
            else:
                self.tree_widget.expandItem(item)

    def edit_tree_node(self, item):
        """编辑树节点配置"""
        if not item:
            return
        node = item.data(1, Qt.UserRole)
        if not node:
            return
        # 编辑前捕获快照（不压栈），仅在用户确认修改后才推入撤销栈，
        # 避免取消编辑产生无意义撤销点；并标记未保存
        snapshot = self._save_state_snapshot()
        dialog = ConfigDialog(node, self)
        if dialog.exec_() == QDialog.Accepted:
            self._push_undo_snapshot(snapshot)
            self._dirty = True
            self._update_title()
            self.refresh_tree()
            self.update_status_bar()

    def show_empty_area_context_menu(self, pos):
        """显示空白区域右键菜单"""
        menu = QMenu(self)
        add_action = menu.addAction('添加物料行')
        add_action.triggered.connect(self.add_material_row)
        menu.exec_(self.tree_widget.mapToGlobal(pos))
