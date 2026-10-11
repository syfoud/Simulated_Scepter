"""验证游戏画面取样、图片保存、单轮调试和 Qt 框选，隔离键鼠执行。"""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from core.common.engine import StateKernel
from route import PATHS
from tool.gui.script_editor import ScriptEditor, new_event
from tool.gui.trigger_sample import TriggerSample
from tool.script_files import save_script
from tool.script_tools import (
    capture_sample,
    debug_events,
    marker_path,
    save_marker,
    text_trigger,
)
from tool.utils import image_tool


class ScriptToolsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.enterContext(patch.dict(PATHS, {"image": str(self.root / "imgs")}))
        self.enterContext(patch("tool.script_tools.get_global_stop_flag", return_value=False))
        self.enterContext(patch("tool.script_tools.key_mouse_manager", Mock()))
        self.clock = SimpleNamespace(now=0)
        def advance(seconds):
            self.clock.now += seconds
        self.enterContext(patch("tool.script_tools.time", SimpleNamespace(monotonic=lambda: self.clock.now, sleep=advance)))
        self.window = SimpleNamespace(hwnd=17)
        self.enterContext(patch("tool.script_tools.set_game_foreground", return_value=self.window))
        self.foreground = self.enterContext(patch("tool.script_tools.get_foreground_game_window", return_value=self.window))
        self.enterContext(patch.object(image_tool, "_path_cache", {}))
        self.frame = np.random.default_rng(8).integers(0, 256, (108, 192, 3), dtype=np.uint8)

    def test_sample_owns_frame_and_text_snapshot_without_preparing_input(self):
        texts = [{"raw_text": "开始 1", "box": [20, 80, 30, 50]}]
        engine = Mock(_stop=False)
        engine.get_screen.return_value = self.frame
        engine.ts.res = texts
        sample = capture_sample(engine, True)
        engine.prepare_script.assert_not_called()
        engine.ts.forward.assert_called_once()
        self.frame[:] = 0
        texts[0]["box"][0] = 99
        self.assertTrue(np.any(sample["screen"]))
        self.assertEqual(sample["texts"][0]["box"][0], 20)

    def test_image_sampling_does_not_run_ocr(self):
        engine = Mock(_stop=False)
        engine.get_screen.return_value = self.frame
        sample = capture_sample(engine, False)
        self.assertEqual(sample["texts"], [])
        engine.ts.forward.assert_not_called()

    def test_text_selection_matches_runtime_normalization(self):
        trigger = text_trigger({"raw_text": "开始！Test 123", "box": [20, 80, 30, 50]})
        self.assertEqual(trigger, {"text": "开始", "box": [20, 80, 30, 50]})
        with self.assertRaisesRegex(ValueError, "为空"):
            text_trigger({"raw_text": "UID 123", "box": [20, 80, 30, 50]})

    def test_marker_preserves_pixels_is_discoverable_and_matches_local_coordinates(self):
        trigger, path = save_marker(self.frame, [20, 70, 30, 60], marker_path("确认事件"))
        np.testing.assert_array_equal(cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR),
                                      self.frame[30:60, 20:70])
        self.assertEqual(path.parent, self.root / "imgs/script_markers")
        with patch.object(image_tool, "_image_cache", {}), \
                patch.object(image_tool, "_image_directory", str(self.root / "imgs")):
            loaded = image_tool.find_image_by_name(trigger["photo"])
            np.testing.assert_array_equal(loaded, self.frame[30:60, 20:70])
            kernel = StateKernel()
            kernel.screen = self.frame
            kernel.xx, kernel.yy = 192, 108
            kernel.scx = kernel.scy = 1.0
            kernel.threshold = 0.97
            kernel.config = None
            kernel.last_info = ""
            self.assertTrue(kernel.check(trigger["photo"], **trigger["pos"], threshold=trigger["threshold"]))
            image_tool.load_all_images_from_directory(str(self.root / "imgs"))
            np.testing.assert_array_equal(image_tool.find_image_by_name(trigger["photo"]), loaded)

    def test_invalid_crop_never_saves_a_file(self):
        for box in ([20, 20, 30, 60], [-1, 20, 30, 60], [20, 200, 30, 60]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                save_marker(self.frame, box, marker_path("无效范围"))
        self.assertFalse((self.root / "imgs").exists())

    def test_capture_waits_for_actual_game_focus_and_redraw(self):
        captured_at = []
        engine = Mock(_stop=False)
        engine.get_screen.side_effect = lambda: captured_at.append(self.clock.now) or self.frame
        self.foreground.side_effect = lambda: self.window if self.clock.now >= 0.5 else None
        capture_sample(engine, False)
        self.assertEqual(len(captured_at), 1)
        self.assertGreaterEqual(captured_at[0], 0.8)

    def test_failed_focus_or_another_game_never_captures_or_recognizes(self):
        for foreground in (None, SimpleNamespace(hwnd=99)):
            with self.subTest(foreground=foreground):
                self.clock.now = 0
                self.foreground.return_value = foreground
                engine = Mock(_stop=False)
                with self.assertRaisesRegex(RuntimeError, "焦点"):
                    capture_sample(engine, True)
                engine.get_screen.assert_not_called()
                engine.ts.forward.assert_not_called()

    def test_focus_loss_during_capture_discards_frame_and_retries(self):
        engine = Mock(_stop=False)
        bad_frame = np.zeros_like(self.frame)
        def capture():
            if engine.get_screen.call_count == 1:
                self.foreground.return_value = None
                return bad_frame
            return self.frame
        def advance(seconds):
            self.clock.now += seconds
            self.foreground.return_value = self.window
        engine.get_screen.side_effect = capture
        with patch("tool.script_tools.time.sleep", side_effect=advance):
            sample = capture_sample(engine, True)
        self.assertEqual(engine.get_screen.call_count, 2)
        np.testing.assert_array_equal(sample["screen"], self.frame)
        np.testing.assert_array_equal(engine.ts.forward.call_args.args[0], self.frame)

    def test_stop_while_waiting_prevents_capture(self):
        engine = Mock(_stop=False)
        self.foreground.return_value = None
        with patch("tool.script_tools.get_global_stop_flag", side_effect=lambda: self.clock.now >= 0.15):
            with self.assertRaises(InterruptedError):
                capture_sample(engine, False)
        engine.get_screen.assert_not_called()
        self.assertLess(self.clock.now, 0.3)

    def test_default_marker_uses_safe_event_name_and_avoids_overwriting(self):
        path = marker_path("事件/确认:奖励")
        self.assertEqual(path.name, "事件_确认_奖励.png")
        save_marker(self.frame, [20, 70, 30, 60], path)
        self.assertEqual(marker_path("事件/确认:奖励").name, "事件_确认_奖励 (2).png")
        self.assertEqual(marker_path("...").name, "图片标志.png")
        self.assertEqual(marker_path("CON").name, "_CON.png")

    def test_external_and_same_named_markers_resolve_exact_files_and_refresh_after_replace(self):
        with patch.object(image_tool, "_image_directory", str(self.root / "imgs")), \
                patch.object(image_tool, "_image_cache", {}):
            first, path = save_marker(self.frame, [20, 70, 30, 60], self.root / "outside/确认.png")
            second, _ = save_marker(self.frame, [80, 100, 70, 90], self.root / "imgs/nested/确认.png")
            third, _ = save_marker(self.frame, [120, 140, 40, 60], self.root / "imgs/确认.png")
            self.assertTrue(Path(first["photo"]).is_absolute())
            self.assertEqual(second["photo"], "nested/确认.png")
            np.testing.assert_array_equal(image_tool.find_image_by_name(first["photo"]), self.frame[30:60, 20:70])
            np.testing.assert_array_equal(image_tool.find_image_by_name(second["photo"]), self.frame[70:90, 80:100])
            self.assertEqual(third["photo"], "./确认.png")
            np.testing.assert_array_equal(image_tool.find_image_by_name(third["photo"]), self.frame[40:60, 120:140])
            kernel = StateKernel()
            kernel.screen = self.frame
            kernel.xx, kernel.yy = 192, 108
            kernel.scx = kernel.scy = 1.0
            kernel.threshold, kernel.config, kernel.last_info = 0.97, None, ""
            self.assertTrue(kernel.check(first["photo"], **first["pos"], threshold=first["threshold"]))
            save_marker(self.frame, [80, 100, 70, 90], path)
            np.testing.assert_array_equal(image_tool.find_image_by_name(first["photo"]), self.frame[70:90, 80:100])
            path.unlink()
            self.assertIsNone(image_tool.find_image_by_name(first["photo"]))
            image_tool._image_cache.update({"key": {"f.png": self.frame}})
            np.testing.assert_array_equal(image_tool.find_image_by_name("key/f"), self.frame)

    def test_failed_image_replace_preserves_original_and_cleans_temporary_file(self):
        path = self.root / "original.png"
        path.write_bytes(b"original")
        with patch("tool.script_tools.os.replace", side_effect=OSError("写入失败")):
            with self.assertRaises(OSError):
                save_marker(self.frame, [20, 70, 30, 60], path)
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_direct_debug_ignores_all_trigger_rules_and_keeps_action_order(self):
        engine = Mock(_stop=False)
        events = [dict(new_event(), name="首项", trigger={"photo": "missing", "condition": "impossible", "once": True},
                       actions=[{"set_state": "next"}, {"sleep": 0}]),
                  dict(new_event(), name="次项", actions=["custom_method"])]
        before = copy.deepcopy(events)
        self.assertIn("3 个动作", debug_events(engine, events, True))
        self.assertEqual([call.args[0] for call in engine.do_action.call_args_list],
                         [{"set_state": "next"}, {"sleep": 0}, "custom_method"])
        engine.ts.forward.assert_not_called()
        engine.get_screen.assert_not_called()
        engine.match_actions.assert_not_called()
        self.assertEqual(events, before)

    def test_trigger_debug_reuses_kernel_rules_and_executes_first_match_only(self):
        kernel = StateKernel()
        kernel._stop = False
        kernel.get_screen = Mock(return_value=self.frame)
        kernel.ts = Mock()
        kernel.ts.find_with_box.return_value = [{"raw_text": "确认", "box": [0, 1, 0, 1]}]
        kernel.prepare_script = Mock()
        kernel.do_action = Mock(return_value=1)
        events = [dict(new_event(), name="条件错误", trigger={"state_only": True, "condition": "wrong"}),
                  dict(new_event(), name="确认", trigger={"text": "确认", "box": [0, 1, 0, 1]}),
                  dict(new_event(), name="后续", actions=[{"sleep": 2}])]
        self.assertIn("已命中“确认”", debug_events(kernel, events, False))
        kernel.do_action.assert_called_once_with({"sleep": 1})
        kernel.ts.find_with_box.return_value = []
        self.assertIn("未命中", debug_events(kernel, events[:2], False))
        self.assertEqual(kernel.do_action.call_count, 1)

    def test_stop_during_direct_debug_prevents_next_action(self):
        engine = Mock(_stop=False)
        engine.do_action.side_effect = lambda _: setattr(engine, "_stop", True)
        result = debug_events(engine, [dict(new_event(), actions=[{"sleep": 0}, {"press": "esc"}])], True)
        self.assertIn("已停止", result)
        engine.do_action.assert_called_once()

    def test_debug_waits_for_game_focus_before_preparing_or_dispatching_input(self):
        for direct in (False, True):
            with self.subTest(direct=direct):
                self.clock.now = 0
                self.foreground.side_effect = lambda: self.window if self.clock.now >= 0.5 else None
                prepared_at = []
                engine = Mock(_stop=False)
                engine.prepare_script.side_effect = lambda: prepared_at.append(self.clock.now)
                engine.match_actions.return_value = ("开始挑战", 1)
                debug_events(engine, [dict(new_event(), actions=[{"position": [1510, 529]}])], direct)
                self.assertGreaterEqual(prepared_at[0], 0.8)

    def test_debug_without_game_focus_never_starts_input_or_dispatches_actions(self):
        self.foreground.return_value = None
        for direct in (False, True):
            with self.subTest(direct=direct):
                engine = Mock(_stop=False)
                with self.assertRaisesRegex(RuntimeError, "焦点"):
                    debug_events(engine, [new_event()], direct)
                engine.prepare_script.assert_not_called()
                engine.do_action.assert_not_called()
                engine.match_actions.assert_not_called()
                engine.get_screen.assert_not_called()

    def test_stop_during_debug_focus_wait_prevents_input(self):
        self.foreground.return_value = None
        engine = Mock(_stop=False)
        with patch("tool.script_tools.get_global_stop_flag", side_effect=lambda: self.clock.now >= 0.15):
            with self.assertRaises(InterruptedError):
                debug_events(engine, [new_event()], True)
        engine.prepare_script.assert_not_called()
        engine.do_action.assert_not_called()


class ScriptToolsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.enterContext(patch.dict(PATHS, {"root": str(self.root), "image": str(self.root / "imgs")}))
        self.frame = np.random.default_rng(5).integers(0, 256, (540, 960, 3), dtype=np.uint8)
        self.texts = [{"raw_text": "确认1", "box": [100, 220, 100, 145]}]
        self.sample = {"screen": self.frame, "texts": self.texts}

    def picker(self, recognize, event_name=""):
        dialog = TriggerSample(self.sample, recognize, event_name=event_name)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_click_ocr_box_selects_text_and_detection_range(self):
        dialog = self.picker(True)
        point = dialog.view.mapFromScene(QPointF(150, 120))
        QTest.mouseClick(dialog.view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(dialog.text_list.currentRow(), 0)
        self.assertEqual(dialog.match_text.text(), "确认")
        dialog.match_text.setText("确认！123")
        dialog.use_btn.click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.trigger, {"text": "确认", "box": [100, 220, 100, 145]})

    def test_reverse_drag_maps_scaled_scene_coordinates_and_saves_crop(self):
        dialog = self.picker(False)
        view = dialog.view
        start, end = view.mapFromScene(QPointF(300, 240)), view.mapFromScene(QPointF(100, 120))
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
        left, right, top, bottom = dialog.box
        for actual, expected in zip(dialog.box, [100, 300, 120, 240]):
            self.assertLessEqual(abs(actual - expected), 2)
        dialog.use_btn.click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        saved = self.root / "imgs" / dialog.trigger["photo"]
        np.testing.assert_array_equal(cv.imdecode(np.frombuffer(saved.read_bytes(), np.uint8), cv.IMREAD_COLOR),
                                      self.frame[top:bottom, left:right])

    def test_picker_opens_at_screen_size_and_image_can_be_renamed_and_relocated(self):
        for recognize in (True, False):
            with self.subTest(recognize=recognize):
                dialog = self.picker(recognize, "领取奖励")
                area = dialog.screen().availableGeometry()
                self.assertGreaterEqual(dialog.width(), area.width() * 0.94)
                self.assertGreaterEqual(dialog.height(), area.height() * 0.91)
                self.assertEqual(dialog.image_row.isVisible(), not recognize)
                self.assertEqual(dialog.file_name.text(), "领取奖励.png")
                if recognize:
                    dialog.reject()
                    continue
                destination = self.root / "自选目录"
                with patch("tool.gui.trigger_sample.QFileDialog.getExistingDirectory", return_value=str(destination)):
                    dialog.browse_btn.click()
                self.assertEqual(dialog.save_folder.text(), str(destination))
                dialog.file_name.setText("另一个标志")
                dialog.select_region([10, 40, 20, 50])
                dialog.use_btn.click()
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertEqual(Path(dialog.trigger["photo"]), destination / "另一个标志.png")
                self.assertTrue((destination / "另一个标志.png").is_file())

    def test_image_overwrite_requires_confirmation_and_failed_save_keeps_picker_open(self):
        dialog = self.picker(False, "事件")
        path = self.root / "imgs/script_markers/事件.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing")
        dialog.select_region([10, 40, 20, 50])
        with patch("tool.gui.trigger_sample.QMessageBox.question", return_value=QMessageBox.No):
            dialog.use_btn.click()
        self.assertEqual(path.read_bytes(), b"existing")
        self.assertTrue(dialog.isVisible())
        dialog.file_name.setText("../无效.png")
        dialog.use_btn.click()
        self.assertTrue(dialog.isVisible())
        self.assertIn("文件名", dialog.selection_label.text())
        dialog.file_name.setText(path.name)
        with patch("tool.gui.trigger_sample.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.use_btn.click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        np.testing.assert_array_equal(cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR), self.frame[20:50, 10:40])

    def test_empty_ocr_and_tiny_crop_cannot_be_accepted(self):
        self.sample["texts"] = []
        dialog = self.picker(True)
        self.assertFalse(dialog.use_btn.isEnabled())
        self.assertIn("未识别", dialog.selection_label.text())
        image = self.picker(False)
        point = image.view.mapFromScene(QPointF(100, 100))
        QTest.mouseClick(image.view.viewport(), Qt.LeftButton, pos=point)
        self.assertIsNone(image.box)
        self.assertFalse(image.use_btn.isEnabled())

    def editor(self):
        registry = Mock()
        registry.runnable.return_value = [SimpleNamespace(id="TestKernel", name="测试内核", folder=self.root / "core/test")]
        path = self.root / "actions/job.json"
        save_script(path, [new_event()])
        editor = ScriptEditor(registry, str(path))
        self.addCleanup(editor.deleteLater)
        return editor

    def test_debug_uses_unsaved_snapshot_and_source_mode(self):
        editor = self.editor()
        requested = Mock()
        editor.debug_requested.connect(requested)
        editor.event_name.setText("未保存的事件")
        editor.debug_direct_btn.click()
        session, kernel, events, direct = requested.call_args.args
        self.assertEqual(kernel, "TestKernel")
        self.assertEqual(events[0]["name"], "未保存的事件")
        self.assertTrue(direct)
        editor.receive_result(session, {"message": "完成"})
        editor.tabs.setCurrentIndex(1)
        editor.source_edit.setPlainText('[{"name":"源码事件","trigger":{"state_only":true},"actions":[]}]')
        editor.debug_trigger_btn.click()
        self.assertEqual(requested.call_args.args[2][0]["name"], "源码事件")
        self.assertFalse(requested.call_args.args[3])

    def test_sample_replaces_only_detector_fields_and_preserves_trigger_options(self):
        editor = self.editor()
        editor.trigger_fields.set_value({"state_only": True, "condition": "battle", "once": True, "extension": 7})
        editor.request_sample(True)
        picker = Mock(trigger={"text": "确认", "box": [100, 220, 100, 145]})
        picker.exec_.return_value = QDialog.Accepted
        with patch("tool.gui.script_editor.TriggerSample", return_value=picker) as dialog:
            editor.receive_result(editor.session, {"sample": self.sample})
        self.assertEqual(dialog.call_args.kwargs["event_name"], editor.event_name.text())
        self.assertEqual(editor.trigger_fields.value(), {"condition": "battle", "once": True, "extension": 7,
                                                        "text": "确认", "box": [100, 220, 100, 145]})
        self.assertTrue(editor.isWindowModified())

    def test_cancelled_or_foreign_result_never_opens_picker(self):
        editor = self.editor()
        stopped = Mock()
        editor.stop_requested.connect(stopped)
        editor.request_sample(False)
        editor.stop_operation()
        stopped.assert_called_once_with(editor.session)
        with patch("tool.gui.script_editor.TriggerSample") as picker:
            editor.receive_result("foreign", {"sample": self.sample})
            self.assertIsNotNone(editor.operation)
            editor.receive_result(editor.session, {"sample": self.sample})
            picker.assert_not_called()
        self.assertIsNone(editor.operation)

    def test_closing_editor_cancels_own_operation_and_waits_for_completion(self):
        editor = self.editor()
        stopped = Mock()
        editor.stop_requested.connect(stopped)
        editor.show()
        self.app.processEvents()
        editor.request_sample(False)
        editor.reject()
        stopped.assert_called_once_with(editor.session)
        self.assertTrue(editor.isVisible())
        self.assertTrue(editor.close_pending)
        editor.receive_result(editor.session, {"message": "已停止"})
        self.assertFalse(editor.isVisible())
        self.assertFalse(editor.close_pending)


if __name__ == "__main__":
    unittest.main()
