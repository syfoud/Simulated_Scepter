"""用真实线程重现停止与轮回切段交错，不访问桌面或接管键鼠。"""

import os
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock

from test.test_simul_thread_lifecycle import load_methods
from test.test_window_recorder_shutdown import load_recorder


class RecordingLifecycleTests(unittest.TestCase):
    def make_task(self, mode="simul"):
        self.manager = Mock()
        namespace = {
            "threading": threading, "time": types.SimpleNamespace(sleep=Mock()),
            "key_mouse_manager": self.manager, "CUS_LOGGER": Mock(),
            "NormalEndError": type("NormalEndError", (Exception,), {}),
            "flush_evidence": Mock(), "finish_recovery": Mock(),
        }
        task = load_methods("simul.py", "SimulatedUniverse", {
            "start", "stop", "stop_background_threads", "restart_recording",
            "start_recording", "rotate_recording",
        }, namespace)
        if mode != "simul":
            names = {"any_fate": "AnyFateUniverse", "iron_blood": "IronBloodUniverse",
                     "finger_snap": "FingerSnap"}
            variant = load_methods(mode + ".py", names[mode], {"restart_recording"}, namespace)
            task.restart_recording = types.MethodType(variant.restart_recording.__func__, task)
        task._worker_lock = threading.Lock()
        task._stop = True
        task._show_map = False
        task.move_thread = task.update_thread = task.map_thread = None
        task.record = task.cut_video = True
        task.gwypzmgzcndqlp = task.bveerelbcpgyqan = task.YKItDYvq3FpnOYx = True
        task.recorder = types.SimpleNamespace(recording=False)
        task.recorder.start_recording = Mock(side_effect=lambda *a: setattr(task.recorder, "recording", True))
        task.recorder.stop_recording = Mock(side_effect=lambda *a, **kw: setattr(task.recorder, "recording", False))
        task.sct = Mock()
        task.pos_predictor = Mock()
        task.save_screen = Mock()
        task.update_state = Mock()
        task.count = 639
        task.elapsed_time = 360
        task.kill_count = 8
        task.del_record_time = 31
        task.debug = task.ruanmei2 = False
        task.countdown = 10
        task.countdown_agent = Mock()
        return task, namespace

    def test_stop_during_cut_never_restarts_recording_in_any_mode(self):
        for mode in ("simul", "any_fate", "iron_blood", "finger_snap"):
            with self.subTest(mode=mode):
                task, namespace = self.make_task(mode)
                paused, resume = threading.Event(), threading.Event()
                errors = []

                def pause(seconds):
                    paused.set()
                    if not resume.wait(3):
                        raise TimeoutError("切段测试未释放等待")

                def run():
                    try:
                        task.start()
                    except Exception as error:
                        errors.append(error)

                namespace["time"].sleep.side_effect = pause
                task.route = task.restart_recording
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                try:
                    self.assertTrue(paused.wait(3))
                    task.stop()
                    self.manager.stop.assert_called()
                finally:
                    resume.set()
                    worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(task.recorder.start_recording.call_count, 1)
                self.assertFalse(task.recorder.recording)
                task.update_state.assert_not_called()
                task.sct.close.assert_called_once()

    def test_normal_completion_finalizes_recording(self):
        task, _ = self.make_task()
        task.route = Mock()
        task.start()
        self.assertFalse(task.recorder.recording)
        task.sct.close.assert_called_once()

    def test_zero_battle_video_deleted_only_for_requested_stop(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                task, _ = self.make_task()
                task.kill_count = 0
                task.route = task.stop if stopped else Mock()
                task.start()
                task.recorder.stop_recording.assert_called_once_with(delete_video=stopped)

    def test_route_failure_still_finalizes_recording_and_screen(self):
        task, _ = self.make_task()
        task.route = Mock(side_effect=ValueError("navigation failed"))
        with self.assertRaisesRegex(ValueError, "navigation failed"):
            task.start()
        self.assertFalse(task.recorder.recording)
        task.sct.close.assert_called_once()

    def test_recorder_close_failure_still_releases_input_and_screen(self):
        task, _ = self.make_task()
        task.route = Mock()
        task.recorder.stop_recording.side_effect = RuntimeError("recording close failed")
        with self.assertRaisesRegex(RuntimeError, "recording close failed"):
            task.start()
        self.manager.stop.assert_called()
        task.sct.close.assert_called_once()

    def test_normal_cut_keeps_each_modes_retention_rule(self):
        for mode in ("simul", "any_fate", "iron_blood", "finger_snap"):
            with self.subTest(mode=mode):
                task, _ = self.make_task(mode)
                task._stop = False
                task.restart_recording()
                self.assertTrue(task.recorder.recording)
                task.recorder.start_recording.assert_called_once_with(640)
                task.update_state.assert_called_once_with("re_start")
                first = task.recorder.stop_recording.call_args
                if mode == "iron_blood":
                    self.assertTrue(first.args[0])
                    self.assertEqual(first.kwargs["battle_count"], 8)
                elif mode == "finger_snap":
                    self.assertTrue(first.args[0])

    @unittest.skipUnless(sys.platform == "win32", "在项目 Windows OpenCV 环境核对真实 MP4 收尾")
    def test_completed_task_leaves_readable_mp4(self):
        import cv2
        import numpy as np

        task, _ = self.make_task()
        recorder_class, namespace = load_recorder()
        namespace["cv2"], namespace["np"] = cv2, np
        recorder = recorder_class()
        recorder.capture_left = recorder.capture_top = 0
        recorder.capture_right, recorder.capture_bottom = 64, 48
        captured = 0

        def capture(bbox):
            nonlocal captured
            captured += 1
            if captured == 5:
                recorder.recording = False
            return np.full((48, 64, 3), 127, dtype=np.uint8)

        namespace["ImageGrab"].grab.side_effect = capture
        with tempfile.TemporaryDirectory() as folder:
            recorder.output_file = os.path.join(folder, "recording.mp4")

            def start(count):
                recorder.out = cv2.VideoWriter(recorder.output_file, cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 48))
                self.assertTrue(recorder.out.isOpened())
                recorder.recording = True
                recorder.recording_thread = threading.Thread(
                    target=recorder._record_window, args=(recorder.out,), daemon=True,
                )
                recorder.recording_thread.start()

            def finish_route():
                recorder.recording_thread.join(3)
                self.assertFalse(recorder.recording_thread.is_alive())

            recorder.start_recording = start
            task.recorder = recorder
            task.route = finish_route
            try:
                task.start()
                self.assertFalse(recorder.recording)
                self.assertIsNone(recorder.out)
                reader = cv2.VideoCapture(recorder.output_file)
                try:
                    self.assertTrue(reader.isOpened())
                    self.assertEqual(reader.get(cv2.CAP_PROP_FRAME_COUNT), 5)
                    self.assertTrue(reader.read()[0])
                finally:
                    reader.release()
            finally:
                recorder.stop_recording()


if __name__ == "__main__":
    unittest.main()
