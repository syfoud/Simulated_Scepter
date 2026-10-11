"""寰宇内核共享的运行参数界面，配置键仍由各内核共用。"""

from pathlib import Path

from PyQt5 import uic
from PyQt5.QtWidgets import QWidget

from route import PATHS
from tool.gui.advanced_features import show_unlock_dialog
from tool.storage import resource_path


class RuntimeSettings(QWidget):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        uic.loadUi(str(resource_path(__file__, "ui/RuntimeSettings.ui")), self)
        self.early_stop_checkbox.setChecked(data.get("early_stop", False))
        authorized = (Path(PATHS["model"]) / "kesln.onnx").is_file()
        self.early_stop_checkbox.setEnabled(authorized)
        self.Aboutupdatelock.setVisible(not authorized)
        self.Aboutupdatelock.clicked.connect(lambda: show_unlock_dialog(self))
        self.Iron_blood_max_run_input.setText(str(data.get("max_run_time", 0)))
        self.Iron_blood_interact_time_input.setText(str(data.get("max_interact_time", 40)))
        for key in ("pig_switch_2_role", "silver_wolf_enable", "auto_attack_breakable"):
            getattr(self, key).setChecked(data.get(key, False))
        for slot in range(1, 5):
            self.silver_wolf_switch_combo.addItem(f"{slot}号位", slot)
        slot = data.get("silver_wolf_switch", 1)
        self.silver_wolf_switch_combo.setCurrentIndex(max(0, self.silver_wolf_switch_combo.findData(slot)))
        self.pig_switch_2_role.toggled.connect(self.update_controls)
        self.silver_wolf_enable.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self):
        self.silver_wolf_switch_combo.setEnabled(
            self.pig_switch_2_role.isChecked() or self.silver_wolf_enable.isChecked())

    def early_stop_enabled(self):
        return self.early_stop_checkbox.isEnabled() and self.early_stop_checkbox.isChecked()

    def collect(self):
        return {
            "early_stop": self.early_stop_checkbox.isChecked(),
            "max_run_time": int(self.Iron_blood_max_run_input.text()),
            "max_interact_time": int(self.Iron_blood_interact_time_input.text()),
            "pig_switch_2_role": self.pig_switch_2_role.isChecked(),
            "silver_wolf_enable": self.silver_wolf_enable.isChecked(),
            "silver_wolf_switch": self.silver_wolf_switch_combo.currentData(),
            "auto_attack_breakable": self.auto_attack_breakable.isChecked(),
        }
