"""
辅助函数模块

提供常用的辅助函数
"""

import os
import sys
import shutil
from pathlib import Path
from typing import Optional


def is_frozen() -> bool:
    """
    判断当前是否运行在 PyInstaller 打包环境

    Returns:
        True 表示运行于打包后的 EXE 环境
    """
    return getattr(sys, 'frozen', False)


def get_bundle_dir() -> Path:
    """
    获取只读资源目录

    打包环境下为 PyInstaller 的 _MEIPASS 解压目录（存放打包进 EXE 的
    出厂默认资源，程序退出即被清空，只读）；开发环境下为项目根目录。

    Returns:
        只读资源根目录
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def get_writable_app_dir() -> Path:
    """
    获取可写的应用数据目录

    打包环境下为 EXE 所在目录（用户可写，配置/日志随应用携带）；
    开发环境下为项目根目录。所有需要持久化的用户数据都应写入此目录，
    切勿写入 get_bundle_dir()（打包后为临时目录，退出即焚）。

    Returns:
        可写应用数据根目录
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def seed_file_from_bundle(bundle_file: Path, writable_file: Path) -> None:
    """
    首次运行时把出厂默认文件从只读资源目录播种到可写目录

    仅当可写文件不存在、且打包资源中存在该文件时复制，避免覆盖用户数据。

    Args:
        bundle_file: 只读资源目录中的出厂文件路径
        writable_file: 可写目录中的目标文件路径
    """
    if not writable_file.exists() and bundle_file.exists():
        try:
            shutil.copyfile(bundle_file, writable_file)
        except OSError:
            # 播种失败不致命：后续读取会回退到内置默认值
            pass


def get_app_dir() -> Path:
    """
    获取应用程序目录

    Returns:
        应用程序根目录
    """
    return Path(__file__).parent.parent


def get_output_dir() -> Path:
    """
    获取输出目录

    Returns:
        输出目录路径，如果不存在则创建
    """
    output_dir = get_app_dir() / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def get_assets_dir() -> Path:
    """
    获取资源目录

    Returns:
        资源目录路径
    """
    return get_app_dir() / "assets"


def ensure_dir(dir_path: Path) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        dir_path: 目录路径

    Returns:
        目录路径
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def format_number(num: float, decimals: int = 2) -> str:
    """
    格式化数字

    Args:
        num: 数字
        decimals: 小数位数

    Returns:
        格式化后的字符串
    """
    # 处理 None / NaN，避免格式化抛异常
    if num is None:
        return ''
    if isinstance(num, float) and num != num:  # NaN（NaN != NaN）
        return ''
    if decimals == 0:
        return f"{round(num):,}"  # 四舍五入而非截断
    else:
        return f"{num:,.{decimals}f}"


def get_entity_name(entity_code: str) -> str:
    """
    获取发运主体名称（不带代码前缀，委托给 EntityConfigManager 统一管理）

    与 models.bom_node.get_entity_name 行为一致，返回纯名称（如"机头"）。
    如需带前缀的显示名（如"01-机头"），请改用 get_entity_display_name。

    Args:
        entity_code: 发运主体代码

    Returns:
        发运主体名称（纯名称，不带前缀）
    """
    from core.entity_config import EntityConfigManager
    return EntityConfigManager.get_entity_name(entity_code)


def get_method_name(method_code: str) -> str:
    """
    获取发运方式名称

    Args:
        method_code: 发运方式代码

    Returns:
        发运方式名称
    """
    name_map = {
        'A': '散装',
        'B': '打捆',
        'C': '装箱',
        'D': '特殊'
    }
    return name_map.get(method_code, method_code)


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除非法字符

    Args:
        filename: 原始文件名

    Returns:
        清理后的文件名
    """
    # 移除非法字符
    illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in illegal_chars:
        filename = filename.replace(char, '_')

    return filename


def get_file_extension(file_path: str) -> str:
    """
    获取文件扩展名

    Args:
        file_path: 文件路径

    Returns:
        文件扩展名（小写，包含点号）
    """
    return Path(file_path).suffix.lower()


def is_excel_file(file_path: str) -> bool:
    """
    判断是否为Excel文件

    Args:
        file_path: 文件路径

    Returns:
        是否为Excel文件
    """
    return get_file_extension(file_path) in ['.xlsx', '.xls']


def is_csv_file(file_path: str) -> bool:
    """
    判断是否为CSV文件

    Args:
        file_path: 文件路径

    Returns:
        是否为CSV文件
    """
    return get_file_extension(file_path) == '.csv'


def get_project_id_from_filename(filename: str) -> Optional[str]:
    """
    从文件名中提取项目编号

    Args:
        filename: 文件名

    Returns:
        项目编号，如果未找到则返回None
    """
    import re

    # 尝试匹配常见的项目编号格式
    patterns = [
        r'(LS\d+)',           # LS098
        r'(ls\d+)',           # ls098
        r'([A-Z]{2}\d+)',    # AB123
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    return None
