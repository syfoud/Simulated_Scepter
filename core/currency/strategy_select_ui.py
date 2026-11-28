"""投资策略多选对话框：带搜索框的多列勾选，选项来自 298 条名单。

目标策略与负面策略共用这一个对话框，只换标题和提示。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from core.currency.checkbox_list_ui import SearchableCheckList
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

        self.list = SearchableCheckList(
            STRATEGY_NAMES,
            columns=self.COLUMNS,
            selected=selected,
            placeholder="搜索策略名（例如：军火、星徽、期货）",
            parent=self,
        )
        layout.addWidget(self.list, 1)

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
        return self.list.selected_names()
