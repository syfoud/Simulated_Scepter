"""使用真实 Qt 对话框和临时配置验证设备信息、保存、取消及失效设备。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from route import PATHS
from tool.gui import ocr_settings
from tool.onnxocr import device


class OcrSettingsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "gui_settings.json"
        self.file.write_text(json.dumps({"other": {"keep": True}}), encoding="utf-8")
        self.enterContext(patch.dict(PATHS, {"user": folder.name}))
        self.first = device.Adapter(0, "同型号显卡", "first-luid", "pci:first")
        self.second = device.Adapter(2, "同型号显卡", "second-luid", "pci:second")
        self.enterContext(patch.object(ocr_settings, "list_adapters", return_value=[self.first, self.second]))
        self.enterContext(patch.object(device, "list_adapters", return_value=[self.first, self.second]))
        self.enterContext(patch.object(device, "default_luid", return_value=self.second.luid))
        self.enterContext(patch.object(device, "get_available_providers", return_value=["DmlExecutionProvider", "CPUExecutionProvider"]))

    def dialog(self):
        dialog = ocr_settings.OcrSettingsDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_auto_displays_actual_mapping_and_cancel_does_not_write(self):
        dialog = self.dialog()
        before = self.file.read_bytes()
        self.assertEqual(dialog.device_combo.currentData(), "auto")
        self.assertIn("second-luid", dialog.device_detail.text())
        self.assertIn("DXGI 2", dialog.device_detail.text())
        dialog.buttons.button(QDialogButtonBox.Cancel).click()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(self.file.read_bytes(), before)

    def test_select_same_name_device_save_and_reopen(self):
        dialog = self.dialog()
        dialog.device_combo.setCurrentIndex(dialog.device_combo.findData(self.first.key))
        self.assertIn("first-luid", dialog.device_detail.text())
        dialog.buttons.button(QDialogButtonBox.Save).click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        saved = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(saved["ocr_device"], self.first.key)
        self.assertEqual(saved["other"], {"keep": True})
        self.assertEqual(self.dialog().device_combo.currentData(), self.first.key)

    def test_cpu_can_be_saved_even_when_enumeration_fails(self):
        with patch.object(ocr_settings, "list_adapters", side_effect=OSError("DXGI failed")):
            dialog = self.dialog()
        dialog.device_combo.setCurrentIndex(dialog.device_combo.findData("cpu"))
        self.assertEqual(dialog.device_detail.text(), "重启后使用：CPU")
        dialog.buttons.button(QDialogButtonBox.Save).click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(json.loads(self.file.read_text())["ocr_device"], "cpu")

    def test_unavailable_selection_is_preserved_and_save_refused(self):
        self.file.write_text('{"ocr_device":"removed"}', encoding="utf-8")
        dialog = self.dialog()
        before = self.file.read_bytes()
        self.assertEqual(dialog.device_combo.currentData(), "removed")
        self.assertIn("重新选择", dialog.device_detail.text())
        with patch.object(QMessageBox, "warning") as warning:
            dialog.buttons.button(QDialogButtonBox.Save).click()
        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.file.read_bytes(), before)

    def test_write_failure_keeps_dialog_open(self):
        dialog = self.dialog()
        before = self.file.read_bytes()
        with patch.object(ocr_settings, "update_settings", side_effect=OSError("write failed")), patch.object(QMessageBox, "critical") as critical:
            dialog.buttons.button(QDialogButtonBox.Save).click()
        critical.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.file.read_bytes(), before)

    def test_missing_directml_is_shown_and_cpu_remains_available(self):
        with patch.object(device, "get_available_providers", return_value=["CPUExecutionProvider"]):
            dialog = self.dialog()
            dialog.device_combo.setCurrentIndex(dialog.device_combo.findData(self.first.key))
            self.assertIn("不支持 DirectML", dialog.device_detail.text())
            with patch.object(QMessageBox, "warning") as warning:
                dialog.buttons.button(QDialogButtonBox.Save).click()
            warning.assert_called_once()
            dialog.device_combo.setCurrentIndex(dialog.device_combo.findData("cpu"))
            dialog.buttons.button(QDialogButtonBox.Save).click()
        self.assertEqual(dialog.result(), QDialog.Accepted)


if __name__ == "__main__":
    unittest.main()
