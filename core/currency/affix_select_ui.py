"""目标词缀多选对话框：带搜索框的多列勾选，选项来自解包的 53 条词缀名。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from core.currency.affixes import AFFIX_NAMES, ordered_selection
from core.currency.checkbox_list_ui import SearchableCheckList


class AffixSelectDialog(QDialog):
    """勾选若干个词缀；不勾表示只统计、不筛选。"""

    COLUMNS = 3

    def __init__(self, selected=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择目标词缀")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())

        layout = QVBoxLayout(self)
        hint = QLabel("勾选要重点关注的词缀（命中会单独记日志与 CSV）；一个都不勾表示只统计全部词缀。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list = SearchableCheckList(
            AFFIX_NAMES,
            columns=self.COLUMNS,
            selected=selected,
            placeholder="搜索词缀名（例如：复仇、护盾、增幅）",
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
        self.resize(min(760, available.width() - 80), min(560, available.height() - 120))

    def selected_affixes(self):
        """按词缀表的顺序返回勾选项，保证配置文件里的顺序稳定。"""
        return ordered_selection(self.list.selected_names())
