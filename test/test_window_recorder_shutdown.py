"""用阻塞写入重现 4K 编码收尾竞态，不读取桌面或生成真实录像。"""

import ast
import datetime
import os
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load_recorder():
    source = Path(__file__).resolve().parents[1] / "tool/window_recorder.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = {
        "threading": threading, "datetime": datetime, "os": os,
        "time": types.SimpleNamespace(sleep=Mock()), "CUS_LOGGER": Mock(),
        "cv2": Mock(), "np": Mock(), "ImageGrab": Mock(), "ctypes": Mock(),
        "win32gui": Mock(), "is_usable_game_window": Mock(return_value=True),
        "get_window_kind": Mock(return_value="local"),
        "LOCAL_GAME_TITLE": "game", "CLOUD_WINDOW_KIND": "cloud",
        "ThreadWithException": threading.Thread,
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["WindowRecorder"], namespace


class WindowRecorderShutdownTests(unittest.TestCase):
    def setUp(self):
        self.cls, self.namespace = load_recorder()
        self.recorder = self.cls(handle=1)
        self.recorder.capture_left = self.recorder.capture_top = 0
        self.recorder.capture_right = 3840
        self.recorder.capture_bottom = 2160
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.recorder.output_path = self.directory.name + os.sep
        self.recorder.output_file = str(Path(self.directory.name) / "第1次轮回-test.mp4")
        Path(self.recorder.output_file).write_bytes(b"video")

    def test_timed_out_writer_stays_owned_until_exit_and_blocks_restart(self):
        entered, resume = threading.Event(), threading.Event()
        writer = Mock()

        def write(frame):
            entered.set()
            if not resume.wait(3):
                raise TimeoutError("未释放测试写入器")

        writer.write.side_effect = write
        recorder = self.recorder
        recorder.out = writer
        recorder.recording = True
        thread = threading.Thread(target=recorder._record_window, args=(writer,), daemon=True)
        recorder.recording_thread = thread
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            # 缩短等待，不改变仍在编码的真实线程状态。
            join = thread.join
            with patch.object(thread, "join", side_effect=lambda timeout: join(0.01)):
                with self.assertRaises(TimeoutError):
                    recorder.stop_recording(delete_video=True)
            self.assertTrue(thread.is_alive())
            self.assertIs(recorder.out, writer)
            writer.release.assert_not_called()
            self.assertTrue(Path(recorder.output_file).exists())
            with self.assertRaisesRegex(RuntimeError, "尚未结束"):
                recorder.start_recording(2)
            self.namespace["cv2"].VideoWriter.assert_not_called()
        finally:
            resume.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        writer.release.assert_called_once()
        self.assertIsNone(recorder.out)
        recorder.stop_recording(delete_video=True)
        self.assertFalse(Path(recorder.output_file).exists())
        self.assertIsNone(recorder.recording_thread)

    def test_completed_recording_renames_once_and_repeated_stop_is_safe(self):
        recorder = self.recorder
        recorder.recording_thread = Mock(is_alive=Mock(return_value=False))
        recorder.stop_recording(battle_count=7)
        self.assertIn("第1次轮回-7战-", recorder.output_file)
        self.assertEqual(b"video", Path(recorder.output_file).read_bytes())
        recorder.stop_recording(battle_count=8)
        self.assertIn("第1次轮回-7战-", recorder.output_file)

    def test_preview_quit_does_not_join_its_own_thread(self):
        recorder = self.recorder
        writer = Mock()
        recorder.out = writer
        recorder.recording = True
        recorder.is_show = True
        self.namespace["cv2"].waitKey.return_value = ord("q")
        recorder.stop_recording = Mock(side_effect=AssertionError("不能在录制线程中 join 自身"))
        recorder._record_window(writer)
        self.assertFalse(recorder.recording)
        recorder.stop_recording.assert_not_called()
        writer.write.assert_called_once()
        writer.release.assert_called_once()

    def test_failed_writer_release_is_retried_only_after_thread_exit(self):
        recorder = self.recorder
        writer = Mock()
        writer.release.side_effect = [OSError("encoder busy"), None]
        recorder.out = writer
        recorder.recording = False
        with self.assertRaisesRegex(OSError, "encoder busy"):
            recorder._record_window(writer)
        self.assertIs(recorder.out, writer)
        with self.assertRaisesRegex(RuntimeError, "尚未释放"):
            recorder.start_recording()
        recorder.stop_recording()
        self.assertIsNone(recorder.out)
        self.assertEqual(writer.release.call_count, 2)

    def test_thread_start_failure_releases_unowned_writer(self):
        self.namespace["win32gui"].GetWindowRect.return_value = (0, 0, 3840, 2160)
        writer = self.namespace["cv2"].VideoWriter.return_value
        thread = Mock()
        thread.start.side_effect = RuntimeError("cannot create thread")
        self.namespace["ThreadWithException"] = Mock(return_value=thread)
        with self.assertRaisesRegex(RuntimeError, "cannot create thread"):
            self.recorder.start_recording()
        writer.release.assert_called_once()
        self.assertFalse(self.recorder.recording)
        self.assertIsNone(self.recorder.out)
        self.assertIsNone(self.recorder.recording_thread)

    def test_unopened_writer_is_released_without_starting_thread(self):
        self.namespace["win32gui"].GetWindowRect.return_value = (0, 0, 3840, 2160)
        writer = self.namespace["cv2"].VideoWriter.return_value
        writer.isOpened.return_value = False
        self.namespace["ThreadWithException"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "无法初始化"):
            self.recorder.start_recording()
        writer.release.assert_called_once()
        self.namespace["ThreadWithException"].assert_not_called()
        self.assertIsNone(self.recorder.out)


if __name__ == "__main__":
    unittest.main()
