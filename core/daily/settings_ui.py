"""日常内核配置界面：配置控件待补充。"""

from PyQt5.QtWidgets import QLabel

from tool.gui.settings_dialog import SettingsDialog as BaseDialog


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("日常内核配置", parent)
        # 配置项待补充；保留可见区域，主窗口的配置入口才有属于本模块的内容。
        self.section = QLabel("日常内核配置项待补充。")
        self.content_layout.addWidget(self.section)

    def persist(self):
        """日常内核暂无配置项，保存时不写入任何值。"""
