"""入口的正常、失败和关闭路径；桌面与输入由 mock 隔离。"""

import types
import unittest
from unittest.mock import Mock

from test.test_simul_thread_lifecycle import load_methods


class EntryPointTests(unittest.TestCase):
    def test_currency_closes_capture_after_releasing_input(self):
        for phase in ("success", "start", "route"):
            with self.subTest(phase=phase):
                events = []
                manager = Mock()
                manager.stop.side_effect = lambda: events.append("input")
                task = load_methods("currency.py", "SimulatedCurrency", {"start"}, {
                    "key_mouse_manager": manager, "CUS_LOGGER": Mock(),
                    "NormalEndError": type("NormalEndError", (Exception,), {}),
                })
                task._stop = False
                task.route = Mock()
                if phase != "success":
                    action = manager.start if phase == "start" else task.route
                    action.side_effect = ValueError("capture failed")
                task.stop = Mock()
                task.sct = Mock()
                task.sct.close.side_effect = lambda: events.append("capture")
                if phase != "success":
                    with self.assertRaisesRegex(ValueError, "capture failed"):
                        task.start()
                else:
                    task.start()
                self.assertEqual(events, ["input", "capture"])

    def test_diver_normal_exit_releases_workers_recording_and_capture(self):
        events = []
        manager = Mock()
        manager.stop.side_effect = lambda: events.append("input")
        keys = Mock()
        keys.join.side_effect = lambda: events.append("keys")
        keyops = Mock()
        keyops.release_pressed_keys.return_value = {}
        task = load_methods("diver.py", "DivergentUniverse", {"start", "_stop_input_workers"}, {
            "key_mouse_manager": manager, "CUS_LOGGER": Mock(),
            "KeyController": Mock(return_value=keys), "keyops": keyops,
        })
        task.record = True
        task.count = 1
        task.route = Mock()
        task.stop_movement_threads = Mock(side_effect=lambda: events.append("movement"))
        task.recorder = Mock()
        task.recorder.stop_recording.side_effect = lambda: events.append("recording")
        task.sct = Mock()
        task.sct.close.side_effect = lambda: events.append("capture")
        task.start()
        self.assertEqual(events, ["movement", "keys", "input", "recording", "capture"])
        keyops.release_pressed_keys.assert_called_once()

    def test_gui_capture_tools_close_resources_even_when_recognition_fails(self):
        for method in ("test", "test_2"):
            for failure in (None, ValueError("recognition failed")):
                with self.subTest(method=method, failure=failure):
                    task = Mock()
                    task.save_screen.side_effect = failure
                    task.click_target.side_effect = failure
                    window = load_methods("new_gui.py", "MainWindow", {method}, {
                        "SimulatedUniverse": Mock(return_value=task),
                        "config_simul": types.SimpleNamespace(
                            debug_mode=0, speed_mode=0, use_consumable=0,
                            slow_mode=0, max_run=1, bonus=False,
                        ),
                        "find_image_by_name": Mock(), "QMessageBox": Mock(),
                    })
                    window.start_task = lambda callback: callback()
                    window.PrintEdit = Mock()
                    window.PrintPhoto = Mock()
                    window.PrintPhoto.isChecked.return_value = True
                    if failure:
                        with self.assertRaisesRegex(ValueError, "recognition failed"):
                            getattr(window, method)()
                    else:
                        getattr(window, method)()
                    task.stop_background_threads.assert_called_once()
                    task.sct.close.assert_called_once()

    def test_gui_capture_closes_even_if_worker_cleanup_raises(self):
        for method in ("test", "test_2"):
            with self.subTest(method=method):
                task = Mock()
                task.stop_background_threads.side_effect = ValueError("cleanup failed")
                window = load_methods("new_gui.py", "MainWindow", {method}, {
                    "SimulatedUniverse": Mock(return_value=task),
                    "config_simul": types.SimpleNamespace(
                        debug_mode=0, speed_mode=0, use_consumable=0,
                        slow_mode=0, max_run=1, bonus=False,
                    ),
                    "find_image_by_name": Mock(), "QMessageBox": Mock(),
                })
                window.start_task = lambda callback: callback()
                window.PrintEdit = Mock()
                window.PrintPhoto = Mock()
                with self.assertRaisesRegex(ValueError, "cleanup failed"):
                    getattr(window, method)()
                task.sct.close.assert_called_once()

    def test_window_close_waits_for_task_cleanup(self):
        window = load_methods("new_gui.py", "MainWindow", {"closeEvent", "_check_task_thread"}, {
            "set_global_stop_flag": Mock(),
        })
        window.close_pending = False
        window.is_task_running = Mock(return_value=True)
        window.stop_task = Mock()
        event = Mock()
        window.closeEvent(event)
        event.ignore.assert_called_once()
        window.stop_task.assert_called_once()
        self.assertTrue(window.close_pending)
        window.task_thread = Mock()
        window.task_thread.is_alive.return_value = False
        window._task_monitor_timer = Mock()
        window.Label_RunningState = Mock()
        window.close = Mock()
        window._check_task_thread()
        window.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
