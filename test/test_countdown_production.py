"""生产倒计时决策接口回归测试。"""

import json
import tempfile
import unittest
from xml.etree import ElementTree
from pathlib import Path
from unittest.mock import patch

from tool.countdown_evaluator import (
    CountdownDecisionAgent,
    DECISION_DP,
    DECISION_MC,
    DECISION_WIN_RATE,
    DECISION_WIN_RATE_DP,
    DecisionContext,
    EFFECT_ADJACENT,
    EFFECT_NOTHING,
    EFFECT_SELECT,
    EFFECT_SPREAD,
    MCConfig,
    MCRecommendation,
    MCSampleStats,
    PHASE_PATH,
    PHASE_EFFECT,
    PHASE_TARGET,
    PHASE_TERMINAL,
    parse_effect_text,
)
from tool.countdown_config import (
    DECISION_MODES, EARLY_STOP_FIELDS, load_finger_snap_settings,
    save_finger_snap_settings,
)


def linear_map():
    nodes = [
        {"idx": 0, "cx": 0, "cy": 0},
        {"idx": 1, "cx": 100, "cy": 0},
        {"idx": 2, "cx": 200, "cy": 0},
    ]
    return nodes, {0: [1], 1: [2], 2: []}


class CountdownProductionTests(unittest.TestCase):
    def setUp(self):
        self.agent = CountdownDecisionAgent(MCConfig(
            control_rollouts=120, evaluation_rollouts=120,
            min_visits=10, seed=7))
        nodes, edges = linear_map()
        self.agent.load_map(nodes, edges, 0, (), 15, 1, 2, plane=1)

    def test_effect_text_accepts_ui_names_inside_ocr_text(self):
        self.assertEqual(EFFECT_SELECT, parse_effect_text("本次效果：慈怀"))
        self.assertEqual(EFFECT_ADJACENT, parse_effect_text("本次效果：丰饶对症"))
        self.assertEqual(EFFECT_SPREAD, parse_effect_text("本次效果：丰饶浇灌"))
        self.assertIsNone(parse_effect_text("OCR失败"))

    def test_finger_snap_only_calls_the_production_decision_interface(self):
        source = (Path(__file__).parents[1] / "finger_snap.py").read_text(
            encoding="utf-8")
        self.assertIn("from tool.countdown_evaluator import", source)
        self.assertNotIn("evaluate_best_single_replacement", source)
        self.assertNotIn("max_weight_path", source)
        self.assertIn("if not self.debug:", source)
        self.assertNotIn("def _dp_should_stop", source)
        early_stop = source[source.index("    def _log_decision"):
                            source.index("        win_rate =", source.index("    def _log_decision"))]
        self.assertIn("advice.context.phase == PHASE_EFFECT", early_stop)
        self.assertIn('text="确认效果"', early_stop)
        self.assertIn("advice.context.phase == PHASE_TARGET", early_stop)
        self.assertIn(
            "self.abandon_confirm(confirm=True, allow_fail=True)", early_stop)
        self.assertNotIn('key_mouse_manager.press("esc")', early_stop)
        self.assertIn("else:\n                return False", early_stop)
        select_doing = source[source.index("    def select_doing"):
                              source.index("    def select_go")]
        select_go = source[source.index("    def select_go"):
                           source.index("    def initing_map")]
        calculated_roll = source[source.index("    def calculated_roll"):
                                 source.index("    def cheat")]
        self.assertNotIn("countdown_agent.apply_target", select_doing)
        self.assertIn("try_analysis_map(mode=2, target_selection=True)", select_doing)
        self.assertIn("self._pending_target = int(advice.action)", select_doing)
        self.assertNotIn(
            "if not (self.countdown_agent.ready and self.countdown_agent.context",
            select_doing)
        self.assertLess(
            select_doing.index("try_analysis_map(mode=2, target_selection=True)"),
            select_doing.index("countdown_agent.recommend_target()"))
        self.assertNotIn('click_text(text="确认目标"', select_doing)
        self.assertIn("key_mouse_manager.click(1685, 982)", select_doing)
        confirm_click = select_doing.index("key_mouse_manager.click(1685, 982)")
        self.assertIn("self._pending_target = None", select_doing[confirm_click:])
        self.assertIn("self._target_decided = False", select_doing[confirm_click:])
        self.assertNotIn("countdown_agent.apply_target", select_go)
        self.assertIn("感染结果已由当前截图同步", select_go)
        candidate = select_go.index("candidate_countdown = num // 5")
        confirmation = select_go.index("confirmed_num = extract_number")
        commit = select_go.index("self.countdown = candidate_countdown")
        self.assertLess(candidate, confirmation)
        self.assertLess(confirmation, commit)
        self.assertIn("保留倒计时{self.countdown}", select_go)
        pending_branch = calculated_roll[
            calculated_roll.index("pending_effect = self._pending_cheat_effect"):
            calculated_roll.index("\n        if observed is None:")]
        self.assertIn("if observed == pending_effect:", pending_branch)
        self.assertIn('text="确认效果"', pending_branch)
        self.assertIn("不重复决策", pending_branch)
        self.assertNotIn("recommend_effect", pending_branch)
        self.assertLess(
            calculated_roll.index("pending_effect = self._pending_cheat_effect"),
            calculated_roll.index("recommend_effect(observed)"))
        self.assertIn("self._pending_cheat_effect = int(action[1])", calculated_roll)

    def test_target_selection_ignores_cyan_borders_and_detects_green_applied_nodes(self):
        import cv2
        import numpy as np

        from tool.utils.analysis_map import detect_infectable_nodes

        image = np.zeros((160, 320, 3), np.uint8)
        matches = [{"location": (40, 40), "size": (60, 60)},
                   {"location": (200, 40), "size": (60, 60)}]
        cv2.rectangle(image, (30, 30), (110, 110), (255, 200, 0), 12)
        cv2.rectangle(image, (190, 30), (270, 110), (255, 200, 0), 12)
        cv2.rectangle(image, (185, 25), (275, 115), (80, 230, 100), 16)
        self.assertEqual(
            [1], detect_infectable_nodes(image, matches, target_selection=True))

    def test_thin_green_halo_is_detected_in_path_selection(self):
        import cv2
        import numpy as np

        from tool.utils.analysis_map import detect_infectable_nodes

        image = np.full((120, 120, 3), (80, 45, 75), np.uint8)
        matches = [{"location": (35, 35), "size": (50, 50)}]
        cv2.rectangle(image, (25, 25), (95, 95), (100, 205, 125), 4)
        self.assertEqual([0], detect_infectable_nodes(image, matches))
        self.assertEqual(
            [0], detect_infectable_nodes(image, matches, target_selection=True))

    def test_finger_snap_settings_are_saved_separately_from_iron_blood(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"first_plane": 14}), encoding="utf-8")
            save_finger_snap_settings({
                "control_rollouts": 321,
                "win_rate_noise_floor_percent": 0.35,
                "path_reward_bonus": 0.002,
                "decision_mode": DECISION_WIN_RATE,
                "dp_early_stop": True,
                "win_rate_dp_early_stop": True,
                "mc_dp_early_stop": True,
                "plane_targets": [16, 76, 81],
            }, path)
            complete = json.loads(path.read_text(encoding="utf-8"))
            loaded = load_finger_snap_settings(path)
        self.assertEqual(14, complete["first_plane"])
        self.assertEqual(321, loaded["control_rollouts"])
        self.assertEqual(0.35, loaded["win_rate_noise_floor_percent"])
        self.assertEqual(0.002, loaded["path_reward_bonus"])
        self.assertEqual(DECISION_WIN_RATE, loaded["decision_mode"])
        self.assertTrue(loaded["dp_early_stop"])
        self.assertTrue(loaded["win_rate_dp_early_stop"])
        self.assertTrue(loaded["mc_dp_early_stop"])
        self.assertEqual([16, 76, 81], loaded["plane_targets"])

    def test_every_decision_mode_resolves_its_real_early_stop_key(self):
        settings = load_finger_snap_settings(Path(__file__).parents[1]
                                             / "config/config/settings_example.json")
        self.assertEqual(
            {"dp_early_stop", "win_rate_dp_early_stop", "mc_dp_early_stop"},
            {EARLY_STOP_FIELDS[mode] for mode in (
                DECISION_DP, DECISION_WIN_RATE, DECISION_WIN_RATE_DP, DECISION_MC)})
        self.assertTrue(all(key in settings for key in EARLY_STOP_FIELDS.values()))
        self.assertIn(DECISION_WIN_RATE_DP, DECISION_MODES)

    def test_finger_snap_controls_live_in_advanced_settings_tab(self):
        root = ElementTree.parse(
            Path(__file__).parents[1] / "resource" / "ui" / "UI.ui").getroot()
        tabs = next(widget for widget in root.iter("widget")
                    if widget.get("name") == "tabWidget").findall("widget")
        self.assertNotIn("FingerSnapTab", [tab.get("name") for tab in tabs])
        iron_tab = next(tab for tab in tabs if tab.get("name") == "AbyssTab")
        controls = {widget.get("name") for widget in iron_tab.iter("widget")}
        self.assertTrue({"Finger_snap_group",
                         "Finger_snap_win_rate_noise_floor_percent_input",
                         "Finger_snap_dp_early_stop_checkbox",
                         "Finger_snap_win_rate_dp_early_stop_checkbox",
                         "Finger_snap_mc_dp_early_stop_checkbox"} <= controls)

    def test_tiny_path_bonus_breaks_near_ties_but_not_real_score_gaps(self):
        names = ("reward", "event", "trade", "adventure", "bugevent", "battle")
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0, "name": "start"},
            *({"idx": idx, "cx": 100, "cy": idx * 100, "name": name}
              for idx, name in enumerate(names, 1)),
        ]
        edges = {0: list(range(1, 7)), **{idx: [] for idx in range(1, 7)}}
        self.agent.load_map(nodes, edges, 0, (), 15, 1, 2)
        context = self.agent.apply_effect_action(EFFECT_NOTHING, "keep")
        bonuses = [self.agent.controller._score_bonus(context, idx)
                   for idx in range(1, 7)]
        self.assertTrue(all(left > right
                            for left, right in zip(bonuses, bonuses[1:])))

        def recommendation(reward_mean):
            reports = {idx: MCSampleStats() for idx in range(1, 7)}
            for stats in reports.values():
                stats.append(0.0)
            reports[1] = MCSampleStats()
            reports[6] = MCSampleStats()
            reports[1].append(reward_mean)
            reports[6].append(10.0)
            with patch.object(self.agent.controller, "evaluate_actions",
                              return_value=(reports, 6)):
                return self.agent.controller.evaluate_current_policy(
                    context, evaluation_rollouts=6).recommended_action

        self.assertEqual(1, recommendation(9.9993))
        self.assertEqual(6, recommendation(9.9991))

    def test_win_rate_mode_falls_back_to_mean_when_every_rate_is_zero(self):
        decision_context = DecisionContext(
            PHASE_EFFECT, self.agent.state, EFFECT_NOTHING)
        mean_reports = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        mean_reports["keep"].append(20)
        mean_reports["reroll"].append(10)
        win_reports = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        for stats in win_reports.values():
            stats.append(0, 100)
        recommendation = MCRecommendation(
            decision_context, mean_reports, "keep", "reroll", 10, 10, win_reports)
        self.agent.decision_mode = DECISION_WIN_RATE
        with patch.object(self.agent.controller, "recommend", return_value=recommendation):
            self.assertEqual("keep", self.agent.recommend_effect(EFFECT_NOTHING).action)
        win_reports["reroll"].append(100, 100)
        with patch.object(self.agent.controller, "recommend", return_value=recommendation):
            self.assertEqual("reroll", self.agent.recommend_effect(EFFECT_NOTHING).action)
        self.agent.decision_mode = DECISION_MC
        with patch.object(self.agent.controller, "recommend", return_value=recommendation):
            self.assertEqual("keep", self.agent.recommend_effect(EFFECT_NOTHING).action)

        self.agent.calculate_dp_upper_bound = True
        for mode in (DECISION_MC, DECISION_WIN_RATE):
            self.agent.decision_mode = mode
            with patch.object(self.agent.controller, "recommend",
                              return_value=recommendation):
                self.assertIsNotNone(
                    self.agent.recommend_effect(EFFECT_NOTHING).dp_upper_bound)

    def test_win_rate_dp_mode_uses_dp_only_when_every_win_rate_is_zero(self):
        context = DecisionContext(PHASE_EFFECT, self.agent.state, EFFECT_NOTHING)
        means = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        wins = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        means["keep"].append(20)
        means["reroll"].append(10)
        for stats in wins.values():
            stats.append(0, 100)
        recommendation = MCRecommendation(
            context, means, "keep", "keep", 10, 10, wins)
        self.agent.decision_mode = DECISION_WIN_RATE_DP
        dp_advice = self.agent._recommend_dp(context)
        with (patch.object(self.agent.controller, "recommend", return_value=recommendation),
              patch.object(self.agent, "_recommend_dp", return_value=dp_advice) as dp):
            self.assertEqual(dp_advice.action,
                             self.agent.recommend_effect(EFFECT_NOTHING).action)
            dp.assert_called_once()

        wins["reroll"].append(100, 100)
        recommendation = MCRecommendation(
            context, means, "keep", "reroll", 10, 10, wins)
        with (patch.object(self.agent.controller, "recommend", return_value=recommendation),
              patch.object(self.agent, "_recommend_dp",
                           side_effect=AssertionError("有非零胜率时不应调用 DP"))):
            self.assertEqual("reroll", self.agent.recommend_effect(EFFECT_NOTHING).action)

    def test_win_rate_noise_floor_filters_single_hit_but_keeps_larger_rate(self):
        self.agent.config = MCConfig(
            control_rollouts=120, evaluation_rollouts=120,
            min_visits=10, seed=7,
            win_rate_noise_floor_percent=0.2).normalized()
        self.agent.decision_mode = DECISION_WIN_RATE_DP
        context = DecisionContext(PHASE_EFFECT, self.agent.state, EFFECT_NOTHING)
        means = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        for stats in means.values():
            stats.append(10)
        wins = {"keep": MCSampleStats(), "reroll": MCSampleStats()}
        wins["keep"].target_count = wins["reroll"].target_count = 714
        wins["reroll"].wins = 1  # 0.1401% < 0.2%
        recommendation = MCRecommendation(
            context, means, "keep", "reroll", 10, 714, wins)
        dp_advice = self.agent._recommend_dp(context)
        with (patch.object(self.agent.controller, "recommend", return_value=recommendation),
              patch.object(self.agent, "_recommend_dp", return_value=dp_advice) as dp):
            self.agent.recommend_effect(EFFECT_NOTHING)
            dp.assert_called_once()

        wins["reroll"].wins = 2  # 0.2801% >= 0.2%
        with (patch.object(self.agent.controller, "recommend", return_value=recommendation),
              patch.object(self.agent, "_recommend_dp",
                           side_effect=AssertionError("达到噪声阈值时不应回退 DP"))):
            self.assertEqual(
                "reroll", self.agent.recommend_effect(EFFECT_NOTHING).action)

    def test_dp_mode_drives_path_without_calling_mc(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0, "name": "start"},
            {"idx": 1, "cx": 100, "cy": 0, "name": "reward"},
            {"idx": 2, "cx": 100, "cy": 100, "name": "battle"},
        ]
        agent = CountdownDecisionAgent(MCConfig(), decision_mode=DECISION_DP)
        agent.load_map(nodes, {0: [1, 2], 1: [], 2: []}, 0, (1, 2), 15, 1, 2)
        with patch.object(agent.controller, "recommend",
                          side_effect=AssertionError("DP 模式不应调用 MC")):
            reroll = agent.recommend_effect(EFFECT_NOTHING)
            self.assertEqual("reroll", reroll.action)
            self.assertIsNotNone(reroll.planned_effect)
            self.assertEqual(reroll.expected_countdown, reroll.dp_upper_bound)
            agent.apply_effect_action(EFFECT_NOTHING, "reroll")
            self.assertEqual(
                "keep", agent.recommend_effect(reroll.planned_effect).action)
            self.assertEqual(1, agent.recommend_path().action)

    def test_auxiliary_dp_stops_before_mc_when_target_is_impossible(self):
        nodes, edges = linear_map()
        agent = CountdownDecisionAgent(
            MCConfig(), targets=(100, 100, 100),
            decision_mode=DECISION_MC, calculate_dp_upper_bound=True)
        agent.load_map(nodes, edges, 0, (), 15, 1, 2)
        with patch.object(agent.controller, "recommend",
                          side_effect=AssertionError("判废后不应继续运行 MC")):
            advice = agent.recommend_effect(EFFECT_NOTHING)
        self.assertIn(advice.action, agent.model.legal_actions(advice.context))
        self.assertLess(advice.dp_upper_bound, 100)

        agent.apply_effect_action(EFFECT_NOTHING, "keep")
        with patch.object(agent.controller, "recommend",
                          side_effect=AssertionError("判废后不应继续运行 MC")):
            path = agent.recommend_path()
        self.assertIn(path.action, agent.model.path_options(agent.state))

    def test_recommendation_does_not_mutate_real_resources(self):
        before = self.agent.state
        advice = self.agent.recommend_effect(EFFECT_NOTHING)
        self.assertEqual(before, self.agent.state)
        self.assertIn(advice.action, self.agent.model.legal_actions(advice.context))

    def test_reroll_only_records_consumption_and_waits_for_next_screen(self):
        context = self.agent.apply_effect_action(EFFECT_NOTHING, "reroll")
        self.assertEqual(1, self.agent.state.reroll_rem)
        self.assertIsNone(self.agent.locked_effect)
        self.assertEqual(PHASE_TERMINAL, context.phase)

    def test_cheat_locks_selected_effect_until_path_confirmation(self):
        context = self.agent.apply_effect_action(
            EFFECT_NOTHING, ("cheat", EFFECT_SPREAD))
        self.assertEqual(0, self.agent.state.cheat_rem)
        self.assertEqual(EFFECT_SPREAD, self.agent.locked_effect)
        self.assertEqual(PHASE_PATH, context.phase)

    def test_target_and_path_are_separate_production_decisions(self):
        context = self.agent.apply_effect_action(EFFECT_SELECT, "keep")
        self.assertEqual(PHASE_TARGET, context.phase)
        target = self.agent.recommend_target().action
        self.agent.apply_target(target)
        self.assertTrue(self.agent.state.infected & 1 << int(target))
        path = self.agent.recommend_path().action
        self.assertEqual(1, path)
        self.assertEqual(1, self.agent.apply_path(path).node_idx)

    def test_reload_keeps_only_confirmed_effect_and_external_facts(self):
        self.agent.apply_effect_action(EFFECT_ADJACENT, "keep")
        nodes, edges = linear_map()
        state = self.agent.load_map(
            nodes, edges, 0, (2,), 23, 0, 1,
            plane=2, preserve_effect=True)
        self.assertEqual(EFFECT_ADJACENT, self.agent.locked_effect)
        self.assertEqual(PHASE_PATH, self.agent.context.phase)
        self.assertEqual((23, 0, 1), (
            state.countdown, state.cheat_rem, state.reroll_rem))
        self.assertEqual(1 << 2, state.infected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
