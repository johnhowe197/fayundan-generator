"""
配置对话框模块

用于编辑BOM节点的发运配置
"""

from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                             QLabel, QLineEdit, QComboBox, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QPushButton, QWidget)
from PyQt5.QtCore import Qt

from models.bom_node import BOMNode, get_entity_name


class ConfigDialog(QDialog):
    """节点配置对话框"""

    def __init__(self, node: BOMNode, parent=None):
        super().__init__(parent)
        self.node = node
        self.init_ui()

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(f'配置 - {self.node.material_id} {self.node.name}')
        self.setFixedSize(450, 400)

        # 主布局
        main_layout = QVBoxLayout()

        # 基本信息组
        info_group = QGroupBox("基本信息")
        info_layout = QFormLayout()

        # 物料号（只读）
        lbl_material = QLabel(self.node.material_id)
        lbl_material.setStyleSheet("font-weight: bold;")
        info_layout.addRow('物料号:', lbl_material)

        # 父物料号（只读）
        lbl_parent = QLabel(self.node.parent_id if self.node.parent_id else '(顶级节点)')
        info_layout.addRow('父物料号:', lbl_parent)

        # 名称（只读）
        lbl_name = QLabel(self.node.name)
        info_layout.addRow('名称:', lbl_name)

        # 数量信息
        info_layout.addRow('自身数量:', QLabel(str(self.node.quantity)))
        info_layout.addRow('最终数量:', QLabel(str(self.node.final_quantity)))

        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)

        # 发运配置组
        config_group = QGroupBox("发运配置")
        config_layout = QFormLayout()

        # 是否展开
        self.combo_expand = QComboBox()
        self.combo_expand.addItems(['是', '否'])
        self.combo_expand.setCurrentText(self.node.expand_status)
        self.combo_expand.currentTextChanged.connect(self.on_expand_changed)
        config_layout.addRow('是否展开:', self.combo_expand)

        # 发运主体
        self.combo_entity = QComboBox()
        self.combo_entity.setEditable(True)
        self.combo_entity.addItems([''] + self.get_entity_list())
        self.combo_entity.setCurrentText(self.node.shipping_entity)
        config_layout.addRow('发运主体:', self.combo_entity)

        # 发运方式
        self.combo_method = QComboBox()
        self.combo_method.addItems(['', 'A-散装', 'B-打捆', 'C-装箱', 'D-特殊'])
        self.combo_method.setCurrentText(self._get_method_display(self.node.shipping_method))
        config_layout.addRow('发运方式:', self.combo_method)

        # 备注
        self.edit_remark = QLineEdit(self.node.remark)
        self.edit_remark.setPlaceholderText('可选备注信息')
        config_layout.addRow('备注:', self.edit_remark)

        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

        # 快捷设置按钮
        quick_group = QGroupBox("快捷设置")
        quick_layout = QHBoxLayout()

        # 清空配置按钮
        btn_clear = QPushButton('清空配置')
        btn_clear.clicked.connect(self.clear_config)
        quick_layout.addWidget(btn_clear)

        quick_layout.addStretch()

        quick_group.setLayout(quick_layout)
        main_layout.addWidget(quick_group)

        # 按钮组
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # 自定义按钮样式
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setText('确定')
        ok_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 20px;")

        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        cancel_button.setText('取消')

        main_layout.addWidget(buttons)

        self.setLayout(main_layout)

        # 更新UI状态
        self.on_expand_changed(self.combo_expand.currentText())

    def get_entity_list(self):
        """获取发运主体列表（动态加载，与主窗口保持一致）"""
        from core.entity_config import EntityConfigManager
        entity_mgr = EntityConfigManager()
        entity_map = entity_mgr.get_entity_map()  # {code: "code-name"}
        return [entity_map[code] for code in sorted(entity_map.keys())]

    def _get_method_display(self, method_code: str) -> str:
        """获取发运方式显示文本"""
        method_map = {
            'A': 'A-散装',
            'B': 'B-打捆',
            'C': 'C-装箱',
            'D': 'D-特殊'
        }
        return method_map.get(method_code, '')

    def _get_method_code(self, display_text: str) -> str:
        """从显示文本获取发运方式代码"""
        if display_text and '-' in display_text:
            return display_text[0]
        return ''

    def on_expand_changed(self, text):
        """是否展开状态改变"""
        is_expand = (text == '是')

        # 如果选择"是"，禁用发运配置
        self.combo_entity.setEnabled(not is_expand)
        self.combo_method.setEnabled(not is_expand)
        self.edit_remark.setEnabled(not is_expand)

        # 如果选择"是"，清空发运配置
        if is_expand:
            self.combo_entity.setCurrentText('')
            self.combo_method.setCurrentText('')

    def clear_config(self):
        """清空配置"""
        self.combo_expand.setCurrentText('是')
        self.combo_entity.setCurrentText('')
        self.combo_method.setCurrentText('')
        self.edit_remark.clear()

    def accept(self):
        """确认保存"""
        # 获取发运方式代码
        method_display = self.combo_method.currentText()
        method_code = self._get_method_code(method_display)

        # 获取发运主体代码（去掉后面的名称）
        entity_text = self.combo_entity.currentText()
        entity_code = entity_text.split('-')[0] if entity_text and '-' in entity_text else entity_text

        # 更新节点配置
        self.node.expand_status = self.combo_expand.currentText()
        self.node.shipping_entity = entity_code
        self.node.shipping_method = method_code
        self.node.remark = self.edit_remark.text()

        # 重新计算最终数量
        self.node.calculate_final_quantity()

        super().accept()
