"""隔离窗口与设备，验证独立通用内核的识别、输入和清理。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from core.common import runtime
from test.core_fixture import copy_core
from tool.registry import KernelRegistry
from tool.utils.game_window import GameWindow


class CommonRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch.object(runtime, "key_mouse_manager", self.manager))
        self.enterContext(patch("core.common.engine.key_mouse_manager", self.manager))
        self.stop_flag = self.enterContext(patch.object(runtime, "get_global_stop_flag", return_value=False))
        self.enterContext(patch("tool.action_script.get_global_stop_flag", side_effect=lambda: self.stop_flag.return_value))
        self.enterContext(patch.object(runtime, "set_game_foreground"))
        self.window = self.enterContext(patch.object(runtime, "get_foreground_game_window", return_value=
            GameWindow(1, "local", "game", "UnityWndClass", 1920, 1080)))
        self.enterContext(patch.object(runtime, "get_client_screen_rect", return_value=(20, 30, 1940, 1110)))
        self.capture = self.enterContext(patch.object(runtime, "Screen"))
        self.frame = np.random.default_rng(13).integers(32, 255, (1080, 1920, 3), dtype=np.uint8)
        self.capture.return_value.grab.return_value = self.frame
        self.ocr = self.enterContext(patch.object(runtime, "get_global_my_ts", return_value=Mock()))

    def kernel(self):
        engine = runtime.ScriptKernel()
        self.addCleanup(engine.stop)
        return engine

    def test_common_factory_operates_with_all_business_modules_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_core(Path(temporary) / "core")
            for module in root.iterdir():
                if module.is_dir() and module.name not in ("common", "__pycache__"):
                    module.rename(Path(temporary) / module.name)
            registry = KernelRegistry(root)
            self.assertEqual([spec.id for spec in registry.runnable()], ["Common"])
            self.assertFalse(registry.errors)
            engine = registry.create_engine("Common", script=True)
            self.addCleanup(engine.stop)
            self.assertIsInstance(engine, registry.load_class("Common"))
            self.assertIs(engine.get_screen(), self.frame)
            self.manager.set_config.assert_called_once_with(None)
            self.manager.set_screen_params.assert_called_once_with(1940, 1110, 1920, 1080, False)

    def test_real_action_loop_recognizes_text_and_executes_coordinates_then_stops(self):
        engine = self.kernel()
        engine.ts.find_with_box.return_value = [{"raw_text": "确认", "box": [10, 20, 10, 20]}]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "script.json"
            path.write_text(json.dumps([{"name": "确认", "trigger": {"text": "确认", "box": [0, 100, 0, 100]},
                                        "actions": [{"position": [960, 540]}, {"press": "f"}, "stop"]}]), encoding="utf-8")
            engine.start(path)
        self.manager.click.assert_called_once_with(0.5, 0.5)
        self.manager.press.assert_called_once_with("f", 0)
        self.assertEqual(engine.action_history, ["确认"])
        self.assertTrue(engine._stop)
        self.capture.return_value.close.assert_called_once()

    def test_shared_template_match_and_position_crop_use_game_coordinates(self):
        engine = self.kernel()
        engine.get_screen()
        template = self.frame[535:545, 955:965].copy()
        self.assertTrue(engine.click_target(template, 0.99, flag=False))
        with patch("core.common.engine.find_image_by_name", return_value=template):
            self.assertTrue(engine.check("button", 0.5, 0.5, threshold=0.99))
        self.assertAlmostEqual(engine.tx, 0.5)
        self.assertAlmostEqual(engine.ty, 0.5)

    def test_wrong_resolution_rejects_input_and_capture(self):
        self.window.return_value = GameWindow(1, "local", "game", "UnityWndClass", 1280, 720)
        with self.assertRaisesRegex(ValueError, "1280 × 720"):
            runtime.create_engine()
        self.capture.assert_not_called()
        self.manager.start.assert_not_called()

    def test_cancellation_while_waiting_does_not_reset_the_stop_request(self):
        self.stop_flag.return_value = True
        engine = runtime.create_engine()
        self.assertTrue(engine._stop)
        self.assertTrue(self.stop_flag.return_value)
        self.capture.assert_not_called()
        engine.prepare_script()
        self.manager.start.assert_not_called()

    def test_script_failure_closes_capture_and_releases_input(self):
        engine = self.kernel()
        engine.ts.forward.side_effect = RuntimeError("OCR failed")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "script.json"
            path.write_text('[{"name":"test","trigger":{"state_only":true},"actions":[]}]', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "OCR failed"):
                engine.start(path)
        self.manager.stop.assert_called_once()
        self.capture.return_value.close.assert_called_once()

    def test_stop_keeps_last_frame_and_closes_capture_once(self):
        engine = self.kernel()
        self.assertIs(engine.get_screen(), self.frame)
        engine.stop()
        engine.stop()
        self.assertIs(engine.get_screen(), self.frame)
        self.capture.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
