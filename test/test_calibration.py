"""角度校准：读取已保存倍率、按需构造通用内核、校准流程的生命周期。"""

import unittest
from unittest.mock import Mock, patch

import tool.calibration as calibration


class GetMultiTest(unittest.TestCase):
    def settings(self, **values):
        return self.enterContext(patch.object(calibration, "load_settings", return_value=values))

    def test_default_value_is_one(self):
        self.settings(calibration_angle=1.0)
        self.assertEqual(calibration.get_multi(), 1.0)

    def test_saved_value_is_returned(self):
        self.settings(calibration_angle=0.73)
        self.assertAlmostEqual(calibration.get_multi(), 0.73)

    def test_out_of_range_values_fall_back_to_uncalibrated(self):
        for value in (0, -1, 5.5, 7):
            with self.subTest(value=value):
                self.settings(calibration_angle=value)
                self.assertEqual(calibration.get_multi(), 1.0)


class CreateKernelTest(unittest.TestCase):
    def test_kernel_is_a_common_script_kernel_with_direction_predictor(self):
        kernel = Mock()
        with patch("core.common.runtime.ScriptKernel", return_value=kernel) as factory:
            created = calibration.create_kernel()

        factory.assert_called_once_with()
        self.assertIs(created, kernel)
        self.assertTrue(hasattr(kernel, "pos_predictor"))


class MainLifecycleTest(unittest.TestCase):
    """main() 只在自建内核时负责释放；外部传入的内核由调用方管理。"""

    def setUp(self):
        self.manager = self.enterContext(patch.object(calibration, "key_mouse_manager", Mock()))
        self.calibrate = self.enterContext(
            patch.object(calibration, "_calibrate", return_value=True)
        )

    def test_caller_supplied_kernel_is_not_stopped(self):
        kernel = Mock()

        self.assertTrue(calibration.main(su=kernel))

        self.manager.start.assert_called_once_with()
        self.calibrate.assert_called_once()
        kernel.stop.assert_not_called()

    def test_own_kernel_is_created_and_released(self):
        kernel = Mock()
        with patch.object(calibration, "create_kernel", return_value=kernel):
            self.assertTrue(calibration.main())

        kernel.stop.assert_called_once_with()

    def test_kernel_creation_failure_releases_input_thread(self):
        with patch.object(calibration, "create_kernel", side_effect=TimeoutError("无窗口")):
            with self.assertRaises(TimeoutError):
                calibration.main()

        self.manager.stop.assert_called_once_with()


class CalibrateResultTest(unittest.TestCase):
    def test_measured_multiplier_is_written_to_gui_settings(self):
        kernel = Mock()
        manager = self.enterContext(patch.object(calibration, "key_mouse_manager", Mock()))
        manager.multi = 1.0

        # 每次转身都恰好转 60°：误差比为 1，最终倍率保持 1.0
        with patch.object(calibration, "update_settings") as update, \
                patch.object(calibration, "time", Mock(sleep=Mock())), \
                patch.object(calibration, "get_angle", side_effect=[100.0, 160.0, 220.0, 280.0]):
            self.assertTrue(calibration._calibrate([3], kernel))

        self.assertEqual(update.call_count, 1)
        saved = update.call_args.args[0]["calibration_angle"]
        self.assertAlmostEqual(saved, 1.0, places=6)

    def test_unknown_initial_angle_reports_failure_without_writing(self):
        kernel = Mock()
        self.enterContext(patch.object(calibration, "key_mouse_manager", Mock()))

        with patch.object(calibration, "update_settings") as update, \
                patch.object(calibration, "get_angle", return_value=None):
            self.assertFalse(calibration._calibrate([1], kernel))

        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
