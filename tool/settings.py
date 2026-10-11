"""全局 JSON 配置的读取与合并保存，不依赖界面或运行内核。"""

import json
import shutil
from pathlib import Path

from route import PATHS
from tool import EXTRA


def load_settings():
    with EXTRA.FILE_LOCK:
        path = Path(PATHS["config"]) / "settings.json"
        if not path.exists():
            shutil.copy2(Path(PATHS["example"]) / "settings_example.json", path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return data


def update_settings(updates):
    """合并当前文件，避免配置窗口相互覆盖未编辑的字段。"""
    with EXTRA.FILE_LOCK:
        path = Path(PATHS["config"]) / "settings.json"
        if not path.exists():
            shutil.copy2(Path(PATHS["example"]) / "settings_example.json", path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(updates)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        return data


def save_config_values(config, values):
    """保存既有 YAML 配置对象，写入失败时恢复内存中的原值。"""
    previous = {key: getattr(config, key) for key in values}
    for key, value in values.items():
        setattr(config, key, value)
    try:
        config.save()
    except OSError:
        for key, value in previous.items():
            setattr(config, key, value)
        raise
