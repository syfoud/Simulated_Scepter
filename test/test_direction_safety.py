"""通过隔离输入验证低可信方向、镜头校正与停止边界。"""

import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from test.test_simul_thread_lifecycle import load_methods


class TurnFailureTests(unittest.TestCase):

    def test_missing_direction_releases_movement_before_returning(self):
        for observations in ([(13, None)], [(13, 212.9), (13, None)]):
            with self.subTest(observations=observations):
                task, manager = self.make_turn(observations)
                self.assertFalse(task.update_direction_data())
                task._abort_walk.assert_called_once()
                manager.mouse_move.assert_not_called()

    def test_bad_position_stops_walking_and_preserves_last_location(self):
        for mode in ("simul", "currency"):
            for score in (0.0, 0.01, float("nan")):
                with self.subTest(mode=mode, score=score):
                    manager = Mock()
                    class_name = "UniverseUtils" if mode == "simul" else "CurrencyUtils"
                    task = load_methods(f"tool/{mode}/utils.py", class_name, {"get_loc"}, {
                        "np": SimpleNamespace(isfinite=math.isfinite),
                        "POSITION_MIN_SIMILARITY": 0.01, "CUS_LOGGER": Mock(),
                        "key_mouse_manager": manager,
                    })
                    task.screen = object()
                    task.now_loc = (10, 20)
                    task._abort_walk = Mock()
                    task.pos_predictor = Mock()
                    task.pos_predictor.update_position.return_value = ((30, 40), score)
                    self.assertFalse(task.get_loc(fresh=False))
                    self.assertEqual(task.now_loc, (10, 20))
                    if mode == "simul":
                        task._abort_walk.assert_called_once()
                    else:
                        manager.clean.assert_called_once()

    def make_turn(self, observations):
        manager = Mock()
        task = load_methods("tool/simul/utils.py", "UniverseUtils", {"update_direction_data"}, {
            "CUS_LOGGER": Mock(), "key_mouse_manager": manager,
            "math": math, "get_dis": math.dist,
            "CAMERA_ARROW_SIMILARITY": 0.9, "CAMERA_VIEW_CONFIDENCE": 0.7,
        })
        task._stop = False
        task.screen, task.sct = object(), Mock()
        task.now_loc, task.target_loc = (562.4, 307.0), (580.29, 281.47)
        task.pos_predictor = SimpleNamespace(
            update_minimap_data=Mock(side_effect=observations),
            direction_similarity=0.961, rotation_confidence=0.97,
        )
        task.get_screen = Mock(return_value=task.screen)
        task.check = Mock(return_value=True)
        task._abort_walk = Mock()
        return task, manager

    def test_camera_alignment_recovers_recorded_idle_mismatch_without_walking(self):
        # 实际故障为镜头 13°、人物 212.9°；只转镜头，复核一致后才返回导航距离。
        task, manager = self.make_turn([(13, 212.9), (13, 212.9), (213, 212.9)])
        self.assertGreater(task.update_direction_data(), 0)
        self.assertAlmostEqual(manager.mouse_move.call_args_list[0].args[0], -160.1)
        self.assertEqual(manager.mouse_move.call_count, 2)
        manager.keyDown.assert_not_called()
        manager.click.assert_not_called()
        task._abort_walk.assert_called()

    def test_unconfirmed_alignment_does_not_issue_target_turn(self):
        for final in ((13, 212.9), (213, None)):
            with self.subTest(final=final):
                task, manager = self.make_turn([(13, 212.9), (13, 212.9), final])
                self.assertFalse(task.update_direction_data())
                self.assertEqual(manager.mouse_move.call_count, 1)
                manager.keyDown.assert_not_called()
                manager.click.assert_not_called()

    def test_changing_or_weak_heading_keeps_original_rejection(self):
        for observations, arrow, view in (
            ([(13, 212.9), (50, 212.9)], 0.961, 0.97),
            ([(13, 212.9), (13, 180)], 0.961, 0.97),
            ([(13, 212.9), (13, 212.9)], 0.89, 0.97),
            ([(13, 212.9), (13, 212.9)], 0.961, 0.69),
        ):
            with self.subTest(observations=observations, arrow=arrow, view=view):
                task, manager = self.make_turn(observations)
                task.pos_predictor.direction_similarity = arrow
                task.pos_predictor.rotation_confidence = view
                self.assertFalse(task.update_direction_data())
                manager.mouse_move.assert_not_called()
                manager.keyDown.assert_not_called()

    def test_non_world_frame_or_stop_before_alignment_sends_no_turn(self):
        task, manager = self.make_turn([(13, 212.9)] * 2)
        task.check.return_value = False
        self.assertFalse(task.update_direction_data())
        manager.mouse_move.assert_not_called()
        task, manager = self.make_turn([(13, 212.9)] * 2)
        task._abort_walk.side_effect = lambda: setattr(task, "_stop", True)
        self.assertFalse(task.update_direction_data())
        manager.mouse_move.assert_not_called()

    def test_world_disappears_after_alignment_does_not_resume_navigation(self):
        task, manager = self.make_turn([(13, 212.9), (13, 212.9), (213, 212.9)])
        task.check.side_effect = [True, False]
        self.assertFalse(task.update_direction_data())
        self.assertEqual(manager.mouse_move.call_count, 1)
        manager.keyDown.assert_not_called()

    def test_aligned_view_and_moving_mode_keep_existing_turn(self):
        for observations, mode in (([(13, 13)], None), ([(13, 212.9)] * 2, 1)):
            with self.subTest(mode=mode):
                task, manager = self.make_turn(observations)
                self.assertGreater(task.update_direction_data(mode=mode), 0)
                self.assertEqual(manager.mouse_move.call_count, 1)
                task._abort_walk.assert_not_called()

    def test_stop_or_capture_failure_after_alignment_cannot_resume_navigation(self):
        task, manager = self.make_turn([(13, 212.9)] * 2)
        manager.mouse_move.side_effect = lambda *a: setattr(task, "_stop", True)
        self.assertFalse(task.update_direction_data())
        self.assertEqual(manager.mouse_move.call_count, 1)
        manager.keyDown.assert_not_called()

        task, manager = self.make_turn([(13, 212.9)] * 2)
        task.get_screen.side_effect = [task.screen, RuntimeError("游戏窗口已失去前台")]
        with self.assertRaisesRegex(RuntimeError, "失去前台"):
            task.update_direction_data()
        self.assertEqual(manager.mouse_move.call_count, 1)
        task._abort_walk.assert_called()
        manager.keyDown.assert_not_called()
