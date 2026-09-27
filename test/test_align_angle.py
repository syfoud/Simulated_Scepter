"""隔离 Win32、截图与键鼠，只验证校准计算、取消及资源所有权。"""

import ast
import math
import sys
import threading
import unittest
from pathlib import Path
from statistics import median
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class AlignAngleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.saved = []
        self.manager = Mock(running=False, multi=1.75)
        self.manager.start.side_effect = self.start_manager
        self.manager.stop.side_effect = self.stop_manager
        self.config = SimpleNamespace(angle="1.75", save=Mock(side_effect=self.save_config))
        self.su = SimpleNamespace(
            screen=object(), get_screen=Mock(),
            sct=Mock(close=Mock(side_effect=self.close_screen)),
            pos_predictor=Mock(),
        )
        self.stop_flag = Mock(return_value=False)
        self.namespace = {
            "math": math,
            "median": median,
            "time": SimpleNamespace(sleep=Mock()),
            "get_global_stop_flag": self.stop_flag,
            "key_mouse_manager": self.manager,
            "CUS_LOGGER": Mock(),
        }
        path = Path(__file__).resolve().parents[1] / "align_angle.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), self.namespace)
        self.main = self.namespace["main"]
        self.get_angle = self.namespace["get_angle"]
        modules = {}
        for name in ("tool.simul.config", "tool.diver.config"):
            modules[name] = ModuleType(name)
            modules[name].config = self.config
        modules["tool.simul.utils"] = ModuleType("tool.simul.utils")
        modules["tool.simul.utils"].UniverseUtils = Mock(side_effect=self.make_universe)
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)

    def start_manager(self):
        self.events.append(("start", threading.get_ident()))
        self.manager.running = True

    def stop_manager(self):
        self.events.append(("stop", threading.get_ident()))
        self.manager.running = False

    def close_screen(self):
        self.events.append(("close", threading.get_ident()))

    def make_universe(self):
        self.events.append(("create", threading.get_ident()))
        return self.su

    def save_config(self):
        self.saved.append(self.config.angle)

    def set_angles(self, *angles):
        self.namespace["get_angle"] = Mock(side_effect=angles)

    def assert_unchanged(self):
        self.assertEqual(self.manager.multi, 1.75)
        self.assertEqual(self.config.angle, "1.75")
        self.config.save.assert_not_called()

    def test_direction_validation_rejects_missing_heading(self):
        self.su.pos_predictor.update_minimap_data.return_value = (30, None)
        self.assertIsNone(self.get_angle(self.su))
        self.su.pos_predictor.update_minimap_data.assert_called_once_with(
            self.su.screen,
        )
        # 方向 0 度是有效结果，不能被当成低可信方向。
        self.su.pos_predictor.update_minimap_data.return_value = (30, 0)
        self.assertEqual(self.get_angle(self.su), 30)

    def test_cancel_before_angle_read_does_not_queue_input(self):
        self.stop_flag.return_value = True
        self.assertIsNone(self.get_angle(self.su))
        self.manager.press.assert_not_called()
        self.su.get_screen.assert_not_called()

    def test_cancel_after_movement_does_not_capture(self):
        self.stop_flag.side_effect = [False, True]
        self.assertIsNone(self.get_angle(self.su))
        self.manager.press.assert_called_once_with("w")
        self.manager.wait.assert_called_once()
        self.su.get_screen.assert_not_called()

    def test_unreliable_initial_angle_keeps_previous_multiplier(self):
        for angle in (None, math.nan, math.inf):
            with self.subTest(angle=angle):
                self.set_angles(angle)
                self.assertFalse(self.main(ang=(1,), su=self.su))
                self.assert_unchanged()
        self.manager.mouse_move.assert_not_called()
        self.su.sct.close.assert_not_called()

    def test_zero_turn_does_not_divide_or_save(self):
        self.set_angles(10, 10)
        self.assertFalse(self.main(ang=(1,), su=self.su))
        self.assert_unchanged()

    def test_unreliable_angle_midway_does_not_save(self):
        self.set_angles(10, 40, None)
        self.assertFalse(self.main(ang=(3,), su=self.su))
        self.assert_unchanged()
        self.assertEqual(self.manager.mouse_move.call_count, 2)

    def test_capture_exception_restores_multiplier_and_releases_owned_resources(self):
        self.set_angles(10, RuntimeError("截图失败"))
        with self.assertRaisesRegex(RuntimeError, "截图失败"):
            self.main(ang=(1,))
        self.assert_unchanged()
        self.assertEqual([event for event, _ in self.events], ["create", "start", "stop", "close"])

    def test_cancel_midway_stops_additional_turns_and_keeps_config(self):
        self.stop_flag.side_effect = [False, False, True]
        self.set_angles(10, 40)
        self.assertFalse(self.main(ang=(3,), su=self.su))
        self.assert_unchanged()
        self.manager.mouse_move.assert_called_once_with(60, fine=1)

    def test_cancel_before_save_restores_previous_multiplier(self):
        self.stop_flag.side_effect = [False, False, True]
        self.set_angles(10, 40)
        self.assertFalse(self.main(ang=(1,), su=self.su))
        self.assert_unchanged()

    def test_success_saves_multiplier_and_closes_resources_on_owner_thread(self):
        self.set_angles(350, 20)
        self.assertTrue(self.main(ang=(1,)))
        self.assertAlmostEqual(self.manager.multi, 2.0)
        self.assertEqual(self.saved, [str(self.manager.multi)])
        self.config.save.assert_called_once()
        self.assertEqual([event for event, _ in self.events], ["create", "start", "stop", "close"])
        self.assertEqual({ident for _, ident in self.events}, {threading.get_ident()})

    def test_borrowed_universe_and_running_manager_remain_available(self):
        self.manager.running = True
        self.set_angles(10, 40)
        self.assertTrue(self.main(ang=(1,), su=self.su))
        self.assertTrue(self.manager.running)
        self.manager.stop.assert_not_called()
        self.su.sct.close.assert_not_called()

    def test_borrowed_resources_are_not_closed_when_calibration_fails(self):
        self.manager.running = True
        self.set_angles(10, None)
        self.assertFalse(self.main(ang=(1,), su=self.su))
        self.assert_unchanged()
        self.assertTrue(self.manager.running)
        self.manager.stop.assert_not_called()
        self.su.sct.close.assert_not_called()

    def test_save_failure_restores_multiplier_and_in_memory_config(self):
        self.set_angles(10, 40)
        self.config.save.side_effect = OSError("配置写入失败")
        with self.assertRaisesRegex(OSError, "配置写入失败"):
            self.main(ang=(1,))
        self.assertEqual(self.manager.multi, 1.75)
        self.assertEqual(self.config.angle, "1.75")
        self.assertEqual([event for event, _ in self.events], ["create", "start", "stop", "close"])

    def test_screen_closes_even_if_manager_cleanup_raises(self):
        self.set_angles(None)
        self.manager.stop.side_effect = RuntimeError("按键释放失败")
        with self.assertRaisesRegex(RuntimeError, "按键释放失败"):
            self.main(ang=(1,))
        self.assert_unchanged()
        self.su.sct.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
