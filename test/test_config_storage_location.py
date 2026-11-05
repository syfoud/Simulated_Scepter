"""用户级配置项的存储位置：协议标记归属 user 目录，校准角度归属全局 gui_settings。"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QApplication

import tool.settings as tool_settings
from core.simulated.config import config as simulated_config
from route import PATHS


class AgreementMarkerTests(unittest.TestCase):
    """协议接受标记写在 user 目录，升级替换程序包时随用户数据保留。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # QApplication 必须先创建，主窗口模块在导入时初始化 Qt 相关对象。
        import new_gui

        cls.module = new_gui

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        # 取 resolve 后的长路径，避免 TEMP 为 8.3 短文件名时与生产代码返回的路径不相等。
        self.user = Path(self.folder.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(self.module.PATHS, {"user": str(self.user)}))
        self.agreement_file = os.path.join(str(self.user), "agreement_accepted.txt")

    def test_missing_marker_opens_dialog_with_user_path(self):
        window = Mock()
        self.module.MainWindow.check_first_launch(window)
        window.show_agreement_dialog.assert_called_once_with(self.agreement_file)

    def test_existing_marker_skips_dialog(self):
        Path(self.agreement_file).write_text("Agreement accepted at: 2026-01-01 00:00:00\n", encoding="utf-8")
        window = Mock()
        self.module.MainWindow.check_first_launch(window)
        window.show_agreement_dialog.assert_not_called()

    def test_legacy_cache_marker_is_ignored(self):
        # 本次改动不做旧配置兼容：旧版本写在 cache 下的标记不再生效，老用户重新接受一次协议。
        root = Path(self.folder.name).resolve() / "root"
        (root / "cache").mkdir(parents=True)
        (root / "cache" / "agreement_accepted.txt").write_text("legacy", encoding="utf-8")
        with patch.dict(self.module.PATHS, {"root": str(root)}):
            window = Mock()
            self.module.MainWindow.check_first_launch(window)
        window.show_agreement_dialog.assert_called_once_with(self.agreement_file)


class CalibrationAngleTests(unittest.TestCase):
    """校准角度保存在全局 gui_settings，模拟宇宙内核按本机校准值转向。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.user = Path(self.folder.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(tool_settings.PATHS, {"user": str(self.user)}))

    def write_angle(self, angle):
        Path(self.user).mkdir(exist_ok=True)
        (self.user / "gui_settings.json").write_text(
            json.dumps({"calibration_angle": angle}), encoding="utf-8"
        )

    def test_default_settings_define_calibration_angle(self):
        default = json.loads(
            (Path(PATHS["root"]) / "resource" / "gui_settings_default.json").read_text(encoding="utf-8")
        )
        self.assertEqual(default["calibration_angle"], 1.0)

    def test_multi_reads_calibrated_value_from_gui_settings(self):
        self.write_angle(0.73)
        self.assertAlmostEqual(simulated_config.multi, 0.73)

    def test_out_of_range_value_is_treated_as_uncalibrated(self):
        for angle in (0, -1, 5.5, 7):
            with self.subTest(angle=angle):
                self.write_angle(angle)
                self.assertEqual(simulated_config.multi, 1.0)


if __name__ == "__main__":
    unittest.main()
