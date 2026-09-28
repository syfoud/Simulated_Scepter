"""弹指生产模型的独立配置读写。"""

import os
import json
import shutil
from dataclasses import asdict, fields
from pathlib import Path

from route import PATHS
from tool import EXTRA
from tool.countdown_evaluator import (
    CAMPAIGN_DEFAULT_TARGETS, DECISION_DP, DECISION_MC, DECISION_WIN_RATE,
    DECISION_WIN_RATE_DP, MCConfig,
)


CONFIG_KEY = "finger_snap_model"
MC_SETTING_FIELDS = tuple(field.name for field in fields(MCConfig))
DECISION_MODES = {
    DECISION_MC: "MC-EV",
    DECISION_WIN_RATE: "MC-WR",
    DECISION_WIN_RATE_DP: "MC-WR→DP",
    DECISION_DP: "DP",
}
EARLY_STOP_FIELDS = {
    DECISION_DP: "dp_early_stop",
    DECISION_WIN_RATE: "win_rate_dp_early_stop",
    DECISION_WIN_RATE_DP: "win_rate_dp_early_stop",
    DECISION_MC: "mc_dp_early_stop",
}
settings_path = os.path.join(PATHS["config"], "settings.json")
example_path = os.path.join(PATHS["example"], "settings_example.json")


def normalize_finger_snap_settings(values=None):
    """校验并补齐模型配置，返回可直接保存的基础类型。"""
    values, defaults = values or {}, MCConfig()
    targets = values.get("plane_targets", CAMPAIGN_DEFAULT_TARGETS)
    if not isinstance(targets, (list, tuple)) or len(targets) != 3:
        raise ValueError("三个位面必须各有一个目标 CD")
    legacy_step = values.get("path_bonus_step")
    decision_mode = str(values.get("decision_mode", DECISION_WIN_RATE))
    if decision_mode not in DECISION_MODES:
        raise ValueError(f"未知决策依据: {decision_mode}")
    mc = MCConfig(
        control_rollouts=values.get("control_rollouts", defaults.control_rollouts),
        evaluation_rollouts=values.get("evaluation_rollouts", defaults.evaluation_rollouts),
        min_visits=values.get("min_visits", defaults.min_visits),
        epsilon_start=values.get("epsilon_start", defaults.epsilon_start),
        epsilon_end=values.get("epsilon_end", defaults.epsilon_end),
        seed=values.get("seed", defaults.seed),
        win_rate_noise_floor_percent=values.get(
            "win_rate_noise_floor_percent",
            defaults.win_rate_noise_floor_percent),
        path_reward_bonus=values.get(
            "path_reward_bonus", defaults.path_reward_bonus if legacy_step is None else float(legacy_step) * 5),
        path_event_bonus=values.get(
            "path_event_bonus", defaults.path_event_bonus if legacy_step is None else float(legacy_step) * 4),
        path_trade_bonus=values.get(
            "path_trade_bonus", defaults.path_trade_bonus if legacy_step is None else float(legacy_step) * 3),
        path_adventure_bonus=values.get(
            "path_adventure_bonus", defaults.path_adventure_bonus if legacy_step is None else float(legacy_step) * 2),
        path_bugevent_bonus=values.get(
            "path_bugevent_bonus", defaults.path_bugevent_bonus if legacy_step is None else float(legacy_step)),
    ).normalized()
    return asdict(mc) | {
        "decision_mode": decision_mode,
        "dp_early_stop": bool(values.get("dp_early_stop", False)),
        "win_rate_dp_early_stop": bool(values.get("win_rate_dp_early_stop", False)),
        "mc_dp_early_stop": bool(values.get("mc_dp_early_stop", False)),
        "plane_targets": [int(value) for value in targets],
        "first_plane_threshold": float(values.get("first_plane_threshold", 4.0)),
        "record_keep_count": int(values.get("record_keep_count", 31)),
    }


def load_finger_snap_settings(path=settings_path):
    """只读取弹指配置；旧配置文件缺少该字段时使用默认值。"""
    path = Path(path)
    if not path.exists() and path == settings_path and example_path.exists():
        shutil.copy2(example_path, path)
    if not path.exists():
        return normalize_finger_snap_settings()
    with EXTRA.FILE_LOCK, path.open(encoding="utf-8") as file:
        return normalize_finger_snap_settings(json.load(file).get(CONFIG_KEY, {}))


def save_finger_snap_settings(values, path=settings_path):
    """仅更新独立弹指配置，保留同一文件中的其它业务设置。"""
    path, normalized = Path(path), normalize_finger_snap_settings(values)
    with EXTRA.FILE_LOCK:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[CONFIG_KEY] = normalized
        path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    return normalized
