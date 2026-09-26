"""倒计时纯 MC 后端的规则与统计回归测试。"""

import inspect
import random
import unittest
from unittest.mock import patch

try:
    from . import countdown_backend as backend
except ImportError:
    import countdown_backend as backend


def linear_map(infected=()):
    nodes = [
        {"idx": 0, "name": "start", "cx": 0, "cy": 0},
        {"idx": 1, "name": "wait", "cx": 100, "cy": 0},
        {"idx": 2, "name": "boss", "cx": 200, "cy": 0},
    ]
    return backend.CountdownMap(nodes, {0: [1], 1: [2], 2: []}, 0, infected)


def third_countdown_map():
    nodes = [
        {"idx": 0, "cx": 1116, "cy": 452},
        {"idx": 1, "cx": 878, "cy": 537},
        {"idx": 2, "cx": 1024, "cy": 454},
        {"idx": 3, "cx": 968, "cy": 372},
        {"idx": 4, "cx": 974, "cy": 534},
        {"idx": 5, "cx": 928, "cy": 454},
        {"idx": 6, "cx": 876, "cy": 374},
        {"idx": 7, "cx": 828, "cy": 456},
    ]
    edges = {
        7: [1, 5, 6], 1: [4, 5], 6: [3, 5], 5: [2, 3, 4],
        3: [2], 4: [2], 2: [0], 0: [],
    }
    return backend.CountdownMap(nodes, edges, 7, ())


def high_target_map():
    """20260617_103451.png 的识图拓扑，用于高目标稀疏状态回归。"""
    coords = [
        (0, 787, 373.5), (1, 927.5, 291.5), (2, 1352, 535.5),
        (3, 1111, 453.5), (4, 1299.5, 615.5), (5, 1017.5, 454.5),
        (6, 1256.5, 537), (7, 1016, 291.5), (8, 1064.5, 535.5),
        (9, 1117.5, 291.5), (10, 1117.5, 615.5), (11, 969, 534.5),
        (12, 879.5, 534.5), (13, 1204.5, 453.5), (14, 923.5, 456),
        (15, 1064.5, 373.5), (16, 1165.5, 535.5), (17, 1022.5, 616.5),
        (18, 1252.5, 372.5), (19, 1165.5, 373.5), (20, 872.5, 372.5),
        (21, 827, 453.5), (22, 1211.5, 615.5), (23, 827, 291.5),
        (24, 974.5, 372.5), (25, 1302.5, 456),
    ]
    nodes = [{"idx": idx, "cx": cx, "cy": cy} for idx, cx, cy in coords]
    edges = {
        0: (20, 21, 23), 1: (7, 24), 2: (), 3: (13, 16, 19), 4: (2,),
        5: (3, 8, 15), 6: (2, 4, 25), 7: (9, 15), 8: (3, 10, 16),
        9: (19,), 10: (16, 22), 11: (5, 8, 17), 12: (11, 14),
        13: (6, 18, 25), 14: (5, 11, 24), 15: (3, 9, 19),
        16: (6, 13, 22), 17: (8, 10), 18: (25,), 19: (13, 18),
        20: (1, 14, 24), 21: (12, 14, 20), 22: (4, 6),
        23: (1, 20), 24: (5, 7, 15), 25: (2,),
    }
    return backend.CountdownMap(nodes, edges, 0, (4, 15))


def rational_path_map():
    nodes = [
        {"idx": 0, "name": "event", "cx": 1272.5, "cy": 644.5},
        {"idx": 1, "name": "battle", "cx": 1321.0, "cy": 352.5},
        {"idx": 2, "name": "trade", "cx": 1443.0, "cy": 355.0},
        {"idx": 3, "name": "reward2", "cx": 1271.5, "cy": 449.0},
        {"idx": 4, "name": "event", "cx": 1386.5, "cy": 644.5},
        {"idx": 5, "name": "head", "cx": 1554.5, "cy": 546.5},
        {"idx": 6, "name": "elite", "cx": 1437.0, "cy": 547.5},
        {"idx": 7, "name": "battle", "cx": 1321.0, "cy": 547.5},
        {"idx": 8, "name": "event", "cx": 1500.5, "cy": 449.5},
        {"idx": 9, "name": "start", "cx": 1212.5, "cy": 541.5},
    ]
    edges = {
        0: (4, 7), 1: (2,), 2: (8,), 3: (1, 7), 4: (6,),
        5: (), 6: (5, 8), 7: (4, 6), 8: (5,), 9: (0, 3, 7),
    }
    return backend.CountdownMap(nodes, edges, 9, (0, 1, 3, 4, 7))


def adjacent_effect_map():
    """20260801_010202.png 的识图拓扑。"""
    nodes = [
        {"idx": 0, "name": "boss", "cx": 1118.5, "cy": 454.5},
        {"idx": 1, "name": "bugevent", "cx": 977.5, "cy": 375.5},
        {"idx": 2, "name": "wait", "cx": 1026.0, "cy": 456.5},
        {"idx": 3, "name": "adventure", "cx": 974.5, "cy": 539.0},
        {"idx": 4, "name": "elite", "cx": 922.5, "cy": 455.5},
        {"idx": 5, "name": "reward", "cx": 882.5, "cy": 536.5},
        {"idx": 6, "name": "bugbattle", "cx": 877.5, "cy": 375.5},
        {"idx": 7, "name": "trade", "cx": 830.5, "cy": 458.0},
    ]
    edges = {
        0: (), 1: (2,), 2: (0,), 3: (2,), 4: (1, 2, 3),
        5: (3, 4), 6: (1, 4), 7: (4, 5, 6),
    }
    return backend.CountdownMap(nodes, edges, 7, ())


class CountdownRuleTests(unittest.TestCase):
    def test_backend_has_no_qt_cv_or_dp_dependency(self):
        source = inspect.getsource(backend)
        self.assertNotIn("PyQt", source)
        self.assertNotRegex(source, r"(?m)^\s*(?:from|import)\s+cv2")
        self.assertNotIn("ExactCountdownDP", source)
        self.assertNotIn("future_table", source)

    def test_select_can_infect_the_immediate_next_node(self):
        model = linear_map()
        state = model.initial_state(cheat=0, reroll=0, countdown=15)
        self.assertIn(1, model.infection_targets(state))
        selected = model.settle_effect(
            state, backend.EFFECT_SELECT, random.Random(1), target=1)
        moved = model.move(selected, 1, backend.EFFECT_SELECT)
        self.assertEqual(16, moved.countdown)
        self.assertEqual(0, moved.infected)

    def test_random_infect_is_environment_random_not_maximized(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(nodes, {0: [1, 2], 1: [], 2: []}, 0, ())
        state = model.initial_state(0, 0, 0)
        outcomes = {
            model.settle_effect(state, backend.EFFECT_RANDOM_INFECT,
                                random.Random(seed)).infected
            for seed in range(50)
        }
        self.assertEqual({1 << 1, 1 << 2}, outcomes)

    def test_spread_samples_directly_without_cartesian_outcome_list(self):
        source = inspect.getsource(backend.CountdownMap.settle_effect)
        self.assertNotIn("cartesian", source.lower())
        self.assertNotIn("product(", source)

    def test_cheat_is_deducted_before_target_and_path_context(self):
        model = linear_map()
        session = backend.CountdownSession(model, cheat=1, reroll=0, countdown=15, seed=3)
        session.set_observed_effect(backend.EFFECT_NOTHING)
        target_context = session.choose_effect(("cheat", backend.EFFECT_SELECT))
        self.assertEqual(backend.PHASE_TARGET, target_context.phase)
        self.assertEqual(0, target_context.state.cheat_rem)
        path_context = session.choose_target(1)
        self.assertEqual(0, path_context.state.cheat_rem)

    def test_reroll_reveals_a_new_effect_before_any_path_exists(self):
        session = backend.CountdownSession(linear_map(), 0, 1, seed=7)
        context = session.choose_effect("reroll")
        self.assertEqual(backend.PHASE_EFFECT, context.phase)
        self.assertEqual(0, context.state.reroll_rem)
        self.assertIsNotNone(context.observed_effect)
        self.assertIsNone(context.locked_effect)

    def test_select_with_no_remaining_target_can_be_kept_as_noop(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, {1})
        session = backend.CountdownSession(model, 0, 0, seed=5)
        session.set_observed_effect(backend.EFFECT_SELECT)
        context = session.choose_effect("keep")
        self.assertEqual(backend.PHASE_PATH, context.phase)

    def test_duplicate_infected_indices_cannot_carry_into_another_bit(self):
        model = linear_map([1, 1])
        self.assertEqual(1 << 1, model.initial_infected)


class CountdownMonteCarloTests(unittest.TestCase):
    def test_selected_effect_with_enough_cheats_has_real_guaranteed_route(self):
        model = adjacent_effect_map()
        for first in (backend.EFFECT_ADJACENT, backend.EFFECT_SELECT):
            for observed in backend.ALL_EFFECTS:
                with self.subTest(first=first, observed=observed):
                    session = backend.CountdownSession(model, 4, 0, countdown=15)
                    session.set_observed_effect(first)
                    session.choose_effect("keep")
                    if first == backend.EFFECT_SELECT:
                        session.choose_target(4)
                    session.choose_path(5)
                    for effect, node in ((backend.EFFECT_ADJACENT, 4),
                                         (backend.EFFECT_BONUS, 1),
                                         (backend.EFFECT_BONUS, 2),
                                         (backend.EFFECT_SELECT, 0)):
                        session.set_observed_effect(observed)
                        session.choose_effect("keep" if observed == effect else ("cheat", effect))
                        if effect == backend.EFFECT_SELECT:
                            session.choose_target(0)
                        session.choose_path(node)
                    self.assertEqual(20, session.state.countdown)
                    self.assertGreaterEqual(session.state.cheat_rem, 0)

    def test_select_and_adjacent_win_evaluation_survives_seed_and_resource_changes(self):
        model = adjacent_effect_map()
        for seed in (7, 20260802):
            for effect, reroll in ((backend.EFFECT_SELECT, 0),
                                   (backend.EFFECT_SELECT, 3),
                                   (backend.EFFECT_ADJACENT, 0)):
                with self.subTest(seed=seed, effect=effect, reroll=reroll):
                    controller = backend.MonteCarloController(
                        model, backend.MCConfig(min_visits=200, seed=seed))
                    context = backend.DecisionContext(
                        backend.PHASE_EFFECT, model.initial_state(4, reroll, 15), effect)
                    result = controller.recommend(context, 20)
                    keep = result.win_reports["keep"]
                    self.assertGreater(keep.target_count, 0)
                    self.assertEqual(keep.target_count, keep.wins)
                    self.assertLessEqual(result.control_rollouts, 10_000)
                    self.assertLessEqual(result.evaluation_rollouts, 10_000)

    def test_bonus_cheat_to_adjacent_with_three_cheats_discovers_wins(self):
        model = adjacent_effect_map()
        for seed in (7, 20260802):
            with self.subTest(seed=seed):
                controller = backend.MonteCarloController(
                    model, backend.MCConfig(min_visits=200, seed=seed))
                context = backend.DecisionContext(
                    backend.PHASE_EFFECT, model.initial_state(3, 2, 15), backend.EFFECT_BONUS)
                result = controller.recommend(context, 20)
                report = result.win_reports[("cheat", backend.EFFECT_ADJACENT)]
                self.assertGreater(report.wins, 0)
                self.assertGreaterEqual(report.maximum, 20)
                self.assertEqual(report.wins / report.target_count, report.win_rate)

    def test_settled_contexts_share_only_equivalent_states(self):
        model = adjacent_effect_map()
        controller = backend.MonteCarloController(model)
        state = model.initial_state(4, 2, 15)
        selected = backend.DecisionContext(backend.PHASE_PATH, state,
                                           locked_effect=backend.EFFECT_SELECT)
        nothing = backend.DecisionContext(backend.PHASE_PATH, state,
                                          locked_effect=backend.EFFECT_NOTHING)
        adjacent = backend.DecisionContext(backend.PHASE_PATH, state,
                                           locked_effect=backend.EFFECT_ADJACENT)
        self.assertEqual(controller._context_key(selected), controller._context_key(nothing))
        self.assertNotEqual(controller._context_key(selected), controller._context_key(adjacent))
        before = backend.DecisionContext(backend.PHASE_EFFECT, state, backend.EFFECT_BONUS)
        paid = backend.DecisionContext(backend.PHASE_EFFECT, model.initial_state(3, 2, 15),
                                       backend.EFFECT_ADJACENT)
        self.assertEqual(controller._win_q_key(before, ("cheat", backend.EFFECT_ADJACENT)),
                         controller._win_q_key(paid, "keep"))
        free = backend.DecisionContext(backend.PHASE_EFFECT, state, backend.EFFECT_ADJACENT)
        self.assertNotEqual(controller._win_q_key(free, "keep"),
                            controller._win_q_key(paid, "keep"))

    def test_effect_evaluation_uses_the_same_rational_policy_as_path_evaluation(self):
        model = adjacent_effect_map()
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=10_000,
                                    evaluation_rollouts=10_000,
                                    min_visits=200, seed=20260802))
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(4, 2, 15),
            observed_effect=backend.EFFECT_ADJACENT)
        recommendation = controller.recommend(context, target=20)
        self.assertEqual(
            1.0, max(report.win_rate
                     for report in recommendation.win_reports.values()))
        self.assertEqual(1.0, recommendation.win_reports["keep"].win_rate)
        self.assertLessEqual(recommendation.control_rollouts, 10_000)
        self.assertLessEqual(recommendation.evaluation_rollouts, 10_000)

    def test_win_policy_uses_rational_shared_downstream_route(self):
        model = rational_path_map()
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=6_000,
                                    evaluation_rollouts=6_000,
                                    min_visits=500, seed=20260802))
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(2, 2, 13),
            locked_effect=backend.EFFECT_NOTHING)
        recommendation = controller.recommend(context, target=15)
        win_reports = recommendation.win_reports
        self.assertIsNotNone(win_reports)
        self.assertEqual({0, 3, 7}, set(win_reports))
        self.assertTrue(all(
            report.wins == report.target_count for report in win_reports.values()))

    def test_win_policy_takes_a_direct_terminal_win_instead_of_risking_it(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
            {"idx": 3, "cx": 200, "cy": 80},
        ]
        model = backend.CountdownMap(
            nodes, {0: (1, 2), 1: (), 2: (3,), 3: ()}, 0, (1, 2))
        controller = backend.MonteCarloController(model)
        controller.win_target = 16
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 15),
            locked_effect=backend.EFFECT_NOTHING)
        self.assertEqual(1, controller._greedy_win_action(context))

    def test_high_target_fixture_discovers_real_wins_with_ten_cheats(self):
        model = high_target_map()
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=2_000,
                                    evaluation_rollouts=2_000,
                                    min_visits=50, seed=20260802))
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(10, 3, 15),
            backend.EFFECT_BONUS)
        recommendation = controller.recommend(context, target=75)
        self.assertIsNotNone(recommendation.win_reports)
        best = recommendation.win_reports[recommendation.highest_win_action]
        self.assertGreater(best.wins, 0)
        self.assertGreaterEqual(best.maximum, 75)

    def test_target_evaluation_keeps_separate_reports_when_every_action_loses(self):
        model = linear_map()
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=4,
                                    evaluation_rollouts=20,
                                    min_visits=1, seed=7))
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        recommendation = controller.recommend(context, target=100)
        self.assertIsNotNone(recommendation.win_reports)
        self.assertIsNot(recommendation.reports, recommendation.win_reports)
        self.assertTrue(all(
            report.target_count and not report.wins
            for report in recommendation.win_reports.values()))

    def test_cancelled_partial_evaluation_does_not_freeze_either_policy(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 40},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(
            nodes, {0: [1, 2], 1: [], 2: []}, 0, ())
        controller = backend.MonteCarloController(
            model, backend.MCConfig(evaluation_rollouts=20))
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        checks = 0

        def cancelled():
            nonlocal checks
            checks += 1
            return checks > 1

        with self.assertRaises(InterruptedError):
            controller.evaluate_current_policy(context, 100, cancelled=cancelled)
        self.assertNotIn(controller._context_key(context), controller.frozen_policy)
        self.assertNotIn(controller._win_context_key(context),
                         controller.frozen_win_policy)

    def test_successor_calibration_uses_the_win_policy_for_win_reports(self):
        class RecordingController(backend.MonteCarloController):
            def __init__(self, model, config):
                super().__init__(model, config)
                self.evaluated = []

            def evaluate_actions(self, context, target=None, progress=None,
                                 cancelled=None, rollouts=None, win_policy=False):
                self.evaluated.append((context.phase, win_policy))
                return super().evaluate_actions(
                    context, target, progress, cancelled, rollouts, win_policy)

        nodes = [
            {"idx": 0, "cx": 0, "cy": 40},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(
            nodes, {0: [1, 2], 1: [], 2: []}, 0, ())
        controller = RecordingController(
            model, backend.MCConfig(control_rollouts=20,
                                    evaluation_rollouts=20,
                                    min_visits=1, seed=9))
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 0, 0),
            backend.EFFECT_NOTHING)
        controller.recommend(context, target=100)
        self.assertIn((backend.PHASE_PATH, True), controller.evaluated)

    def test_excess_cheat_is_merged_above_the_remaining_step_limit(self):
        model = linear_map()
        controller = backend.MonteCarloController(model)
        enough = model.initial_state(2, 0, 15)
        excessive = model.initial_state(99, 0, 15)
        self.assertEqual(controller._state_key(enough),
                         controller._state_key(excessive))
        low = model.initial_state(1, 0, 15)
        self.assertNotEqual(controller._state_key(low),
                            controller._state_key(enough))

    def test_sparse_effect_samples_keep_growth_before_harvest_prior(self):
        nodes = [{"idx": idx, "cx": idx * 100, "cy": 0}
                 for idx in range(5)]
        model = backend.CountdownMap(
            nodes, {0: [1], 1: [2], 2: [3], 3: [4], 4: []}, 0, (1,))
        controller = backend.MonteCarloController(
            model, backend.MCConfig(min_visits=200))
        state = model.initial_state(1, 0, 0)
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, state, backend.EFFECT_NOTHING)
        spread = ("cheat", backend.EFFECT_SPREAD)
        bonus = ("cheat", backend.EFFECT_BONUS)
        self.assertGreater(controller._heuristic(context, spread),
                           controller._heuristic(context, bonus))
        controller.q[controller._q_key(context, bonus)].append(999)
        self.assertEqual(spread, controller._greedy_action(context))

    def test_state_key_can_merge_countdown_only_because_q_stores_return_to_go(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, {1})
        config = backend.MCConfig(control_rollouts=12, evaluation_rollouts=12,
                                  min_visits=2, seed=11)
        controller = backend.MonteCarloController(model, config)
        low = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        high = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 100),
            locked_effect=backend.EFFECT_NOTHING)
        self.assertEqual(controller._context_key(low), controller._context_key(high))
        controller.refine_current_state(low)
        sample = controller.q[controller._q_key(low, 1)]
        # 走感染节点的回报固定为 +1，而不是绝对终值。
        self.assertEqual(1.0, sample.mean)
        controller.refine_current_state(high)
        self.assertEqual(1.0, controller.q[controller._q_key(high, 1)].mean)

    def test_current_state_refinement_balances_every_legal_root_action(self):
        model = linear_map()
        config = backend.MCConfig(control_rollouts=1, evaluation_rollouts=20,
                                  min_visits=7, seed=13)
        controller = backend.MonteCarloController(model, config)
        state = model.initial_state(cheat=1, reroll=1, countdown=15)
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, state, backend.EFFECT_NOTHING)
        completed = controller.refine_current_state(context)
        actions = controller.legal_actions(context)
        self.assertEqual(len(actions) * 7, completed)
        self.assertTrue(all(
            controller.q[controller._q_key(context, action)].count >= 7
            for action in actions))

    def test_reports_use_equal_independent_samples_and_actual_target_hits(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(nodes, {0: [1, 2], 1: [], 2: []}, 0, {2})
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=40, evaluation_rollouts=40,
                                    min_visits=5, seed=17))
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        recommendation = controller.recommend(context, target=1)
        self.assertEqual({10}, {report.count for report in recommendation.reports.values()})
        self.assertEqual(
            {10}, {report.count for report in recommendation.win_reports.values()})
        self.assertEqual(2, recommendation.recommended_action)
        self.assertEqual(1.0, recommendation.reports[2].win_rate)
        self.assertEqual(0.0, recommendation.reports[1].win_rate)

    def test_learning_q_cannot_override_fresh_root_evaluation(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(nodes, {0: [1, 2], 1: [], 2: []}, 0, {2})
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=2, evaluation_rollouts=20,
                                    min_visits=1, seed=19))
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        controller.q[controller._q_key(context, 1)].append(999)
        controller.q[controller._q_key(context, 2)].append(-999)
        recommendation = controller.recommend(context)
        self.assertEqual(2, recommendation.recommended_action)
        self.assertEqual(-3.0, recommendation.reports[1].mean)
        self.assertEqual(1.0, recommendation.reports[2].mean)
        self.assertEqual(2, controller._greedy_action(context))

    def test_adjacent_effect_parent_evaluation_uses_calibrated_successor_policy(self):
        model = third_countdown_map()
        state = model.initial_state(cheat=1, reroll=2, countdown=0)
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, state, observed_effect=backend.EFFECT_ADJACENT)
        controller = backend.MonteCarloController(
            model, backend.MCConfig(control_rollouts=10_000,
                                    evaluation_rollouts=10_000,
                                    min_visits=200, seed=20260802))
        recommendation = controller.recommend(context, target=5)
        keep = recommendation.reports["keep"]
        keep_win = (recommendation.win_reports or recommendation.reports)["keep"]
        path_context = backend.DecisionContext(
            backend.PHASE_PATH, state, locked_effect=backend.EFFECT_ADJACENT)
        key = controller._context_key(path_context)
        self.assertEqual(5, controller.frozen_policy[key])
        self.assertIn(
            controller.frozen_win_policy[controller._win_context_key(path_context)], (1, 6))
        self.assertGreater(keep_win.wins, 0)
        if recommendation.win_reports:
            self.assertIsNot(keep, keep_win)
        self.assertLessEqual(recommendation.control_rollouts, 10_000)
        self.assertLessEqual(recommendation.evaluation_rollouts, 10_000)

    def test_reported_five_effect_route_reaches_five(self):
        model = third_countdown_map()
        state = model.initial_state(cheat=0, reroll=0, countdown=0)
        effects = [
            backend.EFFECT_ADJACENT, backend.EFFECT_ADJACENT,
            backend.EFFECT_BONUS, backend.EFFECT_SPREAD, backend.EFFECT_BONUS,
        ]
        for effect, next_node in zip(effects, [6, 5, 3, 2, 0]):
            state = model.settle_effect(state, effect, random.Random(1))
            state = model.move(state, next_node, effect)
        self.assertEqual(5, state.countdown)

    def test_running_statistics_grow_without_sample_window(self):
        stats = backend.MCSampleStats()
        for value in range(1000):
            stats.append(value)
        self.assertEqual(1000, stats.count)
        self.assertFalse(hasattr(stats, "values"))

    def test_cancelled_control_sampling_never_replays_already_counted_seeds(self):
        class RecordingController(backend.MonteCarloController):
            def __init__(self, model, config):
                super().__init__(model, config)
                self.draws = []

            def _rollout(self, initial, rng, **_kwargs):
                self.draws.append(rng.random())
                return float(initial.state.countdown)

        model = linear_map()
        controller = RecordingController(
            model, backend.MCConfig(control_rollouts=5, min_visits=1, seed=31))
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 0),
            observed_effect=backend.EFFECT_NOTHING)
        checks = 0

        def cancelled():
            nonlocal checks
            checks += 1
            return checks > 3

        self.assertEqual(3, controller.refine_current_state(context, cancelled=cancelled))
        first = tuple(controller.draws)
        controller.refine_current_state(context)
        self.assertTrue(set(first).isdisjoint(controller.draws[len(first):]))

    def test_unobserved_policy_executes_the_independently_selected_first_actions(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        controller = backend.MonteCarloController(model)
        first_actions = {effect: "keep" for effect in backend.ALL_EFFECTS}
        first_actions[backend.EFFECT_NOTHING] = ("cheat", backend.EFFECT_SELECT)
        stats = controller.evaluate_unobserved_effect_policy(
            model.initial_state(1, 0, 0), first_actions, 6, target=1)
        self.assertEqual((-1.0, 0.5), (stats.mean, stats.win_rate))


class CountdownHistoryAndCampaignTests(unittest.TestCase):
    def test_another_possibility_restores_frame_local_path_context(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
            {"idx": 3, "cx": 200, "cy": 40},
        ]
        model = backend.CountdownMap(
            nodes, {0: [1, 2], 1: [3], 2: [3], 3: []}, 0, ())
        session = backend.CountdownSession(model, 0, 2, seed=4)
        session.set_observed_effect(backend.EFFECT_NOTHING)
        session.choose_effect("keep")
        session.choose_path(1)
        first_observed = session.context.observed_effect
        first_reroll = session.choose_effect("reroll").observed_effect
        restored = session.another_possibility(0)
        self.assertEqual(backend.PHASE_PATH, restored.phase)
        self.assertEqual(0, restored.state.node_idx)
        self.assertEqual((1, 2), model.path_options(restored.state))
        self.assertEqual([], session.frames)
        session.choose_path(2)
        second_observed = session.context.observed_effect
        second_reroll = session.choose_effect("reroll").observed_effect
        self.assertNotEqual((first_observed, first_reroll),
                            (second_observed, second_reroll))

    def test_campaign_carries_only_score_resources_and_targets(self):
        campaign = backend.CampaignProgress(
            [15, 20, 25], cheat=2, reroll=3, initial_countdown=15)
        first = campaign.current_config()
        self.assertNotIn("image_path", first)
        campaign.settle_current(backend.CountdownState(9, 0, 18, 1, 2))
        second = campaign.current_config()
        self.assertEqual((18, 1, 2), (
            second["entry_countdown"], second["cheat"], second["reroll"]))

    def test_campaign_settlement_uses_the_current_editable_target(self):
        campaign = backend.CampaignProgress([15, 20, 25])
        result = campaign.settle_current(
            backend.CountdownState(9, 0, 18, 1, 2), target_countdown=19)
        self.assertEqual(19.0, result["target_countdown"])
        self.assertFalse(result["won"])


class CountdownCompatibilityTests(unittest.TestCase):
    def test_locked_compatibility_returns_the_separate_win_policy_rate(self):
        try:
            from . import test_countdown_optimizer as compatibility
        except ImportError:
            import test_countdown_optimizer as compatibility

        class DivergentController(backend.MonteCarloController):
            def recommend(self, context, target=None, *_args, **_kwargs):
                action = self.legal_actions(context)[0]
                mean_stats, win_stats = backend.MCSampleStats(), backend.MCSampleStats()
                mean_stats.append(0, target)
                win_stats.append(100, target)
                return backend.MCRecommendation(
                    context, {action: mean_stats}, action, action, 1, 2,
                    {action: win_stats})

        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        with patch.object(compatibility, "MonteCarloController",
                          DivergentController):
            result = compatibility.analyze_single_map(
                nodes=nodes, edges={0: [1], 1: []}, start_idx=0,
                infectable=set(), effect_state="locked",
                observed_effect=backend.EFFECT_NOTHING, target_cd=50,
                n_train=1, n_sim_trials=2, verbose=False)
        self.assertEqual(1.0, result["win_rate"])

    def test_unlocked_compatibility_evaluates_all_six_first_effects(self):
        try:
            from .test_countdown_optimizer import analyze_single_map
        except ImportError:
            from test_countdown_optimizer import analyze_single_map

        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        result = analyze_single_map(
            nodes=nodes, edges={0: [1], 1: []}, start_idx=0,
            infectable=set(), effect_state="unlocked", target_cd=1,
            n_train=120, n_sim_trials=600, verbose=False)
        self.assertAlmostEqual(-5 / 3, result["eval"]["mean"])
        self.assertAlmostEqual(1 / 3, result["win_rate"])
        self.assertEqual(600, result["eval"]["n_rollouts"])
        self.assertEqual(600, result["conditional_evaluation_rollouts"])
        self.assertEqual(set(backend.ALL_EFFECTS), set(result["recommendations_by_effect"]))
        self.assertIsNone(result["recommendation"])

    def test_unlocked_trains_every_condition_before_freezing_any_report(self):
        try:
            from . import test_countdown_optimizer as compatibility
        except ImportError:
            import test_countdown_optimizer as compatibility

        events = []

        class RecordingController(backend.MonteCarloController):
            def refine_current_state(self, context, *args, **kwargs):
                events.append(("train", context.observed_effect))
                return super().refine_current_state(context, *args, **kwargs)

            def evaluate_current_policy(self, context, *args, **kwargs):
                events.append(("evaluate", context.observed_effect))
                return super().evaluate_current_policy(context, *args, **kwargs)

        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        with patch.object(compatibility, "MonteCarloController", RecordingController):
            compatibility.analyze_single_map(
                nodes=nodes, edges={0: [1], 1: []}, start_idx=0,
                infectable=set(), effect_state="unlocked",
                n_train=12, n_eval=12, n_sim_trials=12, verbose=False)
        self.assertEqual(
            [("train", effect) for effect in backend.ALL_EFFECTS]
            + [("evaluate", effect) for effect in backend.ALL_EFFECTS], events)

    def test_legacy_entry_delegates_to_the_pure_mc_backend(self):
        try:
            from .test_countdown_optimizer import analyze_single_map
        except ImportError:
            from test_countdown_optimizer import analyze_single_map

        nodes = [
            {"idx": 0, "name": "start", "cx": 0, "cy": 0},
            {"idx": 1, "name": "normal", "cx": 100, "cy": 0},
            {"idx": 2, "name": "infected", "cx": 100, "cy": 80},
        ]
        result = analyze_single_map(
            nodes=nodes, edges={0: [1, 2], 1: [], 2: []}, start_idx=0,
            infectable={2}, cheat=0, reroll=0, initial_countdown=0,
            observed_effect=backend.EFFECT_NOTHING, effect_state="locked",
            target_cd=1, n_train=20, n_sim_trials=20, verbose=False)
        self.assertEqual("keep", result["recommended_action"])
        self.assertEqual(1.0, result["eval"]["mean"])
        self.assertEqual(1.0, result["win_rate"])
        self.assertIsInstance(result["mc"], backend.MonteCarloController)
        self.assertIsNone(result["future_table"])

    def test_settled_compatibility_context_never_reapplies_adjacent_effect(self):
        try:
            from .test_countdown_optimizer import analyze_single_map
        except ImportError:
            from test_countdown_optimizer import analyze_single_map

        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 200, "cy": 0},
        ]
        result = analyze_single_map(
            nodes=nodes, edges={0: [1], 1: [2], 2: []}, start_idx=0,
            infectable=set(), observed_effect=backend.EFFECT_ADJACENT,
            effect_state="settled", n_train=10, n_sim_trials=10, verbose=False)
        self.assertIsNone(result["recommendation"].context.locked_effect)


if __name__ == "__main__":
    unittest.main(verbosity=2)
