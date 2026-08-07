"""
进度管理 Mixin

提供工作进度的保存、加载、配置导入导出功能
"""

from pathlib import Path
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from core.progress_config import ProgressFileManager


class ProgressMixin:
    """进度管理 Mixin"""

    def _update_title(self):
        """更新窗口标题"""
        if self._current_file:
            fname = Path(self._current_file).name
            suffix = ' *未保存' if self._dirty else ''
            self.setWindowTitle(f'发运单生成器 - {fname}{suffix}')
        else:
            self.setWindowTitle('发运单生成器')

    def import_bom_data(self):
        """导入BOM数据（导入前自动保存当前工作进度）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择BOM数据文件', '',
            'Excel文件 (*.xlsx *.xls);;CSV文件 (*.csv);*;所有文件 (*.*)'
        )

        if file_path:
            if self.tree_builder.all_nodes:
                reply = QMessageBox.question(
                    self, '确认导入',
                    '导入新BOM将覆盖当前所有发运配置！\n\n'
                    '是否先保存当前工作进度，再导入新BOM？\n\n'
                    '点击"是"：保存当前进度 → 导入新BOM\n'
                    '点击"否"：放弃当前进度，直接导入\n'
                    '点击"取消"：取消导入',
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    self.save_progress()
                    if not hasattr(self, '_last_progress_path') or not self._last_progress_path:
                        reply2 = QMessageBox.question(
                            self, '继续导入',
                            '工作进度未保存，是否继续导入新BOM？\n（当前配置将丢失）',
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No
                        )
                        if reply2 != QMessageBox.Yes:
                            return
                elif reply == QMessageBox.Cancel:
                    return

            self._do_import_bom(file_path)

    def _do_import_bom(self, file_path):
        """执行BOM导入"""
        try:
            from core.bom_parser import BOMParser

            self.current_shipping_order = None

            # 忙碌状态：等待光标 + 按钮禁用防重入；弹窗移到 with 外，
            # 避免等待光标罩在对话框上
            with self._busy('正在导入BOM数据...'):
                parser = BOMParser()
                df = parser.parse(file_path)

                self.tree_builder.build_from_dataframe(df)

                # 切换数据集：清空撤销/恢复栈，避免旧数据快照被撤销复活进新数据集
                self._clear_undo_redo()

                self.refresh_tree()
                self.update_status_bar()
                self._current_file = file_path
                self._dirty = True
                self._update_title()
            self.statusBar().showMessage(f'BOM数据导入成功: {file_path}')
            QMessageBox.information(self, '成功', f'BOM数据导入成功！\n\n'
                                    f'总节点数: {len(self.tree_builder.all_nodes)}')
        except Exception as e:
            self.statusBar().showMessage('导入失败')
            QMessageBox.critical(self, '错误', f'BOM数据导入失败:\n{str(e)}')

    def save_progress(self):
        """保存工作进度

        Returns:
            bool: 保存成功返回 True；无数据、用户取消或保存失败返回 False
        """
        if not self.tree_builder.all_nodes:
            QMessageBox.warning(self, '警告', '没有可保存的数据！')
            return False

        if hasattr(self, '_last_progress_path') and self._last_progress_path:
            file_path = self._last_progress_path
        else:
            # 默认保存目录指向可写应用目录（打包后为 EXE 所在目录/progress）
            from utils.helpers import get_writable_app_dir
            progress_dir = get_writable_app_dir() / 'progress'
            progress_dir.mkdir(parents=True, exist_ok=True)
            project_id = self.tree_builder.project_id or '未命名项目'
            default_name = str(progress_dir / f'{project_id}_工作进度.xlsx')

            file_path, _ = QFileDialog.getSaveFileName(
                self, '保存工作进度', default_name,
                'Excel文件 (*.xlsx)'
            )
            if not file_path:
                return False  # 用户取消保存
            self._last_progress_path = Path(file_path)

        try:
            project_info = {
                '项目名称': self.edit_project_name.text() if hasattr(self, 'edit_project_name') else '',
                '项目图号': self.edit_project_drawing.text() if hasattr(self, 'edit_project_drawing') else '',
                '施工号': self.edit_project_construction.text() if hasattr(self, 'edit_project_construction') else '',
                '制作': self.edit_maker.text() if hasattr(self, 'edit_maker') else '',
                '审核': self.edit_reviewer.text() if hasattr(self, 'edit_reviewer') else '',
            }

            progress_mgr = ProgressFileManager()
            total, visible, hidden = progress_mgr.save(
                str(file_path),
                self.tree_builder.all_nodes,
                project_info,
                hidden_checker=lambda n: self._is_node_hidden(n)
            )

            self.statusBar().showMessage(f'进度已保存: {file_path}')
            self._dirty = False
            self._update_title()
            QMessageBox.information(self, '成功',
                f'工作进度保存成功！\n\n文件: {file_path}\n\n'
                f'总物料数: {total} 个\n'
                f'可见节点: {visible} 个\n'
                f'已隐藏节点: {hidden} 个')
            return True
        except Exception as e:
            self.statusBar().showMessage('保存失败')
            QMessageBox.critical(self, '错误', f'保存失败:\n{str(e)}')
            return False

    def load_progress(self):
        """加载工作进度"""
        # 默认加载目录指向可写应用目录（打包后为 EXE 所在目录/progress）
        from utils.helpers import get_writable_app_dir
        progress_dir = str(get_writable_app_dir() / 'progress')
        file_path, _ = QFileDialog.getOpenFileName(
            self, '加载工作进度', progress_dir,
            'Excel文件 (*.xlsx *.xls);;所有文件 (*.*)'
        )

        if file_path:
            try:
                progress_mgr = ProgressFileManager()
                result = progress_mgr.load(file_path)
                df = result['dataframe']
                project_info = result['project_info']

                self.tree_builder.build_from_dataframe(df)

                # 切换数据集：清空撤销/恢复栈，避免旧数据快照被撤销复活进新数据集
                self._clear_undo_redo()

                # 恢复发运配置
                progress_mgr.restore_nodes(df, self.tree_builder.all_nodes)

                # 恢复项目信息
                if project_info:
                    if hasattr(self, 'edit_project_name'):
                        self.edit_project_name.setText(str(project_info.get('项目名称', '')))
                    if hasattr(self, 'edit_project_drawing'):
                        self.edit_project_drawing.setText(str(project_info.get('项目图号', '')))
                    if hasattr(self, 'edit_project_construction'):
                        self.edit_project_construction.setText(str(project_info.get('施工号', '')))
                    if hasattr(self, 'edit_maker'):
                        self.edit_maker.setText(str(project_info.get('制作', '')))
                    if hasattr(self, 'edit_reviewer'):
                        self.edit_reviewer.setText(str(project_info.get('审核', '')))

                self.refresh_tree()
                self._restore_expand_state()
                self.update_status_bar()

                self._last_progress_path = Path(file_path)
                self._current_file = file_path
                self._dirty = False
                self._update_title()
                self.statusBar().showMessage(f'进度已加载: {file_path}')
                QMessageBox.information(self, '成功',
                    f'工作进度加载成功！\n\n文件: {file_path}\n\n'
                    f'共加载 {len(self.tree_builder.all_nodes)} 条物料数据')
            except Exception as e:
                self.statusBar().showMessage('加载失败')
                QMessageBox.critical(self, '错误', f'加载失败:\n{str(e)}')

    def import_config(self):
        """导入发运配置"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择发运配置文件', '',
            'Excel文件 (*.xlsx *.xls);;CSV文件 (*.csv);;所有文件 (*.*)'
        )

        if file_path:
            try:
                self.statusBar().showMessage('正在导入配置...')
                self.tree_builder.load_config(file_path)
                self.refresh_tree()
                self.update_status_bar()
                self.statusBar().showMessage(f'成功导入发运配置: {file_path}')
                QMessageBox.information(self, '成功', '发运配置导入成功！')
            except Exception as e:
                self.statusBar().showMessage('导入失败')
                QMessageBox.critical(self, '错误', f'导入失败:\n{str(e)}')

    def save_config(self):
        """保存发运配置"""
        if not self.tree_builder.all_nodes:
            QMessageBox.warning(self, '警告', '没有可保存的配置！')
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, '保存发运配置', '发运配置.xlsx',
            'Excel文件 (*.xlsx);;CSV文件 (*.csv)'
        )

        if file_path:
            try:
                self.tree_builder.save_config(file_path)
                self.statusBar().showMessage(f'配置已保存: {file_path}')
                QMessageBox.information(self, '成功', f'配置保存成功！\n\n文件: {file_path}')
            except Exception as e:
                self.statusBar().showMessage('保存失败')
                QMessageBox.critical(self, '错误', f'保存失败:\n{str(e)}')

    def load_config(self):
        """加载发运配置"""
        if not self.tree_builder.all_nodes:
            QMessageBox.warning(self, '警告', '请先导入BOM数据！')
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, '加载发运配置', '',
            'Excel文件 (*.xlsx *.xls);;CSV文件 (*.csv);;所有文件 (*.*)'
        )

        if file_path:
            try:
                reply = QMessageBox.question(
                    self, '确认加载',
                    '加载配置将覆盖当前配置，是否继续？',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if reply == QMessageBox.Yes:
                    self.tree_builder.load_config(file_path)
                    self.refresh_tree()
                    self.update_status_bar()
                    self.statusBar().showMessage(f'配置已加载: {file_path}')
                    QMessageBox.information(self, '成功', f'配置加载成功！\n\n文件: {file_path}')
            except Exception as e:
                self.statusBar().showMessage('加载失败')
                QMessageBox.critical(self, '错误', f'加载失败:\n{str(e)}')
