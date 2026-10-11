"""内核配置窗口的公共布局与保存反馈。"""

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())
        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.save_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        available = self.screen().availableGeometry()
        self.resize(min(700, available.width() - 80), min(720, available.height() - 100))

    def add_section(self, path):
        section = uic.loadUi(str(path))
        self.content_layout.addWidget(section)
        return section

    def save_settings(self):
        try:
            self.persist()
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "参数错误", f"配置无法保存：{error}")
            return
        except OSError as error:
            QMessageBox.critical(self, "保存失败", f"配置写入失败：{error}")
            return
        self.accept()

    def persist(self):
        raise NotImplementedError
