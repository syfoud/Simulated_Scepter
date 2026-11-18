"""投资策略多选对话框：三列勾选，选项来自 298 条名单。

目标策略与负面策略共用这一个对话框，只换标题和提示。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.currency.strategies import STRATEGY_NAMES


class StrategySelectDialog(QDialog):
    """勾选若干个策略；选中的写回配置。"""

    COLUMNS = 3

    def __init__(self, selected=(), parent=None, title="选择投资策略", hint=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())

        layout = QVBoxLayout(self)
        if hint:
            label = QLabel(hint)
            label.setWordWrap(True)
            layout.addWidget(label)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        grid = QGridLayout(content)
        grid.setAlignment(Qt.AlignTop)

        selected = set(selected)
        self.checkboxes = {}
        for index, name in enumerate(STRATEGY_NAMES):
            box = QCheckBox(name, content)
            box.setChecked(name in selected)
            self.checkboxes[name] = box
            grid.addWidget(box, index // self.COLUMNS, index % self.COLUMNS)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        available = self.screen().availableGeometry()
        self.resize(min(900, available.width() - 80), min(640, available.height() - 120))

    def selected_strategies(self):
        """按名单顺序返回勾选项，保证配置里的顺序稳定。"""
        return [name for name in STRATEGY_NAMES if self.checkboxes[name].isChecked()]
