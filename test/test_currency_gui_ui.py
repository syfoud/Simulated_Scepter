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
        self.assertIsNotNone(tab.find(".//widget[@name='Currency_deployment_settings_btn']"))

    def test_affix_collection_controls_exist(self):
        tab = self.currency

        for widget in (
            "Currency_gamemode_combo",
            "Currency_difficulty_mode_combo",
            "Currency_affix_targets_edit",
            "Currency_affix_targets_btn",
            "Currency_max_runs_spin",
            "Currency_gather_mode_checkbox",
        ):
            self.assertIsNotNone(tab.find(f".//widget[@name='{widget}']"), widget)


    def test_strategy_collection_controls_exist(self):
        tab = self.currency

        for widget in (
            "Currency_strategy_targets_edit",
            "Currency_strategy_targets_btn",
            "Currency_strategy_avoid_edit",
            "Currency_strategy_avoid_btn",
            "Currency_auto_exit_plane_checkbox",
        ):
            self.assertIsNotNone(tab.find(f".//widget[@name='{widget}']"), widget)

    def test_auto_exit_plane_disables_manual_plane_choices(self):
        """勾了"按目标策略自动决定退出位面"，两个手选位面就不该还能改。"""
        tab = self.currency
        auto = tab.find(".//widget[@name='Currency_auto_exit_plane_checkbox']")
        exit_combo = tab.find(".//widget[@name='Currency_exit_plane_combo']")
        prior_combo = tab.find(".//widget[@name='Currency_prior_exit_plane_combo']")
        self.assertIsNotNone(auto)

        auto.setChecked(True)
        self.assertFalse(exit_combo.isEnabled())
        self.assertFalse(prior_combo.isEnabled())

        auto.setChecked(False)
        self.assertTrue(exit_combo.isEnabled())
        self.assertTrue(prior_combo.isEnabled())


if __name__ == "__main__":
    unittest.main()
