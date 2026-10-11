"""通用内核共享参数的独立配置窗口。"""

from core.common.config import load_runtime_settings, save_runtime_settings
from core.common.runtime_ui import RuntimeSettings
from tool.gui.settings_dialog import SettingsDialog as BaseDialog


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("通用内核配置", parent)
        self.section = self.runtime = RuntimeSettings(load_runtime_settings(), self)
        self.content_layout.addWidget(self.runtime)

    def persist(self):
        save_runtime_settings(self.runtime.collect())
