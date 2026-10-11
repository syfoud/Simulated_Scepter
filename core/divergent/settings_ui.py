"""差分宇宙配置界面，独立于运行内核与主窗口。"""

from core.divergent.config import config
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.settings import save_config_values
from tool.storage import resource_path


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("差分宇宙配置", parent)
        config.read()
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        for field in ("speed", "weekly", "cpu"):
            getattr(ui, f"Diver_{field}_checkbox").setChecked(bool(getattr(config, field + "_mode")))
        ui.Diver_difficulty_combo.addItems([str(value) for value in config.allow_difficult])
        ui.Diver_difficulty_combo.setCurrentText(str(config.difficult))
        ui.Diver_team_combo.addItems(["追击", "dot", "终结技", "击破", "盾反"])
        ui.Diver_team_combo.setCurrentText(config.team)
        ui.Diver_save_cnt_combo.addItems([str(value) for value in range(5)])
        ui.Diver_save_cnt_combo.setCurrentText(str(config.save_cnt))
        ui.Diver_timezone_combo.addItems(config.timezones)
        ui.Diver_timezone_combo.setCurrentText(config.timezone)
        ui.Diver_max_run_input.setText(str(config.max_run))

    def persist(self):
        ui = self.section
        values = {
            "max_run": int(ui.Diver_max_run_input.text()),
            "difficult": ui.Diver_difficulty_combo.currentText(),
            "team": ui.Diver_team_combo.currentText(),
            "save_cnt": int(ui.Diver_save_cnt_combo.currentText()),
            "timezone": ui.Diver_timezone_combo.currentText(),
        }
        for field in ("speed", "weekly", "cpu"):
            values[field + "_mode"] = int(getattr(ui, f"Diver_{field}_checkbox").isChecked())
        save_config_values(config, values)
