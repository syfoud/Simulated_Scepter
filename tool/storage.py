"""模块资源定位与配置补全，配置只保留一个写入来源。"""

import configparser
import copy
import json
import os
import tempfile
from pathlib import Path

from route import PATHS
from tool import EXTRA


def module_path(source):
    return Path(PATHS["core"]) / Path(source).parent.name


def resource_path(source, relative):
    folder = module_path(source).resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder):
        raise ValueError(f"模块资源路径越界：{relative}")
    return path


def user_path(relative):
    """模块用户配置统一放在程序目录的 user 文件夹下。"""
    folder = Path(PATHS["user"]).resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder):
        raise ValueError(f"用户配置路径越界：{relative}")
    return path


def write_data(path, text):
    """在同一目录写临时文件并替换，写入失败不会截断原配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    """读取 JSON 配置；文件不存在时返回空字典。"""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_defaults(values, defaults):
    """递归补齐默认配置缺失的字段；已有值（含用户清空的列表）保持不变。"""
    if not isinstance(defaults, dict):
        return values
    merged = copy.deepcopy(values) if isinstance(values, dict) else {}
    for key, default in defaults.items():
        if key in merged:
            merged[key] = merge_defaults(merged[key], default)
        else:
            merged[key] = copy.deepcopy(default)
    return merged


def config_path(source):
    """返回模块用户配置路径，缺失字段用模块默认配置补齐。"""
    folder = module_path(source)
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string((folder / "module.ini").read_text(encoding="utf-8"))
    section = parser["config"]
    path = user_path(section["file"])
    default = resource_path(source, section["default"])
    if not default.is_file():
        raise FileNotFoundError(f"缺少模块默认配置：{default}")
    with EXTRA.FILE_LOCK:
        values = read_json(path)
        merged = merge_defaults(values, read_json(default))
        if not path.is_file() or merged != values:
            write_data(path, json.dumps(merged, ensure_ascii=False, indent=4))
    return path


def load_module_settings(source):
    path = config_path(source)
    with EXTRA.FILE_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def update_module_settings(source, values):
    path = config_path(source)
    with EXTRA.FILE_LOCK:
        current = json.loads(path.read_text(encoding="utf-8"))
        current.update(values)
        write_data(path, json.dumps(current, ensure_ascii=False, indent=4))
    return current


def save_json_values(source, values):
    """合并 JSON 已有未知字段，避免新增参数被旧配置窗口覆盖。"""
    path = config_path(source)
    with EXTRA.FILE_LOCK:
        try:
            current = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            current = {}
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key].update(value)
            else:
                current[key] = value
        write_data(path, json.dumps(current, ensure_ascii=False, indent=4))


def save_json_configs(changes):
    """共同保存共享参数和模块参数；写入失败时恢复已写入的文件。"""
    paths = [(config_path(source), values) for source, values in changes]
    with EXTRA.FILE_LOCK:
        originals = {path: path.read_bytes() for path, values in paths}
        updated = []
        try:
            for path, values in paths:
                current = json.loads(originals[path].decode("utf-8"))
                current.update(values)
                write_data(path, json.dumps(current, ensure_ascii=False, indent=4))
                updated.append(path)
        except OSError:
            for path in updated:
                write_data(path, originals[path].decode("utf-8"))
            raise
