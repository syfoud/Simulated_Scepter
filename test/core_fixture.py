"""给配置和 GUI 测试准备独立模块资源，避免修改用户的模块配置。"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_core(target):
    shutil.copytree(ROOT / "core", target, ignore=shutil.ignore_patterns(
        "__pycache__", "settings.json", "settings.yml",
    ))
    return Path(target)
