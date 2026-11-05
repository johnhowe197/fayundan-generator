# -*- coding: utf-8 -*-
"""统一测试入口

自动发现并运行 tests/test_*.py。每个脚本以独立子进程执行，
统一使用 UTF-8 输出与 Qt offscreen 平台，避免逐个手工运行和环境差异。

用法：
    python run_tests.py          # 运行全部
    python run_tests.py v26      # 只运行文件名包含 v26 的脚本

运行前后会备份并还原 config/，防止测试改动真实配置。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / 'tests'
CONFIG_DIR = ROOT / 'config'


def _run_one(path: Path, env: dict):
    """运行单个测试脚本，返回 (是否通过, 统计摘要, 输出)"""
    proc = subprocess.run(
        [sys.executable, '-X', 'utf8', str(path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    match = re.search(r'总计:\s*(\d+)\s*项.*?失败\s*(\d+)', output)
    if match:
        count, bad = int(match.group(1)), int(match.group(2))
        return proc.returncode == 0, f'{count - bad}/{count}', output
    # 部分脚本使用自定义汇总格式，按退出码判定
    return proc.returncode == 0, ('OK' if proc.returncode == 0 else 'FAIL'), output


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else ''
    files = sorted(TESTS_DIR.glob('test_*.py'))
    if keyword:
        files = [f for f in files if keyword in f.name]
    if not files:
        print(f'未找到匹配的测试脚本（关键字: {keyword!r}）')
        return 1

    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONUTF8'] = '1'

    # 备份真实配置，运行结束后还原（测试不应改动 config/）
    backup_root = Path(tempfile.mkdtemp(prefix='fayundan_config_'))
    had_config = CONFIG_DIR.exists()
    if had_config:
        shutil.copytree(CONFIG_DIR, backup_root / 'config')

    results = []
    try:
        for path in files:
            ok, summary, output = _run_one(path, env)
            results.append((path.name, ok, summary))
            if not ok:
                tail = '\n'.join(output.strip().splitlines()[-15:])
                print(f'\n--- {path.name} 失败输出 ---\n{tail}\n')
    finally:
        # 还原配置目录：删除测试可能写入的内容，再复制回运行前状态
        if had_config:
            if CONFIG_DIR.exists():
                shutil.rmtree(CONFIG_DIR)
            shutil.copytree(backup_root / 'config', CONFIG_DIR)
        shutil.rmtree(backup_root, ignore_errors=True)

    print('=' * 68)
    for name, ok, summary in results:
        print(f'{"PASS" if ok else "FAIL":5s} {name:46s} {summary}')
    print('=' * 68)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f'共 {len(files)} 个脚本，失败 {failed} 个')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
