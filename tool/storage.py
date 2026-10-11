"""模块资源定位与旧配置迁移，配置只保留一个写入来源。"""

import configparser
import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

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


def write_data(path, text):
    """在同一目录写临时文件并替换，写入失败不会截断原配置。"""
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def config_path(source):
    """首次使用时迁移旧文件；已有模块配置始终优先，不重复覆盖。"""
    folder = module_path(source)
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string((folder / "module.ini").read_text(encoding="utf-8"))
    section = parser["config"]
    path = resource_path(source, section["file"])
    default = resource_path(source, section["default"])
    legacy = Path(PATHS["config"]) / section["legacy"]
    with EXTRA.FILE_LOCK:
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        if section.get("keys"):
            values = json.loads(default.read_text(encoding="utf-8"))
            old = json.loads(legacy.read_text(encoding="utf-8")) if legacy.is_file() else {}
            keys = [key.strip() for key in section["keys"].split(",")]
            values.update({key: old[key] for key in keys if key in old})
            slot = values.get("silver_wolf_switch")
            if "silver_wolf_switch" in values and (slot is None or isinstance(slot, str)):
                values["silver_wolf_switch"] = {
                    "一号位": 1, "二号位": 2, "三号位": 3, "四号位": 4,
                }.get(slot, 1)
            # 先备份并写入新文件，成功后才移除旧全局配置中的模块字段。
            if legacy.is_file() and any(key in old for key in keys):
                backup = Path(PATHS["backup"]) / "before_core" / legacy.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    shutil.copy2(legacy, backup)
            write_data(path, json.dumps(values, ensure_ascii=False, indent=4))
            if legacy.is_file() and any(key in old for key in keys):
                for key in keys:
                    old.pop(key, None)
                try:
                    write_data(legacy, json.dumps(old, ensure_ascii=False, indent=4))
                except OSError:
                    path.unlink()
                    raise
        else:
            shutil.copy2(legacy if legacy.is_file() else default, path)
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


def save_yaml_values(source, values):
    """合并 YAML 已有未知字段，避免新增参数被旧配置窗口覆盖。"""
    path = config_path(source)
    with EXTRA.FILE_LOCK:
        current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key].update(value)
            else:
                current[key] = value
        write_data(path, yaml.safe_dump(current, allow_unicode=True, sort_keys=False))


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
