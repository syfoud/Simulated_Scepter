"""倒计时地图的最佳情形 DP 旁路分析器。

该模块只计算"所有环境随机结果均取最有利值"时的理论最大最终 CD，供 GUI
展示上限、路径和感染点；它不读取、修改或热启动纯 MC 控制器。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Optional

try:
    from .countdown_backend import (
        ALL_EFFECTS, CountdownMap, CountdownState, DecisionContext,
        EFFECT_ADJACENT, EFFECT_BONUS, EFFECT_NOTHING, EFFECT_RANDOM_INFECT,
        EFFECT_SELECT, EFFECT_SPREAD, PHASE_EFFECT, PHASE_PATH, PHASE_TARGET,
        PHASE_TERMINAL,
    )
except ImportError:
    from countdown_backend import (
        ALL_EFFECTS, CountdownMap, CountdownState, DecisionContext,
        EFFECT_ADJACENT, EFFECT_BONUS, EFFECT_NOTHING, EFFECT_RANDOM_INFECT,
        EFFECT_SELECT, EFFECT_SPREAD, PHASE_EFFECT, PHASE_PATH, PHASE_TARGET,
        PHASE_TERMINAL,
    )


@dataclass(frozen=True, slots=True)
class DPBestStep:
    node_idx: int
    effect_action: object
    effect: int
    next_node: int
    countdown_delta: int
    effect_countdown_delta: int
    move_countdown_delta: int
    infected_added: tuple[int, ...]
    countdown_before: int
    countdown_after: int
    infected_before: int
    infected_after: int
    cheat_before: int
    cheat_after: int
    reroll_before: int
    reroll_after: int


@dataclass(frozen=True, slots=True)
class DPBestResult:
    max_countdown: int
    path: tuple[int, ...]
    infection_nodes: tuple[int, ...]
    steps: tuple[DPBestStep, ...]
    states_evaluated: int


@dataclass(frozen=True, slots=True)
class _Plan:
    state: CountdownState
    steps: tuple[DPBestStep, ...] = ()
    cheat_used: int = 0
    reroll_used: int = 0


class ExactCountdownDP:
    """从当前确定上下文求最有利随机结果下的理论最大 CD。"""

    def __init__(self, countdown_map: CountdownMap, max_states: int = 250_000,
                 max_spread_outcomes: int = 50_000,
                 cancelled: Optional[Callable[[], bool]] = None):
        self.map = countdown_map
        self.max_states = max(1, int(max_states))
        self.max_spread_outcomes = max(1, int(max_spread_outcomes))
        self.cancelled = cancelled
        self.states_evaluated = 0
        self._spread_cache = {}

    def _checkpoint(self, count_state: bool = False) -> None:
        if self.cancelled and self.cancelled():
            raise InterruptedError("DP 计算已取消")
        if count_state:
            self.states_evaluated += 1
            if self.states_evaluated > self.max_states:
                raise RuntimeError(f"DP 非支配状态超过安全上限 {self.max_states:,}")

    @staticmethod
    def _plan_key(plan: _Plan) -> tuple:
        return (-plan.state.countdown, plan.cheat_used + plan.reroll_used,
                plan.cheat_used, plan.reroll_used,
                tuple(step.next_node for step in plan.steps))

    @staticmethod
    def _maximal_masks(masks) -> tuple[int, ...]:
        """感染集合越大不会降低收益，因此删除其真子集。"""
        maximal = []
        for mask in sorted(set(masks), key=lambda value: (-value.bit_count(), value)):
            if not any(mask | other == other for other in maximal):
                maximal.append(mask)
        return tuple(maximal)

    def _spread_outcomes(self, state: CountdownState) -> tuple[int, ...]:
        key = state.node_idx, state.infected
        if key in self._spread_cache:
            return self._spread_cache[key]
        future = self.map.future_masks[state.node_idx]
        sources = state.infected & future
        outcomes = (state.infected,)
        while sources:
            self._checkpoint()
            source_bit = sources & -sources
            source = source_bit.bit_length() - 1
            candidates = self.map.neighbor_masks[source] & future & ~state.infected
            if candidates:
                choices = tuple(1 << idx for idx in self.map.node_map
                                if (candidates >> idx) & 1)
                outcomes = self._maximal_masks(
                    mask | bit for mask in outcomes for bit in choices)
                if len(outcomes) > self.max_spread_outcomes:
                    raise RuntimeError(
                        f"浇灌非支配组合超过安全上限 {self.max_spread_outcomes:,}")
            sources ^= source_bit
        self._spread_cache[key] = outcomes
        return outcomes

    def _effect_outcomes(self, state: CountdownState, effect: int):
        if effect == EFFECT_BONUS:
            yield state.infected, self.map.active_infected_count(state), ()
        elif effect in (EFFECT_SELECT, EFFECT_RANDOM_INFECT):
            targets = self.map.infection_targets(state)
            if targets:
                for target in targets:
                    yield state.infected | 1 << target, 0, (target,)
            else:
                yield state.infected, 0, ()
        elif effect == EFFECT_SPREAD:
            for mask in self._spread_outcomes(state):
                added = mask & ~state.infected
                yield mask, 0, tuple(
                    idx for idx in self.map.node_map if (added >> idx) & 1)
        else:
            yield state.infected, 0, ()

    def _expand(self, plan: _Plan, effect: int, action: object, outcomes=None):
        origin = plan.state
        outcomes = outcomes if outcomes is not None else self._effect_outcomes(origin, effect)
        for mask, effect_delta, selected in outcomes:
            post = CountdownState(
                origin.node_idx, mask, origin.countdown + effect_delta, 0, 0)
            for next_node in self.map.path_options(post):
                self._checkpoint()
                adjacent_added = (self.map.neighbor_masks[next_node]
                                  & ~self.map.destroy_masks[origin.node_idx]
                                  & ~origin.infected
                                  if effect == EFFECT_ADJACENT else 0)
                moved = self.map.move(post, next_node, effect)
                added = moved.infected & ~origin.infected | adjacent_added
                infected_added = tuple(
                    idx for idx in self.map.node_map if (added >> idx) & 1)
                if selected:
                    infected_added = tuple(dict.fromkeys(selected + infected_added))
                step = DPBestStep(
                    origin.node_idx, action, effect, next_node,
                    moved.countdown - origin.countdown,
                    effect_delta, moved.countdown - post.countdown,
                    infected_added,
                    origin.countdown, moved.countdown,
                    origin.infected, moved.infected, 0, 0, 0, 0)
                yield _Plan(
                    CountdownState(next_node, moved.infected, moved.countdown, 0, 0),
                    plan.steps + (step,), plan.cheat_used, plan.reroll_used)

    def _first_plans(self, context: DecisionContext, state: CountdownState):
        if context.phase == PHASE_EFFECT:
            observed = context.observed_effect
            if observed not in ALL_EFFECTS:
                raise ValueError("效果阶段缺少实际观察效果")
            choices = {observed: ("keep", 0, 0)}
            if context.state.cheat_rem:
                choices.update(
                    (effect, (("cheat", effect), 1, 0))
                    for effect in ALL_EFFECTS if effect != observed)
            if context.state.reroll_rem:
                for effect in ALL_EFFECTS:
                    candidate = ("reroll", 0, 1)
                    if effect not in choices or candidate[1:] < choices[effect][1:]:
                        choices[effect] = candidate
            for effect, (action, cheat, reroll) in choices.items():
                for plan in self._expand(_Plan(state), effect, action):
                    yield _Plan(plan.state, plan.steps, cheat, reroll)
        elif context.phase == PHASE_TARGET:
            yield from self._expand(
                _Plan(state), EFFECT_SELECT, "选择感染点",
                self._effect_outcomes(state, EFFECT_SELECT))
        elif context.phase == PHASE_PATH:
            effect = context.locked_effect or EFFECT_NOTHING
            yield from self._expand(
                _Plan(state), effect, "已结算", ((state.infected, 0, ()),))
        else:
            raise ValueError(f"未知决策阶段: {context.phase}")

    def _add_frontier(self, frontiers: dict, queue: deque, plan: _Plan) -> None:
        plans = frontiers.setdefault(plan.state.node_idx, {})
        mask, countdown = plan.state.infected, plan.state.countdown
        same = plans.get(mask)
        if same and (same.state.countdown > plan.state.countdown or (
                same.state.countdown == plan.state.countdown
                and self._plan_key(same) <= self._plan_key(plan))):
            return
        future = self.map.future_masks[plan.state.node_idx]
        missing = future & ~mask
        if 1 << missing.bit_count() <= len(plans):
            extra = missing
            while True:
                other = plans.get(mask | extra)
                if other and other.state.countdown >= countdown:
                    return
                if not extra:
                    break
                extra = (extra - 1) & missing
        elif any(other_mask | mask == other_mask
                 and other.state.countdown >= countdown
                 for other_mask, other in plans.items()):
            return

        if 1 << mask.bit_count() <= len(plans):
            subset = mask
            while True:
                other = plans.get(subset)
                if other and countdown >= other.state.countdown:
                    del plans[subset]
                if not subset:
                    break
                subset = (subset - 1) & mask
        else:
            for other_mask, other in tuple(plans.items()):
                if mask | other_mask == mask and countdown >= other.state.countdown:
                    del plans[other_mask]
        plans[mask] = plan
        queue.append(plan)
        self._checkpoint(True)

    def solve(self, context: DecisionContext) -> DPBestResult:
        """返回当前上下文在最有利随机结果下的最大 CD 与一条实现轨迹。"""
        source = context.state
        if context.phase == PHASE_TERMINAL:
            return DPBestResult(source.countdown, (source.node_idx,), (), (), 0)
        state = CountdownState(source.node_idx, source.infected, 0, 0, 0)
        frontiers, queue = {}, deque()
        for plan in self._first_plans(context, state):
            self._add_frontier(frontiers, queue, plan)

        terminals = []
        while queue:
            self._checkpoint()
            plan = queue.popleft()
            if frontiers.get(plan.state.node_idx, {}).get(plan.state.infected) is not plan:
                continue
            if self.map.is_terminal(plan.state):
                terminals.append(plan)
                continue
            # 最有利结果下"归心"等价于"慈怀"，"可憎"又被慈怀弱支配。
            for effect in (EFFECT_SPREAD, EFFECT_BONUS,
                           EFFECT_ADJACENT, EFFECT_SELECT):
                for child in self._expand(plan, effect, "keep"):
                    self._add_frontier(frontiers, queue, child)
        if not terminals:
            terminals = [plan for plans in frontiers.values() for plan in plans.values()
                         if self.map.is_terminal(plan.state)]
        if not terminals:
            raise RuntimeError("DP 未找到可到达的终点")
        best = min(terminals, key=self._plan_key)
        cheat, reroll, steps = source.cheat_rem, source.reroll_rem, []
        for step in best.steps:
            cheat_before, reroll_before = cheat, reroll
            if isinstance(step.effect_action, tuple) and step.effect_action[0] == "cheat":
                cheat -= 1
            elif step.effect_action == "reroll":
                reroll -= 1
            steps.append(replace(
                step,
                countdown_before=source.countdown + step.countdown_before,
                countdown_after=source.countdown + step.countdown_after,
                cheat_before=cheat_before, cheat_after=cheat,
                reroll_before=reroll_before, reroll_after=reroll))
        steps = tuple(steps)
        seen = set()
        infection_nodes = tuple(
            node for step in steps for node in step.infected_added
            if node not in seen and not seen.add(node))
        return DPBestResult(
            source.countdown + best.state.countdown,
            (source.node_idx,) + tuple(step.next_node for step in steps),
            infection_nodes, steps, self.states_evaluated)


__all__ = ["DPBestResult", "DPBestStep", "ExactCountdownDP"]
