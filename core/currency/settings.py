import json
import os
from pathlib import Path

from tool import EXTRA
from tool.storage import config_path, resource_path, write_data

EXIT_PLANES = (1, 2, 3)
DEFAULT_EXIT_PLANE = 1
DEFAULT_EXIT_IF_NO_PRIOR = False
DEFAULT_PRIOR_EXIT_PLANE = None
DEFAULT_AUTO_EXIT_PLANE = False


PRIORITY_KEYS = (
    "prior_envir",
    "envir_1",
    "envir_2",
    "envir_3",
    "envir_4",
)

def load_default_priority():
    """Load the default currency-war priority from the example config."""
    try:
        with open(resource_path(__file__, "config/default.json"), encoding="utf-8") as config_file:
            values = json.load(config_file) or {}
    except (OSError, ValueError):
        return {}

    priority = values.get("priority")

    if not isinstance(priority, dict):
        return {}

    return priority

def normalize_currency_settings(values=None):
    """Validate currency-war settings and return serializable values.

    exit_after_plane 为 None 表示完成投资策略选择后不退出对局；prior_exit_plane
    为 None 表示刷出必选投资环境时不调整退出位面。
    """
    values = values if isinstance(values, dict) else {}
    exit_plane = values.get("exit_after_plane", DEFAULT_EXIT_PLANE)
    if exit_plane is not None:
        try:
            exit_plane = int(exit_plane)
        except (TypeError, ValueError):
            exit_plane = DEFAULT_EXIT_PLANE
        if exit_plane not in EXIT_PLANES:
            exit_plane = DEFAULT_EXIT_PLANE

    exit_if_no_prior = values.get(
        "exit_if_no_prior",
        DEFAULT_EXIT_IF_NO_PRIOR,
    )
    if not isinstance(exit_if_no_prior, bool):
        exit_if_no_prior = DEFAULT_EXIT_IF_NO_PRIOR

    prior_exit_plane = values.get(
        "prior_exit_plane",
        DEFAULT_PRIOR_EXIT_PLANE,
    )
    if prior_exit_plane is not None:
        try:
            prior_exit_plane = int(prior_exit_plane)
        except (TypeError, ValueError):
            prior_exit_plane = DEFAULT_PRIOR_EXIT_PLANE

        if prior_exit_plane not in EXIT_PLANES:
            prior_exit_plane = DEFAULT_PRIOR_EXIT_PLANE

    priority = values.get("priority")
    if not isinstance(priority, dict):
        priority = {}

    default_priority = load_default_priority()

    for key in PRIORITY_KEYS:
        if key not in priority or not isinstance(priority[key], list):
            priority[key] = default_priority.get(key, [])
        priority[key] = [entry for entry in priority[key] if isinstance(entry, str)]

    deployment = values.get("deployment", {})
    if not isinstance(deployment, dict):
        deployment = {}
    clean_deployment = {}
    for key in ("front_priority", "back_priority"):
        entries = deployment.get(key, [])
        if not isinstance(entries, list):
            entries = []
        clean_deployment[key] = list(dict.fromkeys(
            entry.strip() for entry in entries if isinstance(entry, str) and entry.strip()
        ))
    names = deployment.get("names", {})
    if not isinstance(names, dict):
        names = {}
    clean_deployment["names"] = {
        template: name.strip()
        for template, name in names.items()
        if isinstance(template, str) and isinstance(name, str) and name.strip()
    }

    strategy_targets = know = values.get("strategy_targets", [])
    if not isinstance(know, list):
        strategy_targets = []
    strategy_targets = [n.strip() for n in strategy_targets if isinstance(n, str) and n.strip()]


    strategy_avoid = values.get("strategy_avoid", [])
    if not isinstance(strategy_avoid, list):
        strategy_avoid = []
    strategy_avoid = [n.strip() for n in strategy_avoid if isinstance(n, str) and n.strip()]
    strategy_targets = list(dict.fromkeys(strategy_targets))
    strategy_avoid = list(dict.fromkeys(strategy_avoid))


    auto_exit_plane = values.get("auto_exit_plane", DEFAULT_AUTO_EXIT_PLANE)
    if not isinstance(auto_exit_plane, bool):
        auto_exit_plane = DEFAULT_AUTO_EXIT_PLANE

    return {
        "strategy_targets": strategy_targets,
        "strategy_avoid": strategy_avoid,
        "auto_exit_plane": auto_exit_plane,
        "exit_after_plane": exit_plane,
        "exit_if_no_prior": exit_if_no_prior,
        "prior_exit_plane": prior_exit_plane,
        "priority": priority,
        "deployment": clean_deployment,
    }

def resolve_priority(deployment):
    """把上阵优先级里的角色名换成模板文件名，直接写模板文件名也可以。

    Returns:
        (前台模板名列表, 后台模板名列表)；认不出的条目原样保留，方便先配置后采集。
    """
    by_name = {name: template for template, name in deployment["names"].items()}
    resolved = []
    for key in ("front_priority", "back_priority"):
        entries = []
        for entry in deployment[key]:
            template = by_name.get(entry, entry)
            if template not in entries:
                entries.append(template)
        resolved.append(entries)
    return resolved[0], resolved[1]


def load_currency_settings(path=None):
    """Load the currency-war settings, falling back to safe defaults."""
    path = os.fspath(config_path(__file__) if path is None else path)
    if not os.path.exists(path):
        return normalize_currency_settings()

    with EXTRA.FILE_LOCK:
        try:
            with open(path, encoding="utf-8") as config_file:
                values = json.load(config_file) or {}
        except (OSError, ValueError):
            values = {}
    return normalize_currency_settings(values)


def save_currency_settings(values, path=None):
    """Update currency-war settings while preserving future config fields."""
    path = os.fspath(config_path(__file__) if path is None else path)
    with EXTRA.FILE_LOCK:
        try:
            with open(path, encoding="utf-8") as config_file:
                current = json.load(config_file) or {}
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}

        current.update(values)
        normalized = normalize_currency_settings(current)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        write_data(Path(path), json.dumps(current, ensure_ascii=False, indent=4))
    return normalized
