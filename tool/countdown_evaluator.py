"""倒计时最大化的生产规则、蒙特卡洛评估与决策接口。

本模块不依赖 Qt、OpenCV、GUI 或项目图像缓存；生产程序只需传入识别后的地图、
画面事实与资源，随机结算仍以游戏画面为准。
"""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping, Optional


EFFECT_SPREAD = 1
EFFECT_BONUS = 2
EFFECT_ADJACENT = 3
EFFECT_SELECT = 4
EFFECT_RANDOM_INFECT = 5
EFFECT_NOTHING = 6
ALL_EFFECTS = tuple(range(1, 7))
EFFECT_NAMES = {
    EFFECT_SPREAD: "浇灌",
    EFFECT_BONUS: "为善",
    EFFECT_ADJACENT: "对症",
    EFFECT_SELECT: "慈怀",
    EFFECT_RANDOM_INFECT: "归心",
    EFFECT_NOTHING: "可憎",
}
EFFECT_TEXT_ALIASES = {
    EFFECT_SPREAD: ("浇灌",),
    EFFECT_BONUS: ("为善",),
    EFFECT_ADJACENT: ("对症",),
    EFFECT_SELECT: ("慈怀",),
    EFFECT_RANDOM_INFECT: ("归心",),
    EFFECT_NOTHING: ("可憎",),
}
# 作弊界面各效果按钮上实际显示的文字，与骰子结果文本（EFFECT_TEXT_ALIASES）分开：
# 慈怀的作弊按钮写「选择」，而骰子结果文本是「慈怀」。
EFFECT_CHEAT_TEXT = {
    EFFECT_SPREAD: "浇灌",
    EFFECT_BONUS: "为善",
    EFFECT_ADJACENT: "对症",
    EFFECT_SELECT: "选择",
    EFFECT_RANDOM_INFECT: "归心",
    EFFECT_NOTHING: "可憎",
}
_EFFECT_ALIASES = {name: effect for effect, names in EFFECT_TEXT_ALIASES.items()
                   for name in names}

PHASE_EFFECT = "effect"
PHASE_TARGET = "target"
PHASE_PATH = "path"
PHASE_TERMINAL = "terminal"

DECISION_MC = "mc"
DECISION_WIN_RATE = "win_rate"
DECISION_WIN_RATE_DP = "win_rate_dp"
DECISION_DP = "dp"

CAMPAIGN_DEFAULT_TARGETS = (15.0, 75.0, 80.0)
DEFAULT_MAP_FILES = (
    "test1.png",
    "test2.png",
    "test3.png",
)

# 路径节点只获得极小的偏好补正：用于区分几乎等价的 MC 结果，不覆盖实际 CD 收益。
_PATH_SCORE_BONUS_FIELD = {
    "reward": "path_reward_bonus", "reward2": "path_reward_bonus",
    "event": "path_event_bonus",
    "trade": "path_trade_bonus", "trade2": "path_trade_bonus",
    "adventure": "path_adventure_bonus",
    "bugevent": "path_bugevent_bonus",
}


def parse_effect_text(text: str) -> Optional[int]:
    """从游戏 OCR 文本中识别六种效果，无法确认时返回 ``None``。"""
    normalized = "".join(str(text or "").split())
    return next((effect for name, effect in _EFFECT_ALIASES.items()
                 if name in normalized), None)


@dataclass(frozen=True, slots=True)
class CountdownState:
    """一张地图内的完整事实状态。"""

    node_idx: int
    infected: int
    countdown: int
    cheat_rem: int
    reroll_rem: int


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """当前需要用户或策略作出的单一决策。"""

    phase: str
    state: CountdownState
    observed_effect: Optional[int] = None
    locked_effect: Optional[int] = None


@dataclass(slots=True)
class MCSampleStats:
    """常数空间的在线样本统计；不会在 200 条处截断。"""

    count: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    wins: int = 0
    target_count: int = 0
    minimum: float = math.inf
    maximum: float = -math.inf

    def append(self, value: float, target: Optional[float] = None) -> None:
        value = float(value)
        self.count += 1
        self.total += value
        self.total_sq += value * value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        if target is not None:
            self.target_count += 1
            self.wins += int(value >= target)

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else float("-inf")

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        variance = (self.total_sq - self.total * self.total / self.count) / (self.count - 1)
        return max(variance, 0.0) ** 0.5

    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / self.target_count if self.target_count else None


@dataclass(frozen=True, slots=True)
class MCConfig:
    """当前状态控制与独立评价预算。"""

    control_rollouts: int = 10_000
    evaluation_rollouts: int = 10_000
    min_visits: int = 2000
    epsilon_start: float = 0.35
    epsilon_end: float = 0.03
    seed: int = 20260802
    win_rate_noise_floor_percent: float = 0.2
    path_reward_bonus: float = 0.0008
    path_event_bonus: float = 0.0004
    path_trade_bonus: float = 0.0003
    path_adventure_bonus: float = 0.0002
    path_bugevent_bonus: float = 0.0001

    def normalized(self) -> "MCConfig":
        return MCConfig(
            control_rollouts=max(1, int(self.control_rollouts)),
            evaluation_rollouts=max(1, int(self.evaluation_rollouts)),
            min_visits=max(1, int(self.min_visits)),
            epsilon_start=min(max(float(self.epsilon_start), 0.0), 1.0),
            epsilon_end=min(max(float(self.epsilon_end), 0.0), 1.0),
            seed=int(self.seed),
            win_rate_noise_floor_percent=min(
                max(float(self.win_rate_noise_floor_percent), 0.0), 100.0),
            path_reward_bonus=float(self.path_reward_bonus),
            path_event_bonus=float(self.path_event_bonus),
            path_trade_bonus=float(self.path_trade_bonus),
            path_adventure_bonus=float(self.path_adventure_bonus),
            path_bugevent_bonus=float(self.path_bugevent_bonus),
        )


@dataclass(frozen=True, slots=True)
class MCRecommendation:
    """同一批结构化结果同时驱动日志、图例和按钮推荐。"""

    context: DecisionContext
    reports: Mapping[object, MCSampleStats]
    recommended_action: object
    highest_win_action: object
    control_rollouts: int
    evaluation_rollouts: int
    win_reports: Optional[Mapping[object, MCSampleStats]] = None


class CountdownMap:
    """DAG 地图与唯一的业务状态转移实现。"""

    def __init__(self, nodes: Iterable[Mapping], edges: Mapping[int, Iterable[int]],
                 start_idx: int, infected_indices: Iterable[int], column_tolerance: float = 30.0):
        copied = [dict(node) for node in nodes]
        self.nodes = tuple(copied)
        self.node_map = {int(node["idx"]): node for node in copied}
        if len(self.node_map) != len(copied):
            raise ValueError("节点 idx 必须唯一")
        if start_idx not in self.node_map:
            raise ValueError(f"起点 #{start_idx} 不存在")
        self.start_idx = int(start_idx)
        self.edges = {idx: tuple(int(dst) for dst in edges.get(idx, ())) for idx in self.node_map}
        for src, targets in self.edges.items():
            unknown = [dst for dst in targets if dst not in self.node_map]
            if unknown:
                raise ValueError(f"节点 #{src} 指向不存在节点 {unknown}")
        self.initial_infected = sum(1 << idx for idx in set(map(int, infected_indices)) if idx in self.node_map)

        ordered = sorted(self.nodes, key=lambda node: (float(node["cx"]), float(node.get("cy", 0))))
        self.columns = {}
        column, previous_x = 0, None
        for node in ordered:
            x = float(node["cx"])
            if previous_x is not None and x - previous_x > column_tolerance:
                column += 1
            self.columns[int(node["idx"])] = column
            previous_x = x

        self.destroy_masks = {}
        for node_idx, node_column in self.columns.items():
            self.destroy_masks[node_idx] = sum(
                1 << other for other, other_column in self.columns.items()
                if other_column <= node_column)
        node_mask = sum(1 << idx for idx in self.node_map)
        self.future_masks = {
            idx: node_mask & ~destroyed
            for idx, destroyed in self.destroy_masks.items()
        }

        predecessors = defaultdict(set)
        for src, targets in self.edges.items():
            for target in targets:
                predecessors[target].add(src)
        self.neighbors = {
            idx: tuple(sorted(set(self.edges[idx]) | predecessors[idx]))
            for idx in self.node_map
        }
        self.neighbor_masks = {
            idx: sum(1 << neighbor for neighbor in neighbors)
            for idx, neighbors in self.neighbors.items()
        }
        self._effect_actions = {
            (effect, has_cheat, has_reroll): tuple(
                ["keep"]
                + ([("cheat", candidate) for candidate in ALL_EFFECTS
                    if candidate != effect] if has_cheat else [])
                + (["reroll"] if has_reroll else []))
            for effect in ALL_EFFECTS
            for has_cheat in (False, True)
            for has_reroll in (False, True)
        }
        self._longest_steps = {}

    def initial_state(self, cheat: int, reroll: int, countdown: int = 15) -> CountdownState:
        return CountdownState(self.start_idx, self.initial_infected, int(countdown),
                              max(0, int(cheat)), max(0, int(reroll)))

    def is_terminal(self, state: CountdownState) -> bool:
        return not self.edges.get(state.node_idx)

    def path_options(self, state: CountdownState) -> tuple[int, ...]:
        return self.edges.get(state.node_idx, ())

    def legal_actions(self, context: DecisionContext) -> tuple:
        state = context.state
        if context.phase == PHASE_EFFECT:
            if context.observed_effect not in ALL_EFFECTS:
                raise ValueError("效果决策阶段必须有已观察效果")
            return self._effect_actions[
                (context.observed_effect, bool(state.cheat_rem), bool(state.reroll_rem))]
        if context.phase == PHASE_TARGET:
            return self.infection_targets(state)
        return self.path_options(state) if context.phase == PHASE_PATH else ()

    def active_infected_count(self, state: CountdownState) -> int:
        return (state.infected & self.future_masks[state.node_idx]).bit_count()

    def infection_targets(self, state: CountdownState) -> tuple[int, ...]:
        available = self.future_masks[state.node_idx] & ~state.infected
        targets = []
        while available:
            bit = available & -available
            targets.append(bit.bit_length() - 1)
            available ^= bit
        return tuple(targets)

    def settle_effect(self, state: CountdownState, effect: int, rng: random.Random,
                      target: Optional[int] = None) -> CountdownState:
        """结算不依赖路径的效果；对症效果留到选路时结算。"""
        if effect not in ALL_EFFECTS:
            raise ValueError(f"未知效果: {effect}")
        if effect == EFFECT_ADJACENT:
            return state

        mask, countdown = state.infected, state.countdown
        destroyed = self.destroy_masks[state.node_idx]
        if effect == EFFECT_BONUS:
            countdown += (mask & ~destroyed).bit_count()
        elif effect == EFFECT_SELECT:
            if target not in self.infection_targets(state):
                raise ValueError(f"节点 #{target} 不是可用的慈怀目标")
            mask |= 1 << target
        elif effect == EFFECT_RANDOM_INFECT:
            candidates = self.infection_targets(state)
            if candidates:
                mask |= 1 << candidates[rng.randrange(len(candidates))]
        elif effect == EFFECT_SPREAD:
            base_mask = mask
            sources = base_mask & self.future_masks[state.node_idx]
            while sources:
                source_bit = sources & -sources
                source = source_bit.bit_length() - 1
                candidates = (self.neighbor_masks[source]
                              & self.future_masks[state.node_idx] & ~base_mask)
                if candidates:
                    selected = rng.randrange(candidates.bit_count())
                    for _ in range(selected):
                        candidates &= candidates - 1
                    mask |= candidates & -candidates
                sources ^= source_bit
        return CountdownState(state.node_idx, mask, countdown,
                              state.cheat_rem, state.reroll_rem)

    def move(self, state: CountdownState, next_node: int,
             locked_effect: Optional[int] = None) -> CountdownState:
        """按“效果→移动判分→销毁目标列”的顺序完成一次移动。"""
        if next_node not in self.path_options(state):
            raise ValueError(f"节点 #{next_node} 不是当前可选路径")
        mask = state.infected
        if locked_effect == EFFECT_ADJACENT:
            already_destroyed = self.destroy_masks[state.node_idx]
            mask |= sum(1 << neighbor for neighbor in self.neighbors[next_node]
                        if not (already_destroyed >> neighbor) & 1)
        countdown = state.countdown + (1 if (mask >> next_node) & 1 else -3)
        return CountdownState(next_node, mask & ~self.destroy_masks[next_node], countdown,
                              state.cheat_rem, state.reroll_rem)

    def longest_steps_from(self, node_idx: int) -> int:
        if node_idx in self._longest_steps:
            return self._longest_steps[node_idx]
        visiting = set()

        def visit(node: int) -> int:
            if node in self._longest_steps:
                return self._longest_steps[node]
            if node in visiting:
                raise ValueError("地图包含环，倒计时模拟仅支持 DAG")
            visiting.add(node)
            value = 0 if not self.edges[node] else 1 + max(visit(dst) for dst in self.edges[node])
            visiting.remove(node)
            self._longest_steps[node] = value
            return value

        return visit(node_idx)


class MonteCarloController:
    """从当前精确状态续采样，并用独立批次评价冻结策略。"""

    def __init__(self, countdown_map: CountdownMap, config: Optional[MCConfig] = None):
        self.map = countdown_map
        self.config = (config or MCConfig()).normalized()
        self.q = defaultdict(MCSampleStats)
        self.win_q = defaultdict(MCSampleStats)
        self.frozen_policy = {}
        self.frozen_win_policy = {}
        self.win_target = None
        self._effect_heuristic_cache = {}
        self.total_control_rollouts = 0
        self.total_evaluation_trials = 0
        self._sampled_contexts = {}

    def _state_key(self, state: CountdownState) -> tuple:
        # 均分目标对当前 CD 线性可加；Q 回填后续累计回报后可安全去掉该维度。
        # 均分 Q 不使用目标；目标只进入独立胜率策略，不污染均分表。
        useful_cheat = min(
            state.cheat_rem, self.map.longest_steps_from(state.node_idx))
        return (state.node_idx,
                state.infected & ~self.map.destroy_masks[state.node_idx],
                useful_cheat, state.reroll_rem)

    def _context_key(self, context: DecisionContext) -> tuple:
        # 路径阶段的普通效果已结算进事实状态，只有对症仍影响下一次移动。
        locked = None
        if context.phase == PHASE_PATH:
            locked = context.locked_effect == EFFECT_ADJACENT
        state_key = self._state_key(context.state)
        if context.phase in (PHASE_TARGET, PHASE_PATH):
            remaining = max(0, self.map.longest_steps_from(context.state.node_idx) - 1)
            state_key = state_key[:2] + (min(state_key[2], remaining), state_key[3])
        return (context.phase, state_key,
                context.observed_effect if context.phase == PHASE_EFFECT else None,
                locked)

    def _win_context_key(self, context: DecisionContext) -> tuple:
        # 达标概率取决于当前绝对 CD，不能像均分回报那样省略该维度。
        state = context.state
        key = self._context_key(context)
        useful_cheat = key[1][2]
        normalized = (
            state.node_idx,
            state.infected & ~self.map.destroy_masks[state.node_idx],
            state.countdown, useful_cheat, state.reroll_rem)
        return (context.phase, normalized, key[2], key[3])

    def _q_key(self, context: DecisionContext, action: object) -> tuple:
        # 已选效果及付费后的状态相同，就不应按原骰面拆散样本。
        if context.phase == PHASE_EFFECT and action != "reroll":
            effect = context.observed_effect if action == "keep" else int(action[1])
            state = context.state
            if action != "keep":
                state = replace(state, cheat_rem=state.cheat_rem - 1)
            settled_key = self._context_key(DecisionContext(PHASE_PATH, state))[1]
            return ("settle", settled_key, effect)
        return self._context_key(context) + (action,)

    def _win_q_key(self, context: DecisionContext, action: object) -> tuple:
        if context.phase == PHASE_EFFECT and action != "reroll":
            return self._q_key(context, action) + (context.state.countdown,)
        return self._win_context_key(context) + (action,)

    def legal_actions(self, context: DecisionContext) -> tuple:
        return self.map.legal_actions(context)

    def _advance(self, context: DecisionContext, action: object,
                 rng: random.Random, validate: bool = True) -> DecisionContext:
        state = context.state
        if validate and action not in self.legal_actions(context):
            raise ValueError(f"{action!r} 不是 {context.phase} 阶段的合法动作")
        if context.phase == PHASE_EFFECT:
            if action == "reroll":
                rerolled = CountdownState(
                    state.node_idx, state.infected, state.countdown,
                    state.cheat_rem, state.reroll_rem - 1)
                return DecisionContext(PHASE_EFFECT, rerolled, rng.randint(1, 6))
            if action == "keep":
                locked, paid = context.observed_effect, state
            else:
                locked = int(action[1])
                paid = CountdownState(
                    state.node_idx, state.infected, state.countdown,
                    state.cheat_rem - 1, state.reroll_rem)
            if locked == EFFECT_SELECT:
                targets = self.map.infection_targets(paid)
                if targets:
                    return DecisionContext(PHASE_TARGET, paid, locked_effect=locked)
                return DecisionContext(PHASE_PATH, paid, locked_effect=locked)
            settled = self.map.settle_effect(paid, locked, rng)
            return DecisionContext(PHASE_PATH, settled, locked_effect=locked)
        if context.phase == PHASE_TARGET:
            settled = self.map.settle_effect(state, EFFECT_SELECT, rng, int(action))
            return DecisionContext(PHASE_PATH, settled, locked_effect=EFFECT_SELECT)
        if context.phase == PHASE_PATH:
            moved = self.map.move(state, int(action), context.locked_effect)
            if self.map.is_terminal(moved):
                return DecisionContext(PHASE_TERMINAL, moved)
            return DecisionContext(PHASE_EFFECT, moved, rng.randint(1, 6))
        return context

    @staticmethod
    def _action_sort_key(action: object) -> tuple:
        if action == "keep":
            return (0, 0)
        if action == "reroll":
            return (2, 0)
        if isinstance(action, tuple):
            return (1, int(action[1]))
        return (0, int(action))

    def _score_bonus(self, context: DecisionContext, action: object) -> float:
        if context.phase != PHASE_PATH:
            return 0.0
        field = _PATH_SCORE_BONUS_FIELD.get(
            str(self.map.node_map[int(action)].get("name", "")))
        return getattr(self.config, field) if field else 0.0

    def _heuristic(self, context: DecisionContext, action: object) -> float:
        state = context.state
        if context.phase == PHASE_EFFECT:
            effect = context.observed_effect if action == "keep" else (
                None if action == "reroll" else int(action[1]))
            key = state.node_idx, state.infected & self.map.future_masks[state.node_idx]
            values = self._effect_heuristic_cache.get(key)
            if values is None:
                remaining = max(1, self.map.longest_steps_from(state.node_idx))
                active, future = self.map.active_infected_count(state), key[1]
                sources, probabilities = future, defaultdict(float)
                while sources:
                    source_bit = sources & -sources
                    source = source_bit.bit_length() - 1
                    candidates = self.map.neighbor_masks[source] & self.map.future_masks[
                        state.node_idx] & ~state.infected
                    if candidates:
                        probability = 1.0 / candidates.bit_count()
                        while candidates:
                            bit = candidates & -candidates
                            target = bit.bit_length() - 1
                            probabilities[target] = 1 - (
                                1 - probabilities[target]) * (1 - probability)
                            candidates ^= bit
                    sources ^= source_bit
                adjacent_gain = max((
                    (self.map.neighbor_masks[next_node]
                     & ~self.map.destroy_masks[next_node]
                     & ~state.infected).bit_count()
                    for next_node in self.map.path_options(state)), default=0)
                harvest_steps = max(remaining - 1, 0)
                has_target = bool(self.map.infection_targets(state))
                values = (
                    (active + sum(probabilities.values())) * harvest_steps,
                    float(active * remaining),
                    float((active + adjacent_gain) * harvest_steps),
                    float((active + has_target) * harvest_steps),
                    float((active + has_target) * harvest_steps),
                    float(active * harvest_steps),
                )
                if len(self._effect_heuristic_cache) >= 8192:
                    self._effect_heuristic_cache.clear()
                self._effect_heuristic_cache[key] = values
            value = max(values) * 0.8 if effect is None else values[effect - 1]
            if isinstance(action, tuple):
                value -= 0.05
        elif context.phase == PHASE_TARGET:
            value = (4.0 if int(action) in self.map.path_options(state) else 0.0
                     ) + 0.05 * self.map.longest_steps_from(int(action))
        elif context.phase == PHASE_PATH:
            infected = bool((state.infected >> int(action)) & 1)
            value = ((1.0 if infected else -3.0)
                     + 0.05 * self.map.longest_steps_from(int(action)))
        else:
            value = 0.0
        return value

    def _greedy_action(self, context: DecisionContext,
                       policy_cache: Optional[dict] = None,
                       actions: Optional[tuple] = None,
                       context_key: Optional[tuple] = None) -> object:
        context_key = context_key or self._context_key(context)
        actions = actions or self.legal_actions(context)
        if not actions:
            return None
        cache_key = (False, context_key)
        if policy_cache is not None and cache_key in policy_cache:
            return policy_cache[cache_key]
        frozen = self.frozen_policy.get(context_key)
        if frozen in actions:
            selected = frozen
        else:
            scored = []
            best_score = float("-inf")
            for action in actions:
                q_key = self._q_key(context, action)
                samples = self.q.get(q_key)
                heuristic = self._heuristic(context, action)
                # 深层状态不能套用根节点的样本门槛；保留两次观测以免单次异常覆盖先验。
                reliable = min(2, self.config.min_visits)
                score = (samples.mean if samples and samples.count >= reliable
                         else heuristic) + self._score_bonus(context, action)
                scored.append((score, heuristic, action))
                if score > best_score:
                    best_score = score
            selected = selected_key = None
            for score, heuristic, action in scored:
                if abs(score - best_score) <= 1e-12:
                    tie_key = (-heuristic, self._action_sort_key(action))
                    if selected_key is None or tie_key < selected_key:
                        selected, selected_key = action, tie_key
        if policy_cache is not None:
            policy_cache[cache_key] = selected
        return selected

    def _greedy_win_action(self, context: DecisionContext,
                           policy_cache: Optional[dict] = None,
                           actions: Optional[tuple] = None,
                           context_key: Optional[tuple] = None) -> object:
        context_key = context_key or self._context_key(context)
        actions = actions or self.legal_actions(context)
        cache_key = (True, self._win_context_key(context))
        if policy_cache is not None and cache_key in policy_cache:
            return policy_cache[cache_key]
        if context.phase == PHASE_PATH and self.win_target is not None:
            terminal_wins = []
            for action in actions:
                successor = self._advance(
                    context, action, random.Random(0), False)
                if (successor.phase == PHASE_TERMINAL
                        and successor.state.countdown >= self.win_target):
                    terminal_wins.append((
                        successor.state.countdown
                        + self._score_bonus(context, action), action))
            if terminal_wins:
                selected = min(
                    terminal_wins,
                    key=lambda item: (-item[0], self._action_sort_key(item[1])))[1]
                if policy_cache is not None:
                    policy_cache[cache_key] = selected
                return selected
        selected = self.frozen_win_policy.get(cache_key[1])
        if selected in actions:
            if policy_cache is not None:
                policy_cache[cache_key] = selected
            return selected
        learned = [(action, self.win_q.get(self._win_q_key(context, action)))
                   for action in actions]
        # 成功轨迹不能因深层访问不足而被丢弃；是否可靠由后续独立续采验证。
        learned = [(action, stats) for action, stats in learned
                   if stats and stats.target_count]
        noise_floor = self.config.win_rate_noise_floor_percent / 100.0
        winners = [(action, stats) for action, stats in learned
                   if (stats.win_rate or 0.0) >= noise_floor
                   and (stats.win_rate or 0.0) > 0.0]
        if winners:
            selected = min(winners, key=lambda item: (
                -item[1].win_rate,
                -item[1].mean - self._score_bonus(context, item[0]),
                self._action_sort_key(item[0])))[0]
        elif learned:
            # 已访问状态尚未采到有效成功时，与根决策一致退回均分策略。
            selected = self._greedy_action(
                context, policy_cache, actions, context_key)
        else:
            selected = self._greedy_action(
                context, policy_cache, actions, context_key)
        if policy_cache is not None:
            policy_cache[cache_key] = selected
        return selected

    def _rollout(self, initial: DecisionContext, rng: random.Random,
                 epsilon: float = 0.0, forced_action: object = None,
                 learn: bool = False, learn_win: bool = False,
                 win_policy: bool = False,
                 policy_cache: Optional[dict] = None) -> float:
        context, first = initial, True
        trace = [] if learn else None
        win_trace = [] if learn_win else None
        max_decisions = len(self.map.nodes) * 4 + initial.state.reroll_rem + 32
        for _ in range(max_decisions):
            if context.phase == PHASE_TERMINAL:
                break
            context_key = self._context_key(context)
            actions = self.legal_actions(context)
            if not actions:
                context = DecisionContext(PHASE_TERMINAL, context.state)
                break
            if learn or learn_win:
                key = self._win_context_key(context)
                entry = self._sampled_contexts.setdefault(key, [context, 0])
                entry[1] += 1
            if first and forced_action is not None:
                action = forced_action
            elif epsilon and rng.random() < epsilon:
                action = actions[rng.randrange(len(actions))]
            else:
                action = (self._greedy_win_action(
                    context, policy_cache, actions, context_key) if win_policy
                    else self._greedy_action(
                        context, policy_cache, actions, context_key))
            if learn:
                trace.append((self._q_key(context, action), context.state.countdown))
            if learn_win:
                win_trace.append(self._win_q_key(context, action))
            context = self._advance(context, action, rng, False)
            first = False
        else:
            raise RuntimeError("单次模拟超过安全决策上限，地图可能含环或状态转移异常")
        final_countdown = float(context.state.countdown)
        if learn:
            for key, countdown_at_decision in trace:
                self.q[key].append(final_countdown - countdown_at_decision)
        if learn_win:
            for key in win_trace:
                self.win_q[key].append(final_countdown, self.win_target)
        return final_countdown

    def _refine_with_budget(self, context: DecisionContext, total: int,
                            progress: Optional[Callable[[int, int, str], None]] = None,
                            cancelled: Optional[Callable[[], bool]] = None,
                            label: str = "当前状态控制采样",
                            train_win: bool = False) -> int:
        actions = self.legal_actions(context)
        if not actions:
            return 0
        config = self.config
        total = max(len(actions) * (2 if train_win else 1), int(total))
        base_seed = config.seed + self.total_control_rollouts * 104_729
        completed = sequence = 0
        last_progress = time.perf_counter()

        def sample(initial, budget, win_policy):
            nonlocal completed, last_progress, sequence
            if budget <= 0:
                return
            current_actions = self.legal_actions(initial)
            if win_policy:
                current_actions = tuple(sorted(
                    current_actions,
                    key=lambda action: self.win_q[
                        self._win_q_key(initial, action)].count))
            rng = random.Random(
                base_seed + sequence * 1_000_003
                + (900_000_007 if win_policy else 0))
            sequence += 1
            for index in range(budget):
                if cancelled and cancelled():
                    return
                fraction = index / max(budget - 1, 1)
                epsilon = (config.epsilon_start
                           + (config.epsilon_end - config.epsilon_start) * fraction)
                action = current_actions[index % len(current_actions)]
                self._rollout(
                    initial, rng, epsilon=epsilon, forced_action=action,
                    learn=not win_policy, learn_win=win_policy,
                    win_policy=win_policy)
                completed += 1
                if progress:
                    now = time.perf_counter()
                    if completed == total or now - last_progress >= 0.1:
                        progress(completed, total, label)
                        last_progress = now

        if not train_win:
            sample(context, total, False)
        else:
            mean_budget, win_budget = (total + 1) // 2, total // 2
            sample(context, mean_budget, False)
            sample(context, win_budget, True)
        if progress and completed != total:
            progress(completed, total, label)
        self.total_control_rollouts += completed
        return completed

    def refine_current_state(self, context: DecisionContext,
                             progress: Optional[Callable[[int, int, str], None]] = None,
                             cancelled: Optional[Callable[[], bool]] = None) -> int:
        """只从当前确定状态采样，并强制均衡覆盖每个根动作。"""
        actions = self.legal_actions(context)
        total = max(self.config.control_rollouts, self.config.min_visits * len(actions))
        return self._refine_with_budget(context, total, progress, cancelled)

    def evaluate_actions(self, context: DecisionContext, target: Optional[float] = None,
                         progress: Optional[Callable[[int, int, str], None]] = None,
                         cancelled: Optional[Callable[[], bool]] = None,
                         rollouts: Optional[int] = None,
                         win_policy: bool = False) -> tuple[dict, int]:
        """强制各根动作，冻结下游策略，以独立且等量的样本作最终比较。"""
        actions = self.legal_actions(context)
        if not actions:
            return {}, 0
        budget = self.config.evaluation_rollouts if rollouts is None else max(1, int(rollouts))
        per_action = max(1, budget // len(actions))
        total = per_action * len(actions)
        reports = {action: MCSampleStats() for action in actions}
        completed, rng, policy_cache = 0, random.Random(0), {}
        last_progress = time.perf_counter()
        # 相同评价轮次使用相同随机种子，减少候选间环境噪声。
        for _trial in range(per_action):
            seed = self._next_evaluation_seed()
            rng.seed(seed)
            common_state = rng.getstate()
            for action in actions:
                if cancelled and cancelled():
                    return reports, completed
                rng.setstate(common_state)
                value = self._rollout(
                    context, rng, forced_action=action,
                    win_policy=win_policy, policy_cache=policy_cache)
                reports[action].append(value, target)
                completed += 1
                if progress:
                    now = time.perf_counter()
                    if completed == total or now - last_progress >= 0.1:
                        progress(completed, total, "冻结策略独立评价")
                        last_progress = now
        return reports, completed

    def _next_evaluation_seed(self) -> int:
        seed = self.config.seed + 500_000_003 + self.total_evaluation_trials * 130_363
        self.total_evaluation_trials += 1
        return seed

    def _freeze_action(self, context: DecisionContext, action: object,
                       win_policy: bool = False) -> None:
        policy = self.frozen_win_policy if win_policy else self.frozen_policy
        key = self._win_context_key if win_policy else self._context_key
        policy[key(context)] = action
        # 剩余作弊足够覆盖每一步时，骰面不限制可选效果；共享同一条件策略。
        if (context.phase == PHASE_EFFECT and context.state.cheat_rem
                >= self.map.longest_steps_from(context.state.node_idx)):
            effect = context.observed_effect if action == "keep" else (
                None if action == "reroll" else action[1])
            for observed in ALL_EFFECTS:
                equivalent = replace(context, observed_effect=observed)
                policy[key(equivalent)] = ("reroll" if effect is None else
                                          "keep" if effect == observed else ("cheat", effect))

    def evaluate_current_policy(
            self, context: DecisionContext, target: Optional[float] = None,
            progress: Optional[Callable[[int, int, str], None]] = None,
            cancelled: Optional[Callable[[], bool]] = None,
            control_rollouts: int = 0,
            evaluation_rollouts: Optional[int] = None) -> MCRecommendation:
        """不再训练，分别评价均分策略与目标胜率策略。"""
        actions = self.legal_actions(context)
        budget = (self.config.evaluation_rollouts if evaluation_rollouts is None
                  else max(1, int(evaluation_rollouts)))
        mean_budget = budget if target is None else max(len(actions), budget // 2)
        reports, evaluated = self.evaluate_actions(
            context, target, progress, cancelled, mean_budget)
        if not reports or not any(report.count for report in reports.values()):
            raise RuntimeError("当前状态没有完成任何候选评价")
        if evaluated != max(1, mean_budget // len(actions)) * len(actions):
            raise InterruptedError("均分策略评价已取消")
        ranked = sorted((action for action, report in reports.items() if report.count),
                        key=lambda action: (-reports[action].mean
                                            - self._score_bonus(context, action),
                                            self._action_sort_key(action)))
        if target is None:
            self._freeze_action(context, ranked[0])
            return MCRecommendation(context, reports, ranked[0], ranked[0],
                                    int(control_rollouts), evaluated)

        # 两套策略均须公平覆盖所有动作；极小预算不足时，最低成本为每套每动作一次。
        win_budget = max(len(actions), budget - mean_budget)
        win_reports, win_evaluated = self.evaluate_actions(
            context, target, progress, cancelled, win_budget, True)
        if win_evaluated != max(1, win_budget // len(actions)) * len(actions):
            raise InterruptedError("胜率策略评价已取消")
        win_ranked = sorted(
            (action for action, report in win_reports.items()
            if report.target_count),
            key=lambda action: (-win_reports[action].win_rate,
                                -win_reports[action].mean
                                - self._score_bonus(context, action),
                                self._action_sort_key(action)))
        winner = win_ranked[0] if win_ranked else ranked[0]
        self._freeze_action(context, ranked[0])
        if win_ranked:
            self._freeze_action(context, winner, True)
        return MCRecommendation(
            context, reports, ranked[0], winner, int(control_rollouts),
            evaluated + win_evaluated, win_reports)

    def _sample_successor_contexts(self, context: DecisionContext) -> tuple:
        """只采本批实际遇到的一层后继；固定六次探测，不枚举未来状态。"""
        successors, seen = [], set()
        base_seed = self.config.seed + 700_000_003 + self.total_control_rollouts * 130_363
        for action in self.legal_actions(context):
            for probe, observed_effect in enumerate(ALL_EFFECTS):
                successor = self._advance(
                    context, action, random.Random(base_seed + probe * 104_729), False)
                if successor.phase == PHASE_EFFECT:
                    successor = replace(successor, observed_effect=observed_effect)
                actions = self.legal_actions(successor)
                if not actions:
                    continue
                if len(actions) == 1:
                    self.frozen_policy[self._context_key(successor)] = actions[0]
                    self.frozen_win_policy[self._win_context_key(successor)] = actions[0]
                elif successor not in seen:
                    seen.add(successor)
                    successors.append(successor)
        return tuple(successors)

    def _calibrate_successors(
            self, successors: tuple, target: Optional[float], control_budget: int,
            evaluation_budget: int,
            progress: Optional[Callable[[int, int, str], None]] = None,
            cancelled: Optional[Callable[[], bool]] = None) -> tuple[int, int]:
        """在预算内对实际访问的状态作完整 MC 续跑，先改进下游再评价上游。"""
        if not successors:
            return 0, 0
        weights = [len(self.legal_actions(item)) for item in successors]
        weight_sum = sum(weights)

        def allocate(total):
            total = max(weight_sum, int(total))
            base, remainder = divmod(total, weight_sum)
            budgets = [base * weight for weight in weights]
            for index in range(remainder):
                budgets[index % len(budgets)] += 1
            return budgets

        trained = evaluated = 0
        for successor, budget in zip(successors, allocate(control_budget)):
            if cancelled and cancelled():
                return trained, evaluated
            trained += self._refine_with_budget(
                successor, budget, progress, cancelled, train_win=target is not None)
        evaluation_budgets = allocate(evaluation_budget // 2)
        remaining = evaluation_budget - sum(evaluation_budgets)
        selected = []
        grouped = {}
        for key, (successor, visits) in self._sampled_contexts.items():
            if (successor.phase == PHASE_EFFECT and successor.state.cheat_rem
                    >= self.map.longest_steps_from(successor.state.node_idx)):
                key = key[:2] + (None, key[3])
            entry = grouped.setdefault(key, [successor, 0])
            entry[1] += visits
        for successor, visits in sorted(grouped.values(), key=lambda item: -item[1]):
            # 每动作先作四次策略改进试采；展示值仍由最后的独立评价产生。
            cost = len(self.legal_actions(successor)) * 4
            if cost <= remaining:
                selected.append((successor, cost))
                remaining -= cost
        stages = {PHASE_EFFECT: 0, PHASE_TARGET: 1, PHASE_PATH: 2}
        selected.sort(key=lambda item: (
            self.map.longest_steps_from(item[0].state.node_idx),
            self._context_key(item[0])[1][2], item[0].state.reroll_rem, -stages[item[0].phase]))
        for successor, budget in selected:
            incumbent = (self._greedy_win_action(successor) if target is not None
                         else self._greedy_action(successor))
            reports, completed = self.evaluate_actions(
                successor, target, progress, cancelled,
                rollouts=budget, win_policy=target is not None)
            evaluated += completed
            if cancelled and cancelled():
                return trained, evaluated
            # 小批试采没有观察到胜率提升时，不因一次幸运高分改掉已有成功策略。
            winner = min(reports, key=lambda action: (
                -(reports[action].win_rate or 0.0),
                -int(action == incumbent and (reports[action].win_rate or 0.0) > 0),
                -reports[action].mean - self._score_bonus(successor, action),
                self._action_sort_key(action)))
            self._freeze_action(successor, winner, target is not None)
        if cancelled and cancelled():
            return trained, evaluated
        for successor, eval_budget in zip(successors, evaluation_budgets):
            if cancelled and cancelled():
                break
            evaluated += self.evaluate_current_policy(
                successor, target, progress, cancelled,
                evaluation_rollouts=eval_budget).evaluation_rollouts
        return trained, evaluated

    def evaluate_unobserved_effect_policy(
            self, state: CountdownState, first_actions: Mapping[int, object], rollouts: int,
            target: Optional[float] = None) -> MCSampleStats:
        """在效果尚未出现时，等概率抽取首效果并评价冻结条件策略。"""
        stats = MCSampleStats()
        rng, policy_cache = random.Random(0), {}
        for index in range(max(1, int(rollouts))):
            rng.seed(self._next_evaluation_seed())
            # 对首效果分层抽样，六种等概率分支覆盖均衡；后续环境随机仍逐次采样。
            effect = ALL_EFFECTS[index % len(ALL_EFFECTS)]
            context = DecisionContext(PHASE_EFFECT, state, effect)
            stats.append(self._rollout(
                context, rng, forced_action=first_actions[effect],
                policy_cache=policy_cache), target)
        return stats

    def recommend(self, context: DecisionContext, target: Optional[float] = None,
                  progress: Optional[Callable[[int, int, str], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None) -> MCRecommendation:
        normalized_target = None if target is None else float(target)
        self._sampled_contexts.clear()
        self.frozen_policy.clear()
        self.frozen_win_policy.clear()
        if normalized_target != self.win_target:
            self.win_q.clear()
            self.win_target = normalized_target
        successors = self._sample_successor_contexts(context)
        actions = self.legal_actions(context)
        if successors:
            root_control = max(self.config.min_visits * len(actions),
                               self.config.control_rollouts // 2)
            successor_control = max(
                sum(len(self.legal_actions(item)) for item in successors),
                self.config.control_rollouts - root_control)
            root_evaluation = max(len(actions), self.config.evaluation_rollouts // 4)
            successor_evaluation = max(
                sum(len(self.legal_actions(item)) for item in successors),
                self.config.evaluation_rollouts - root_evaluation)
        else:
            root_control = max(
                self.config.control_rollouts, self.config.min_visits * len(actions))
            successor_control = successor_evaluation = 0
            root_evaluation = self.config.evaluation_rollouts
        control = self._refine_with_budget(
            context, root_control, progress, cancelled,
            train_win=target is not None)
        branch_control, branch_evaluation = self._calibrate_successors(
            successors, target, successor_control, successor_evaluation,
            progress, cancelled)
        self._sampled_contexts.clear()
        recommendation = self.evaluate_current_policy(
            context, target, progress, cancelled,
            control_rollouts=control + branch_control,
            evaluation_rollouts=root_evaluation)
        return replace(
            recommendation,
            evaluation_rollouts=(recommendation.evaluation_rollouts
                                 + branch_evaluation))


class CountdownSession:
    """事实随机流、逐步操作和可反悔历史均由后端持有。"""

    def __init__(self, countdown_map: CountdownMap, cheat: int, reroll: int,
                 countdown: int = 15, seed: int = 20260802):
        self.map = countdown_map
        self.rng = random.Random(seed)
        self.state = countdown_map.initial_state(cheat, reroll, countdown)
        self.frames = []
        self.context = DecisionContext(PHASE_TERMINAL, self.state)
        self._step_before = self.state
        self._observations = []
        self._effect_actions = []
        self._locked_effect = None
        self._target = None
        self._begin_step()

    def _begin_step(self, observed_effect: Optional[int] = None) -> DecisionContext:
        if self.map.is_terminal(self.state):
            self.context = DecisionContext(PHASE_TERMINAL, self.state)
            return self.context
        observed = int(observed_effect or self.rng.randint(1, 6))
        if observed not in ALL_EFFECTS:
            raise ValueError("观察效果必须在 1..6")
        self._step_before = self.state
        self._observations = [observed]
        self._effect_actions = []
        self._locked_effect = None
        self._target = None
        self.context = DecisionContext(PHASE_EFFECT, self.state, observed)
        return self.context

    def set_observed_effect(self, effect: int) -> DecisionContext:
        """人工同步游戏内已经出现的效果，不消耗资源。"""
        if self.context.phase != PHASE_EFFECT:
            raise RuntimeError("只有效果选择阶段可以改写观察结果")
        if effect not in ALL_EFFECTS:
            raise ValueError("观察效果必须在 1..6")
        self._observations[-1] = int(effect)
        self.context = replace(self.context, observed_effect=int(effect))
        return self.context

    def choose_effect(self, action: object) -> DecisionContext:
        if self.context.phase != PHASE_EFFECT:
            raise RuntimeError("当前不是效果选择阶段")
        if action not in self.map.legal_actions(self.context):
            raise ValueError(f"非法效果动作: {action!r}")
        self._effect_actions.append(action)
        state = self.context.state
        if action == "reroll":
            state = replace(state, reroll_rem=state.reroll_rem - 1)
            observed = self.rng.randint(1, 6)
            self._observations.append(observed)
            self.state = state
            self.context = DecisionContext(PHASE_EFFECT, state, observed)
            return self.context

        locked = self.context.observed_effect if action == "keep" else int(action[1])
        if action != "keep":
            state = replace(state, cheat_rem=state.cheat_rem - 1)
        self._locked_effect = locked
        self.state = state
        if locked == EFFECT_SELECT:
            targets = self.map.infection_targets(state)
            if targets:
                self.context = DecisionContext(PHASE_TARGET, state, locked_effect=locked)
            else:
                self.context = DecisionContext(PHASE_PATH, state, locked_effect=locked)
        else:
            self.state = self.map.settle_effect(state, locked, self.rng)
            self.context = DecisionContext(PHASE_PATH, self.state, locked_effect=locked)
        return self.context

    def choose_target(self, target: int) -> DecisionContext:
        if self.context.phase != PHASE_TARGET:
            raise RuntimeError("当前不是慈怀目标选择阶段")
        self.state = self.map.settle_effect(self.context.state, EFFECT_SELECT, self.rng, target)
        self._target = int(target)
        self.context = DecisionContext(PHASE_PATH, self.state, locked_effect=EFFECT_SELECT)
        return self.context

    def choose_path(self, next_node: int) -> dict:
        if self.context.phase != PHASE_PATH:
            raise RuntimeError("当前不是路径选择阶段")
        path_context = self.context
        after = self.map.move(path_context.state, int(next_node), path_context.locked_effect)
        frame = {
            "index": len(self.frames),
            "display_node": self._step_before.node_idx,
            "state_before": self._step_before,
            "state_after_effect": path_context.state,
            "state_after": after,
            "observations": tuple(self._observations),
            "effect_actions": tuple(self._effect_actions),
            "locked_effect": self._locked_effect,
            "effect_target": self._target,
            "path": int(next_node),
            "path_context": path_context,
            "resume": {
                "step_before": self._step_before,
                "observations": tuple(self._observations),
                "effect_actions": tuple(self._effect_actions),
                "locked_effect": self._locked_effect,
                "target": self._target,
            },
        }
        self.frames.append(frame)
        self.state = after
        self._begin_step()
        return frame

    def choose(self, action: object):
        if self.context.phase == PHASE_EFFECT:
            return self.choose_effect(action)
        if self.context.phase == PHASE_TARGET:
            return self.choose_target(int(action))
        if self.context.phase == PHASE_PATH:
            return self.choose_path(int(action))
        raise RuntimeError("终态没有可执行动作")

    def random_action(self) -> object:
        """从当前合法动作中随机选择，实际随机流仍完全留在后端。"""
        actions = self.map.legal_actions(self.context)
        if not actions:
            raise RuntimeError("当前状态没有合法动作")
        return actions[self.rng.randrange(len(actions))]

    @property
    def step_facts(self) -> dict:
        """给前端展示当前步事实，不暴露可变内部列表。"""
        return {
            "observations": tuple(self._observations),
            "effect_actions": tuple(self._effect_actions),
            "locked_effect": self._locked_effect,
            "effect_target": self._target,
        }

    def another_possibility(self, frame_index: int) -> DecisionContext:
        """舍弃所选帧及其后续，只恢复该帧已经结算好的路径选择。"""
        if not 0 <= frame_index < len(self.frames):
            raise IndexError("历史帧索引越界")
        frame = self.frames[frame_index]
        self.frames = self.frames[:frame_index]
        self.context = frame["path_context"]
        self.state = self.context.state
        resume = frame["resume"]
        self._step_before = resume["step_before"]
        self._observations = list(resume["observations"])
        self._effect_actions = list(resume["effect_actions"])
        self._locked_effect = resume["locked_effect"]
        self._target = resume["target"]
        return self.context


class CampaignProgress:
    """三位面只继承倒计时和资源，不向当前后端暴露未来地图。"""

    def __init__(self, targets: Iterable[float] = CAMPAIGN_DEFAULT_TARGETS,
                 cheat: int = 2, reroll: int = 3, initial_countdown: int = 15):
        self.targets = tuple(float(value) for value in targets)
        if len(self.targets) != 3:
            raise ValueError("完整仿真必须提供三个位面目标")
        self.plane_index = 0
        self.countdown = int(initial_countdown)
        self.cheat = max(0, int(cheat))
        self.reroll = max(0, int(reroll))
        self.results = []

    @property
    def finished(self) -> bool:
        return self.plane_index >= 3

    def current_config(self) -> dict:
        if self.finished:
            raise RuntimeError("三个位面均已完成")
        return {
            "plane": self.plane_index + 1,
            "target_countdown": self.targets[self.plane_index],
            "entry_countdown": self.countdown,
            "cheat": self.cheat,
            "reroll": self.reroll,
        }

    def settle_current(self, state: CountdownState,
                       target_countdown: Optional[float] = None) -> dict:
        if self.finished:
            raise RuntimeError("三个位面均已完成")
        target = (self.targets[self.plane_index] if target_countdown is None
                  else float(target_countdown))
        result = {
            "plane": self.plane_index + 1,
            "final_countdown": state.countdown,
            "target_countdown": target,
            "won": state.countdown >= target,
            "cheat": state.cheat_rem,
            "reroll": state.reroll_rem,
        }
        self.results.append(result)
        self.countdown, self.cheat, self.reroll = (
            state.countdown, state.cheat_rem, state.reroll_rem)
        self.plane_index += 1
        return dict(result)


@dataclass(frozen=True, slots=True)
class ProductionDecision:
    """生产代理只消费该只读结果，不接触控制器内部 Q 表。"""

    context: DecisionContext
    action: object
    highest_win_action: object
    expected_countdown: float
    win_rate: Optional[float]
    sample_count: int
    control_rollouts: int
    evaluation_rollouts: int
    alternatives: tuple
    planned_effect: Optional[int] = None
    dp_upper_bound: Optional[float] = None


class CountdownDecisionAgent:
    """在真实画面事实之上提供效果、感染点与路径三类决策。

    本类不会自行替游戏产生重投或随机感染结果。调用者执行建议后，应在下一张
    画面中重新同步 CD、资源与感染点，再请求下一阶段建议。
    """

    def __init__(self, config: Optional[MCConfig] = None,
                 targets: Iterable[float] = CAMPAIGN_DEFAULT_TARGETS,
                 decision_mode: str = DECISION_MC,
                 calculate_dp_upper_bound: bool = False):
        self.config = (config or MCConfig()).normalized()
        self.targets = tuple(float(value) for value in targets)
        if len(self.targets) != 3:
            raise ValueError("生产决策必须提供三个位面目标")
        if decision_mode not in (
                DECISION_MC, DECISION_WIN_RATE, DECISION_WIN_RATE_DP, DECISION_DP):
            raise ValueError(f"未知决策依据: {decision_mode}")
        self.decision_mode = decision_mode
        self.calculate_dp_upper_bound = bool(calculate_dp_upper_bound)
        self.model = self.controller = self.state = self.context = None
        self.plane = 1
        self.locked_effect = None

    @property
    def ready(self) -> bool:
        return self.model is not None and self.controller is not None

    @property
    def target_countdown(self) -> float:
        return self.targets[self.plane - 1]

    def reset(self) -> None:
        self.model = self.controller = self.state = self.context = None
        self.locked_effect = None

    def load_map(self, nodes: Iterable[Mapping], edges: Mapping[int, Iterable[int]],
                 start_idx: int, infected_indices: Iterable[int], countdown: int,
                 cheat: int, reroll: int, plane: int = 1,
                 preserve_effect: bool = False) -> CountdownState:
        """装入当前画面识别出的剩余地图；换图后只保留已经确定的本步效果。"""
        locked = self.locked_effect if preserve_effect else None
        self.plane = min(max(int(plane), 1), 3)
        self.model = CountdownMap(nodes, edges, int(start_idx), infected_indices)
        self.model.longest_steps_from(int(start_idx))
        self.controller = MonteCarloController(self.model, self.config)
        self.state = self.model.initial_state(cheat, reroll, countdown)
        self.locked_effect = locked
        self.context = DecisionContext(
            PHASE_PATH if locked is not None else PHASE_TERMINAL,
            self.state, locked_effect=locked)
        return self.state

    def sync_facts(self, countdown: Optional[int] = None,
                   cheat: Optional[int] = None,
                   reroll: Optional[int] = None,
                   infected_indices: Optional[Iterable[int]] = None,
                   node_idx: Optional[int] = None) -> CountdownState:
        """以最新 OCR/识图事实覆盖预测状态，不猜测游戏随机结果。"""
        self._require_ready()
        infected = self.state.infected
        if infected_indices is not None:
            infected = sum(1 << int(idx) for idx in set(infected_indices)
                           if int(idx) in self.model.node_map)
        self.state = CountdownState(
            self.state.node_idx if node_idx is None else int(node_idx), infected,
            self.state.countdown if countdown is None else int(countdown),
            self.state.cheat_rem if cheat is None else max(0, int(cheat)),
            self.state.reroll_rem if reroll is None else max(0, int(reroll)))
        return self.state

    def recommend_effect(self, observed_effect: int) -> ProductionDecision:
        self._require_ready()
        observed = int(observed_effect)
        if observed not in ALL_EFFECTS:
            raise ValueError("观察效果必须在 1..6")
        return self._recommend(DecisionContext(PHASE_EFFECT, self.state, observed))

    def apply_effect_action(self, observed_effect: int, action: object) -> DecisionContext:
        """在生产程序确认点击成功后记录资源消耗与最终采用的效果。"""
        context = DecisionContext(PHASE_EFFECT, self.state, int(observed_effect))
        if action not in self.model.legal_actions(context):
            raise ValueError(f"非法效果动作: {action!r}")
        if action == "reroll":
            self.state = replace(self.state, reroll_rem=self.state.reroll_rem - 1)
            self.locked_effect = None
            self.context = DecisionContext(PHASE_TERMINAL, self.state)
            return self.context
        self.locked_effect = (context.observed_effect if action == "keep"
                              else int(action[1]))
        if action != "keep":
            self.state = replace(self.state, cheat_rem=self.state.cheat_rem - 1)
        phase = (PHASE_TARGET if self.locked_effect == EFFECT_SELECT
                 and self.model.infection_targets(self.state) else PHASE_PATH)
        self.context = DecisionContext(
            phase, self.state, locked_effect=self.locked_effect)
        return self.context

    def recommend_target(self) -> Optional[ProductionDecision]:
        self._require_ready()
        targets = self.model.infection_targets(self.state)
        if not targets:
            self.context = DecisionContext(
                PHASE_PATH, self.state, locked_effect=self.locked_effect)
            return None
        self.context = DecisionContext(
            PHASE_TARGET, self.state, locked_effect=EFFECT_SELECT)
        return self._recommend(self.context)

    def apply_target(self, target: int) -> DecisionContext:
        self._require_ready()
        if int(target) not in self.model.infection_targets(self.state):
            raise ValueError(f"节点 #{target} 不是当前可感染目标")
        self.state = replace(self.state, infected=self.state.infected | 1 << int(target))
        self.context = DecisionContext(
            PHASE_PATH, self.state, locked_effect=EFFECT_SELECT)
        return self.context

    def recommend_path(self) -> ProductionDecision:
        self._require_ready()
        self.context = DecisionContext(
            PHASE_PATH, self.state,
            locked_effect=self.locked_effect or EFFECT_NOTHING)
        return self._recommend(self.context)

    def apply_path(self, next_node: int) -> CountdownState:
        self._require_ready()
        if self.context.phase != PHASE_PATH:
            raise RuntimeError("当前不是路径选择阶段")
        self.state = self.model.move(
            self.context.state, int(next_node), self.context.locked_effect)
        self.context = DecisionContext(PHASE_TERMINAL, self.state)
        self.locked_effect = None
        return self.state

    def _recommend(self, context: DecisionContext) -> ProductionDecision:
        if self.decision_mode == DECISION_DP:
            return self._recommend_dp(context)
        dp_advice = None
        if self.calculate_dp_upper_bound:
            dp_advice = self._recommend_dp(context)
            if dp_advice.expected_countdown < self.target_countdown:
                return dp_advice
        recommendation = self.controller.recommend(
            context, target=self.target_countdown)
        win_reports = recommendation.win_reports or recommendation.reports
        noise_floor = self.config.win_rate_noise_floor_percent / 100.0
        has_significant_win_rate = any(
            (stats.win_rate or 0.0) > 0.0
            and (stats.win_rate or 0.0) >= noise_floor
            for stats in win_reports.values())
        if (self.decision_mode in (DECISION_WIN_RATE, DECISION_WIN_RATE_DP)
                and has_significant_win_rate):
            action = recommendation.highest_win_action
        elif self.decision_mode == DECISION_WIN_RATE_DP:
            dp_advice = dp_advice or self._recommend_dp(context)
            action = dp_advice.action
        else:
            action = recommendation.recommended_action
        mean_stats = recommendation.reports[action]
        win_stats = win_reports.get(action, mean_stats)
        alternatives = tuple(
            (candidate, stats.mean,
             (win_reports.get(candidate, stats).win_rate
              if win_reports.get(candidate, stats) else None), stats.count)
            for candidate, stats in recommendation.reports.items())
        return ProductionDecision(
            context, action, recommendation.highest_win_action,
            mean_stats.mean, win_stats.win_rate, mean_stats.count,
            recommendation.control_rollouts,
            recommendation.evaluation_rollouts, alternatives,
            planned_effect=(dp_advice.planned_effect
                            if dp_advice and action == dp_advice.action else None),
            dp_upper_bound=dp_advice.expected_countdown if dp_advice else None)

    def _recommend_dp(self, context: DecisionContext) -> ProductionDecision:
        """以最有利随机结果的精确 DP 轨迹代理当前一步。"""
        from tool.countdown_dp import ExactCountdownDP

        bonuses = {name: getattr(self.config, field)
                   for name, field in _PATH_SCORE_BONUS_FIELD.items()}
        result = ExactCountdownDP(self.model, path_bonuses=bonuses).solve(context)
        if not result.steps:
            raise RuntimeError("DP 未返回当前决策动作")
        step = result.steps[0]
        if context.phase == PHASE_EFFECT:
            action = step.effect_action
        elif context.phase == PHASE_TARGET:
            legal = set(self.model.legal_actions(context))
            action = next((node for node in step.infected_added if node in legal), None)
            if action is None:
                raise RuntimeError("DP 未返回合法感染目标")
        elif context.phase == PHASE_PATH:
            action = step.next_node
        else:
            raise RuntimeError(f"DP 不支持当前决策阶段: {context.phase}")
        return ProductionDecision(
            context, action, action, float(result.max_countdown), None,
            result.states_evaluated, 0, 0, (), step.effect,
            float(result.max_countdown))

    def _require_ready(self) -> None:
        if not self.ready:
            raise RuntimeError("尚未装入可评估地图")


def format_action(phase: str, action: object) -> str:
    if phase == PHASE_EFFECT:
        if action == "keep":
            return "keep"
        if action == "reroll":
            return "reroll"
        return f"cheat→{EFFECT_NAMES[int(action[1])]}"
    if phase == PHASE_TARGET:
        return f"感染 #{int(action)}"
    if phase == PHASE_PATH:
        return f"前往 #{int(action)}"
    return "终点"


__all__ = [
    "ALL_EFFECTS", "CAMPAIGN_DEFAULT_TARGETS", "CampaignProgress",
    "CountdownDecisionAgent", "CountdownMap", "CountdownSession",
    "CountdownState", "DecisionContext",
    "DEFAULT_MAP_FILES", "EFFECT_ADJACENT", "EFFECT_BONUS", "EFFECT_CHEAT_TEXT",
    "EFFECT_NAMES",
    "EFFECT_NOTHING", "EFFECT_RANDOM_INFECT", "EFFECT_SELECT", "EFFECT_SPREAD",
    "EFFECT_TEXT_ALIASES",
    "MCConfig", "MCRecommendation", "MCSampleStats", "MonteCarloController",
    "PHASE_EFFECT", "PHASE_PATH", "PHASE_TARGET", "PHASE_TERMINAL",
    "DECISION_DP", "DECISION_MC", "DECISION_WIN_RATE", "DECISION_WIN_RATE_DP",
    "ProductionDecision", "format_action", "parse_effect_text",
]
