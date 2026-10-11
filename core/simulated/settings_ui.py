"""模拟宇宙配置界面，独立于运行内核与主窗口。"""

from core.simulated.config import config
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.settings import save_config_values
from tool.storage import resource_path


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("模拟宇宙配置", parent)
        config.read()
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        for key, field in (("bonus", "bonus"),
                           ("speed_mode", "speed"), ("slow_mode", "slow")):
            getattr(ui, f"Simul_{field}_checkbox").setChecked(bool(getattr(config, key)))
        ui.Simul_difficulty_combo.addItems([str(value) for value in config.allow_difficult])
        ui.Simul_difficulty_combo.setCurrentText(str(config.difficult))
        ui.Simul_fate_combo.addItems(config.fates)
        ui.Simul_fate_combo.setCurrentText(config.fate)
        ui.Simul_timezone_combo.addItems(config.timezones)
        ui.Simul_timezone_combo.setCurrentText(config.timezone)
        ui.Simul_max_run_input.setText(str(config.max_run))

    def persist(self):
        ui = self.section
        values = {
            "max_run": int(ui.Simul_max_run_input.text()),
            "difficult": ui.Simul_difficulty_combo.currentText(),
            "fate": ui.Simul_fate_combo.currentText(),
            "timezone": ui.Simul_timezone_combo.currentText(),
        }
        for key, field in (("bonus", "bonus"),
                           ("speed_mode", "speed"), ("slow_mode", "slow")):
            values[key] = int(getattr(ui, f"Simul_{field}_checkbox").isChecked())
        save_config_values(config, values)
