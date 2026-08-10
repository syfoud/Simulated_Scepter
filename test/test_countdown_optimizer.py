"""旧单图接口的兼容层。

历史版本在这个文件中混合了识图、近似 DP、MC、缓存、打印与结果展示。实际 GUI
已经改用 ``countdown_backend``；此文件仅保留旧脚本仍会调用的
``analyze_single_map``，并把它转发到同一套纯 MC 状态机。
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from .countdown_backend import (
        ALL_EFFECTS, CountdownMap, CountdownSession, DecisionContext, EFFECT_NAMES,
        MCConfig, MonteCarloController, PHASE_EFFECT, PHASE_PATH,
        format_action,
    )
    from .countdown_map_loader import load_countdown_map
except ImportError:
    from countdown_backend import (
        ALL_EFFECTS, CountdownMap, CountdownSession, DecisionContext, EFFECT_NAMES,
        MCConfig, MonteCarloController, PHASE_EFFECT, PHASE_PATH,
        format_action,
    )
    from countdown_map_loader import load_countdown_map


MapSimulator = CountdownMap
MonteCarloOptimizer = MonteCarloController


class ExactCountdownDP:
    """阻止旧调用静默继续使用已证实语义不一致的近似 DP。"""

    def __init__(self, *_args, **_kwargs):
        raise RuntimeError(
            "ExactCountdownDP 已从在线推荐链路移除；请使用 MonteCarloController，"
            "DP 只能作为另行验证过的离线测试 oracle。")


def _decision_text(context, recommendation, node_names):
    lines = [
        f"当前阶段: {context.phase}",
        f"当前节点: #{context.state.node_idx}",
        f"当前CD: {context.state.countdown}",
        f"资源: cheat={context.state.cheat_rem} reroll={context.state.reroll_rem}",
    ]
    if context.observed_effect:
        lines.append(f"实际观察效果: {EFFECT_NAMES[context.observed_effect]}")
    lines.append("候选动作（冻结贪心下游独立MC评价）:")
    for action, stats in sorted(
            recommendation.reports.items(), key=lambda item: -item[1].mean):
        label = format_action(context.phase, action)
        if isinstance(action, int):
            label += f" {node_names.get(action, '')}"
        win = "" if stats.win_rate is None else f" 胜率={stats.win_rate * 100:.4f}%"
        mark = " <-- 推荐" if action == recommendation.recommended_action else ""
        lines.append(f"  {label}: mean={stats.mean:.3f} n={stats.count}{win}{mark}")
    return "\n".join(lines)


def analyze_single_map(image_path: str = None, *, nodes: list = None,
                       edges: dict = None, start_idx: int = None,
                       infectable: set = None, cheat: int = 0,
                       reroll: int = 0, initial_countdown: int = 0,
                       observed_effect: int = None,
                       effect_state: str = "unlocked", plane: int = None,
                       future_table: dict = None, target_cd: float = None,
                       n_train: int = 15_000, n_eval: int = None,
                       n_sim_trials: int = 2_000,
                       use_cache: bool = True, label: str = "",
                       verbose: bool = True, match_mode: int = 1) -> dict:
    """以旧参数名执行一次当前状态纯 MC 推荐。

    ``target_cd`` 只统计候选胜率，推荐目标仍是最大化平均最终倒计时。
    ``future_table`` 和 ``use_cache`` 为兼容旧调用而接收，但在线当前图不会使用。
    """
    del use_cache
    if future_table:
        raise ValueError("当前位面纯 MC 不接受 future_table，避免泄露未来地图")
    if image_path:
        prepared = load_countdown_map(image_path, plane or 1, match_mode)
        model, raw_nodes = prepared.model, list(prepared.model.nodes)
        raw_edges = {node: list(targets) for node, targets in model.edges.items()}
        infected = {idx for idx in model.node_map if (model.initial_infected >> idx) & 1}
        label = label or os.path.basename(image_path)
    elif nodes is not None and edges is not None and start_idx is not None and infectable is not None:
        raw_nodes, raw_edges, infected = nodes, edges, set(infectable)
        model = CountdownMap(nodes, edges, start_idx, infected)
        label = label or f"{len(nodes)}节点图"
    else:
        raise ValueError("必须提供 image_path 或 (nodes, edges, start_idx, infectable)")

    config = MCConfig(
        control_rollouts=n_train,
        evaluation_rollouts=n_sim_trials,
        min_visits=max(5, min(200, n_train // 20)),
    )
    session = CountdownSession(model, cheat, reroll, initial_countdown, config.seed)
    recommendations_by_effect = None
    if effect_state == "locked":
        if observed_effect not in EFFECT_NAMES:
            raise ValueError("locked 状态必须提供 1..6 的 observed_effect")
        session.set_observed_effect(observed_effect)
        context = session.context
    elif effect_state == "settled":
        if observed_effect not in EFFECT_NAMES:
            raise ValueError("settled 状态必须提供 1..6 的 observed_effect")
        # settled 表示调用者传入的 mask/CD 已经包含效果结果，路径阶段不得重复结算对症。
        context = DecisionContext(PHASE_PATH, session.state)
    elif effect_state == "unlocked":
        context = None
    else:
        raise ValueError("effect_state 必须是 unlocked / locked / settled")

    node_names = {int(node["idx"]): node.get("name", "") for node in raw_nodes}
    controller = MonteCarloController(model, config)
    if context is None:
        recommendations_by_effect, lines = {}, [
            "首个实际效果尚未出现：不存在可提前执行的单一动作。",
            "以下为六种等概率实际效果出现后的条件最优策略：",
        ]
        per_effect_control = max(1, (n_train + len(ALL_EFFECTS) - 1) // len(ALL_EFFECTS))
        contexts = [DecisionContext(PHASE_EFFECT, session.state, observed_effect=effect)
                    for effect in ALL_EFFECTS]
        controller.config = MCConfig(
            control_rollouts=per_effect_control,
            evaluation_rollouts=1,
            min_visits=config.min_visits,
            epsilon_start=config.epsilon_start,
            epsilon_end=config.epsilon_end,
            seed=config.seed,
        ).normalized()
        for conditional in contexts:
            controller.refine_current_state(conditional)

        action_total = sum(len(controller.legal_actions(item)) for item in contexts)
        per_action_samples = max(
            1, int(n_sim_trials if n_eval is None else n_eval) // max(action_total, 1))
        for effect, conditional in zip(ALL_EFFECTS, contexts):
            action_count = len(controller.legal_actions(conditional))
            controller.config = MCConfig(
                control_rollouts=1,
                evaluation_rollouts=per_action_samples * action_count,
                min_visits=config.min_visits,
                epsilon_start=config.epsilon_start,
                epsilon_end=config.epsilon_end,
                seed=config.seed,
            ).normalized()
            conditional_rec = controller.evaluate_current_policy(conditional, target_cd)
            recommendations_by_effect[effect] = conditional_rec
            report = conditional_rec.reports[conditional_rec.recommended_action]
            win = "" if report.win_rate is None else f"，胜率 {report.win_rate * 100:.4f}%"
            lines.append(
                f"  {EFFECT_NAMES[effect]}: "
                f"{format_action(PHASE_EFFECT, conditional_rec.recommended_action)}，"
                f"平均最终CD {report.mean:.3f}{win}")
        controller.config = config
        selected = controller.evaluate_unobserved_effect_policy(
            session.state,
            {effect: item.recommended_action
             for effect, item in recommendations_by_effect.items()},
            n_sim_trials, target_cd)
        recommendation = None
        decision_analysis = "\n".join(lines)
        recommended_action = "等待实际效果，再执行对应条件策略"
    else:
        recommendation = controller.recommend(context, target_cd)
        selected = recommendation.reports[recommendation.recommended_action]
        decision_analysis = _decision_text(context, recommendation, node_names)
        recommended_action = format_action(context.phase, recommendation.recommended_action)
    evaluation = {
        "mean": selected.mean,
        "std": selected.std,
        "min": selected.minimum,
        "max": selected.maximum,
        "n_rollouts": selected.count,
    }
    if verbose:
        print(f"\n{'=' * 60}\n单图纯MC分析: {label}\n{'=' * 60}")
        print(decision_analysis)
        print(f"推荐: {recommended_action}")
        print(f"平均最终CD={selected.mean:.3f} ± {selected.std:.3f}")
        if selected.win_rate is not None:
            print(f"目标{target_cd}: {selected.wins}/{selected.target_count}，"
                  f"胜率={selected.win_rate * 100:.4f}%")
    return {
        "label": label,
        "nodes": raw_nodes,
        "edges": raw_edges,
        "start_idx": model.start_idx,
        "infectable": infected,
        "sim": model,
        "mc": controller,
        "w_table": None,
        "eval": evaluation,
        "eval_zero": None,
        "resource_gain": None,
        "recommended_action": recommended_action,
        "decision_analysis": decision_analysis,
        "recommendation": recommendation,
        "recommendations_by_effect": recommendations_by_effect,
        "conditional_evaluation_rollouts": sum(
            item.evaluation_rollouts for item in recommendations_by_effect.values())
            if recommendations_by_effect else None,
        "win_rate": selected.win_rate,
        "target_cd": target_cd,
        "num_q_states": len(controller.q),
        "future_table": None,
    }


__all__ = [
    "ExactCountdownDP", "MapSimulator", "MonteCarloOptimizer",
    "analyze_single_map",
]
