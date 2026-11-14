"""通用设置里的截图方式选择：界面控件、默认配置与配置读写保持一致。"""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tool.screenshot import CAPTURE_BACKENDS, resolve_capture_backend
from tool.settings import load_settings, update_settings

ROOT = Path(__file__).resolve().parents[1]


class CaptureSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = ET.parse(ROOT / "resource" / "ui" / "UI.ui").getroot()

    def widget(self, widget_class, name):
        return self.ui.find(f".//widget[@class='{widget_class}'][@name='{name}']")

    def test_settings_tab_offers_capture_backend_and_background_mode(self):
        self.assertIsNotNone(self.widget("QComboBox", "capture_backend_combo"))
        self.assertIsNotNone(self.widget("QCheckBox", "background_mode_checkbox"))

    def test_defaults_match_the_offered_values(self):
        defaults = json.loads(
            (ROOT / "resource" / "gui_settings_default.json").read_text(encoding="utf-8"))
        self.assertIs(defaults["background_mode"], False)
        self.assertIn(defaults["capture_backend"], ("auto",) + CAPTURE_BACKENDS)


class CaptureSettingsRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = load_settings()
        cls.original = {
            "background_mode": original.get("background_mode", False),
            "capture_backend": original.get("capture_backend", "auto"),
        }

    @classmethod
    def tearDownClass(cls):
        update_settings(cls.original)

    def test_saved_backend_is_used_on_the_next_task(self):
        update_settings({"background_mode": True, "capture_backend": "printwindow"})
        settings = load_settings()
        self.assertTrue(settings["background_mode"])
        self.assertEqual(resolve_capture_backend(settings, settings["background_mode"]), "printwindow")

    def test_unknown_backend_falls_back_to_mode_default(self):
        update_settings({"capture_backend": "bogus"})
        settings = load_settings()
        self.assertEqual(resolve_capture_backend(settings, True), "printwindow")
        self.assertEqual(resolve_capture_backend(settings, False), "screen")


if __name__ == "__main__":
    unittest.main()
