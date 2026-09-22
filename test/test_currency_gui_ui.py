import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

UI_PATH = Path(__file__).resolve().parents[1] / "resource" / "ui" / "UI.ui"


class CurrencyGuiUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(UI_PATH).getroot()

    def test_currency_settings_has_dedicated_tab(self):
        tab = self.root.find(".//widget[@name='CurrencyWarTab']")

        self.assertIsNotNone(tab)
        self.assertEqual(tab.find("./attribute[@name='title']/string").text, "货币战争设置")

    def test_currency_settings_uses_choice_and_save_controls(self):
        tab = self.root.find(".//widget[@name='CurrencyWarTab']")

        self.assertIsNotNone(
            tab.find(".//widget[@class='QComboBox'][@name='Currency_exit_plane_combo']")
        )
        save_button = tab.find(
            ".//widget[@class='QPushButton'][@name='Currency_save_btn']"
        )
        self.assertIsNotNone(save_button)
        self.assertEqual(save_button.find("./property[@name='text']/string").text, "保存货币战争设置")


if __name__ == "__main__":
    unittest.main()
