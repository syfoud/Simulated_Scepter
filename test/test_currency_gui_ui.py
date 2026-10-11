import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

UI_PATH = Path(__file__).resolve().parents[1] / "resource" / "ui" / "UI.ui"


class CurrencyGuiUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(UI_PATH).getroot()
        cls.currency = ET.parse(Path(__file__).resolve().parents[1] / "core/currency/ui/settings.ui").getroot()

    def test_currency_settings_are_independent_of_main_tabs(self):
        self.assertIsNone(self.root.find(".//widget[@name='CurrencyWarTab']"))
        self.assertIsNotNone(self.root.find(".//widget[@name='kernel_buttons']"))

    def test_currency_settings_uses_choice_and_save_controls(self):
        tab = self.currency

        self.assertIsNotNone(
            tab.find(".//widget[@class='QComboBox'][@name='Currency_exit_plane_combo']")
        )
        self.assertIsNotNone(tab.find(".//widget[@name='Currency_priority_settings_btn']"))


if __name__ == "__main__":
    unittest.main()
