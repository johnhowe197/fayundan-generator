"""
发运单生成器 - 主程序入口

项目名称：发运单生成器（桌面版）
版本：2.3.1
创建日期：2026-06-06
描述：离线桌面应用，实现多级BOM数据导入、树结构可视化、发运配置维护、自动计算和发运单导出
"""

import sys
import os
import traceback
import logging
from pathlib import Path

# 设置控制台编码
import io
_stdout_wrap_error = None
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
except Exception as e:
    _stdout_wrap_error = e

# 添加当前目录到Python路径
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

# 确定可写的应用数据目录（打包后为 EXE 所在目录，开发环境为脚本所在目录），
# 用于存放日志等需持久化且可写的数据，避免打包后落入临时目录而丢失
if getattr(sys, 'frozen', False):
    app_data_dir = Path(sys.executable).parent
else:
    app_data_dir = app_dir

# 设置日志
log_file = app_data_dir / "error.log"
logging.basicConfig(
    filename=str(log_file),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 同时输出到控制台
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(console_handler)

if _stdout_wrap_error is not None:
    logging.debug(f'控制台输出编码包装失败（不影响主流程）: {_stdout_wrap_error}')


def main():
    """主函数"""
    logging.info("程序启动中...")

    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from PyQt5.QtGui import QFont
        from PyQt5.QtCore import Qt

        logging.info("PyQt5导入成功")

        # 创建应用程序
        app = QApplication(sys.argv)
        logging.info("应用程序创建成功")

        # 设置应用程序字体
        font = QFont("Microsoft YaHei", 10)
        app.setFont(font)

        # 设置应用程序样式
        app.setStyle('Fusion')

        # 设置应用程序信息
        app.setApplicationName("发运单生成器")
        app.setApplicationVersion("2.3.1")
        app.setOrganizationName("WJH")

        # 设置异常钩子
        def exception_hook(exc_type, exc_value, exc_traceback):
            """全局异常处理"""
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            logging.error(f"未处理的异常: {error_msg}")

            # 弹窗提示，避免打包（console=False）后异常表现为"静默闪退"，
            # 用户和开发者都无从知晓。弹窗失败不影响日志记录。
            try:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.critical(
                    None, "程序错误",
                    f"发生未处理的异常：\n\n{type(exc_value).__name__}: {exc_value}\n\n"
                    f"详细信息已记录到 error.log"
                )
            except Exception:
                logging.debug('未处理异常弹窗显示失败', exc_info=True)

        sys.excepthook = exception_hook

        # 导入并显示主窗口
        logging.info("正在导入MainWindow...")
        from ui.main_window import MainWindow

        logging.info("正在创建MainWindow...")
        window = MainWindow()

        logging.info("正在显示窗口...")
        window.show()

        logging.info("程序启动成功，进入事件循环")

        # 运行应用程序
        exit_code = app.exec_()
        logging.info(f"程序退出，退出码: {exit_code}")
        sys.exit(exit_code)

    except Exception as e:
        # 记录错误
        error_msg = traceback.format_exc()
        logging.error(f"程序启动错误: {error_msg}")

        # 打印到控制台
        print("=" * 60)
        print("程序启动错误!")
        print("=" * 60)
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        print("=" * 60)

        # 尝试显示错误对话框
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "启动失败",
                f"程序启动失败:\n\n{type(e).__name__}: {str(e)}"
            )
        except Exception:
            logging.debug('启动失败弹窗显示失败', exc_info=True)

        raise


if __name__ == '__main__':
    main()
