"""发现、校验与保存动作脚本，供运行入口和编辑器共同使用。"""

import json
import math
from pathlib import Path

from route import PATHS
from tool.log import CUS_LOGGER
from tool.storage import write_data


def script_key(path):
    """项目内脚本保存相对路径，外部脚本保留绝对路径。"""
    path = Path(path).resolve()
    root = Path(PATHS["root"]).resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def script_path(key):
    return (Path(PATHS["root"]) / key).resolve()


def validate_script(data):
    """校验公共动作结构，保留模块专用方法和扩展字段。

    Raises:
        ValueError: 脚本结构或公共坐标、时间参数无效。
    """
    if not isinstance(data, list) or not data:
        raise ValueError("脚本必须是非空事件列表")
    try:
        json.dumps(data, allow_nan=False)
    except ValueError as error:
        raise ValueError("脚本包含 JSON 不支持的数值（NaN 或 Infinity）") from error
    for index, event in enumerate(data, 1):
        label = f"事件 {index}"
        if not isinstance(event, dict) or not isinstance(event.get("name"), str) or not event["name"].strip():
            raise ValueError(f"{label} 需要非空名称")
        trigger = event.get("trigger")
        if not isinstance(trigger, dict) or not any(trigger.get(key) for key in ("text", "photo", "state_only")):
            raise ValueError(f"{label} 需要文本、图片或纯状态触发条件")
        if trigger.get("text") and "box" not in trigger:
            raise ValueError(f"{label} 的文本触发需要 box 识别范围")
        steps = event.get("actions")
        if not isinstance(steps, list):
            raise ValueError(f"{label} 的 actions 必须是动作列表")
        for number, step in enumerate(steps, 1):
            if isinstance(step, str):
                if not step.isidentifier():
                    raise ValueError(f"{label} 动作 {number} 的内核方法名称无效")
            elif not isinstance(step, dict) or not step:
                raise ValueError(f"{label} 动作 {number} 必须是参数对象或内核方法名称")
        for item in (trigger, *(step for step in steps if isinstance(step, dict))):
            for key, size in (("box", 4), ("position", 2)):
                if key in item and (not isinstance(item[key], list) or len(item[key]) != size
                                    or not all(isinstance(n, (int, float)) and not isinstance(n, bool)
                                               and math.isfinite(n) for n in item[key])):
                    raise ValueError(f"{label} 的 {key} 需要 {size} 个有效数值")
            for key in ("sleep", "real_sleep", "time", "interval"):
                if key not in item:
                    continue
                value = item[key]
                # 运行内核会将等待时间转为浮点数；兼容既有脚本的数值字符串。
                if key in ("sleep", "real_sleep") and isinstance(value, str):
                    try:
                        value = float(value)
                    except ValueError as error:
                        raise ValueError(f"{label} 的 {key} 必须是有效等待时间") from error
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{label} 的 {key} 必须是非负有限数值")
    return data


def parse_script(text):
    try:
        return validate_script(json.loads(text))
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 第 {error.lineno} 行、第 {error.colno} 列：{error.msg}") from error


def read_script(path):
    return parse_script(Path(path).read_text(encoding="utf-8-sig"))


def save_script(path, data):
    validate_script(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_data(path, json.dumps(data, ensure_ascii=False, indent=4, allow_nan=False) + "\n")


def discover_scripts(registry):
    folders = [Path(PATHS["root"]) / "actions"]
    folders.extend(spec.folder / "actions" for spec in registry.runnable())
    paths = []
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, list):
                    continue
                validate_script(data)
            except (OSError, ValueError) as error:
                CUS_LOGGER.warning("脚本 %s 无法加载，将跳过此文件：%s", path.name, error)
                continue
            paths.append(path)
    return paths
