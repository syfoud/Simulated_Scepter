"""寰宇命途配置界面。"""

from core.common import config as runtime_config
from core.common.config import load_runtime_settings
from core.common.runtime_ui import RuntimeSettings, advanced_user_file_exists
from core.any_fate.text_key import FATES
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import (
    load_module_settings,
    resource_path,
    save_json_configs,
)


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("寰宇命途配置", parent)
        data = load_runtime_settings() | load_module_settings(__file__)
        self.runtime = RuntimeSettings(data, self)
        self.content_layout.addWidget(self.runtime)
        # 任意命途没有早停逻辑，早停开关只属于实现它的内核
        self.runtime.early_stop_checkbox.hide()
        self.record_checkbox = self.runtime.add_record_checkbox("录制任意命途视频")
        self.record_checkbox.setChecked(bool(data.get("record", False)))
        self.record_checkbox.setEnabled(advanced_user_file_exists())
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        ui.Any_fate_combo.addItems(FATES)
        ui.Any_fate_combo.setCurrentText(data["any_fate"])

    def persist(self):
        save_json_configs([(runtime_config.__file__, self.runtime.collect()),
                           (__file__, {
                               "any_fate": self.section.Any_fate_combo.currentText(),
                               "record": self.record_checkbox.isChecked(),
                           })])
