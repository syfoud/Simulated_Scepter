"""弹指一挥模型与共享运行参数的配置界面。"""

from core.common import config as runtime_config
from core.common.config import load_runtime_settings
from core.common.runtime_ui import RuntimeSettings
from core.finger_snap.config import (
    CONFIG_KEY,
    DECISION_MODES,
    MC_SETTING_FIELDS,
    normalize_finger_snap_settings,
)
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import (
    load_module_settings,
    resource_path,
    save_json_configs,
)


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("弹指一挥配置", parent)
        data = load_runtime_settings() | load_module_settings(__file__)
        self.runtime = RuntimeSettings(data, self)
        self.content_layout.addWidget(self.runtime)
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        model = normalize_finger_snap_settings(data.get(CONFIG_KEY, {}))
        for field in MC_SETTING_FIELDS:
            getattr(ui, f"Finger_snap_{field}_input").setText(str(model[field]))
        for plane, target in enumerate(model["plane_targets"], 1):
            getattr(ui, f"Finger_snap_plane{plane}_target_input").setText(str(target))
        for mode, label in DECISION_MODES.items():
            ui.Finger_snap_decision_mode_combo.addItem(label, mode)
        ui.Finger_snap_decision_mode_combo.setCurrentIndex(
            ui.Finger_snap_decision_mode_combo.findData(model["decision_mode"]))
        for field in ("dp_early_stop", "win_rate_dp_early_stop", "mc_dp_early_stop"):
            getattr(ui, f"Finger_snap_{field}_checkbox").setChecked(model[field])
        for field in ("first_plane_threshold", "record_keep_count"):
            getattr(ui, f"Finger_snap_{field}_input").setText(str(model[field]))
        self.runtime.early_stop_checkbox.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self):
        for field in ("dp_early_stop_checkbox", "win_rate_dp_early_stop_checkbox",
                      "mc_dp_early_stop_checkbox", "plane1_target_input", "plane2_target_input",
                      "plane3_target_input", "record_keep_count_input"):
            getattr(self.section, "Finger_snap_" + field).setEnabled(self.runtime.early_stop_enabled())

    def persist(self):
        ui = self.section
        values = {}
        for field in MC_SETTING_FIELDS:
            convert = int if field in ("control_rollouts", "evaluation_rollouts", "min_visits", "seed") else float
            values[field] = convert(getattr(ui, f"Finger_snap_{field}_input").text())
        values["decision_mode"] = ui.Finger_snap_decision_mode_combo.currentData()
        for field in ("dp_early_stop", "win_rate_dp_early_stop", "mc_dp_early_stop"):
            values[field] = getattr(ui, f"Finger_snap_{field}_checkbox").isChecked()
        values["plane_targets"] = [int(getattr(ui, f"Finger_snap_plane{plane}_target_input").text())
                                   for plane in range(1, 4)]
        values["first_plane_threshold"] = float(ui.Finger_snap_first_plane_threshold_input.text())
        values["record_keep_count"] = int(ui.Finger_snap_record_keep_count_input.text())
        # 两部分先一起校验，再合并写入同一文件，避免模型参数非法时只保存一半。
        save_json_configs([(runtime_config.__file__, self.runtime.collect()),
                           (__file__, {CONFIG_KEY: normalize_finger_snap_settings(values)})])
