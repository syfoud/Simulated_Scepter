"""全局 JSON 配置的读取与合并保存，不依赖界面或运行内核。

用户配置保存在程序目录下的 user 文件夹，首次运行时由自带的
resource/gui_settings_default.json 创建；之后的读写都只针对这份用户配置。
"""

import json
import os
import shutil

from route import PATHS
from tool import EXTRA
from tool.storage import merge_defaults


def ensure_settings():
    """确保用户配置存在，返回其路径；不存在时复制默认配置创建。"""
    path = os.path.join(PATHS["user"], "gui_settings.json")
    with EXTRA.FILE_LOCK:
        if not os.path.exists(path):
            os.makedirs(PATHS["user"], exist_ok=True)
            shutil.copy2(
                os.path.join(PATHS["root"], "resource", "gui_settings_default.json"), path
            )
    return path


def read_json(path) -> dict | None:
    """读取 JSON 对象。

    Args:
        path: 配置文件路径。

    Returns:
        解析后的字典；文件不存在、无法读取或格式不是对象时返回 None。
    """
    path = os.fspath(path)
    if not os.path.isfile(path):
        return None
    with EXTRA.FILE_LOCK:
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def write_json(path, data: dict) -> None:
    """以统一缩进写入 JSON 对象，目录不存在时自动创建。

    Args:
        path: 配置文件路径。
        data: 待写入的配置字典。
    """
    path = os.fspath(path)
    with EXTRA.FILE_LOCK:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode="w", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False, indent=4))


def load_default_settings() -> dict | None:
    """读取默认配置；不可读时返回 None，由调用方使用代码内置兜底。"""
    return read_json(os.path.join(PATHS["root"], "resource", "gui_settings_default.json"))


def load_settings():
    """读取用户配置；首次运行时用默认配置创建，缺失字段按默认配置补齐。"""
    path = ensure_settings()
    with EXTRA.FILE_LOCK:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        merged = merge_defaults(data, load_default_settings() or {})
        if merged != data:
            write_json(path, merged)
        return merged


def update_settings(updates):
    """合并当前文件，避免配置窗口相互覆盖未编辑的字段。

    读-改-写全程持锁，避免自动清理等后台写入覆盖本次保存的字段。
    """
    with EXTRA.FILE_LOCK:
        data = load_settings()
        data.update(updates)
        write_json(os.path.join(PATHS["user"], "gui_settings.json"), data)
    return data


def save_config_values(config, values):
    """保存既有配置对象，写入失败时恢复内存中的原值。"""
    previous = {key: getattr(config, key) for key in values}
    for key, value in values.items():
        setattr(config, key, value)
    try:
        config.save()
    except OSError:
        for key, value in previous.items():
            setattr(config, key, value)
        raise
