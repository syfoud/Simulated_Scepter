"""货币战争策略配置界面。"""

from core.currency.priority_ui import CurrencyPriorityDialog
from core.currency.settings import (
    EXIT_PLANES,
    load_currency_settings,
    save_currency_settings,
)
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import config_path, resource_path


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("货币战争配置", parent)
        self.path = config_path(__file__)
        settings = load_currency_settings(path=self.path)
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        for plane in EXIT_PLANES:
            ui.Currency_exit_plane_combo.addItem(f"第 {plane} 位面", plane)
        ui.Currency_exit_plane_combo.setCurrentIndex(
            ui.Currency_exit_plane_combo.findData(settings["exit_after_plane"]))
        ui.Currency_exit_if_no_prior_checkbox.setChecked(settings["exit_if_no_prior"])
        ui.Currency_prior_exit_plane_combo.addItem("不调整", None)
        for plane in EXIT_PLANES:
            ui.Currency_prior_exit_plane_combo.addItem(f"第 {plane} 位面", plane)
        ui.Currency_prior_exit_plane_combo.setCurrentIndex(
            ui.Currency_prior_exit_plane_combo.findData(settings["prior_exit_plane"]))
        ui.Currency_priority_settings_btn.clicked.connect(self.open_priority)

    def open_priority(self):
        CurrencyPriorityDialog(self).exec_()

    def persist(self):
        ui = self.section
        save_currency_settings({
            "exit_after_plane": ui.Currency_exit_plane_combo.currentData(),
            "exit_if_no_prior": ui.Currency_exit_if_no_prior_checkbox.isChecked(),
            "prior_exit_plane": ui.Currency_prior_exit_plane_combo.currentData(),
        }, path=self.path)
