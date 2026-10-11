"""寰宇命途配置界面。"""

from core.common import config as runtime_config
from core.common.config import load_runtime_settings
from core.common.runtime_ui import RuntimeSettings
from core.simulated.config import config
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
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        ui.Any_fate_combo.addItems(config.fates)
        ui.Any_fate_combo.setCurrentText(data.get("any_fate", "巡猎"))

    def persist(self):
        save_json_configs([(runtime_config.__file__, self.runtime.collect()),
                           (__file__, {"any_fate": self.section.Any_fate_combo.currentText()})])
