"""带搜索框的勾选列表：策略/词缀这类几百项的多选界面共用。

抽出来是因为「选择投资策略（含负面）」和「选择目标词缀」两个对话框结构完全一样，
只有标题、提示和名字来源不同；搜索逻辑写两遍就会各自漂移。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class SearchableCheckList(QWidget):
    """一行搜索框 + 若干列复选框；输入关键词即时过滤（不改变已勾选状态）。

    Args:
        names: 可勾选的名字列表，顺序即展示顺序。
        columns: 每行几列。
        selected: 初始勾选的名字集合。
        placeholder: 搜索框提示文字。
        parent: 父控件。
    """

    def __init__(self, names, columns=3, selected=(), placeholder="搜索…", parent=None):
        super().__init__(parent)
        self.names = list(names)
        self.columns = max(1, columns)
        self.checkboxes = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.counter = QLabel(self)
        layout.addWidget(self.counter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        self.grid = QGridLayout(content)
        self.grid.setAlignment(Qt.AlignTop)
        self._content = content

        chosen = set(selected)
        for name in self.names:
            box = QCheckBox(name, content)
            box.setChecked(name in chosen)
            box.stateChanged.connect(self._update_counter)
            self.checkboxes[name] = box

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.search.textChanged.connect(self.apply_filter)
        self.apply_filter("")

    def apply_filter(self, keyword):
        """按关键词重排可见项：命中即显示，全部重排以不留空位。"""
        keyword = (keyword or "").strip().lower()
        for box in self.checkboxes.values():
            self.grid.removeWidget(box)

        row = column = 0
        for name in self.names:
            box = self.checkboxes[name]
            match = not keyword or keyword in name.lower()
            box.setVisible(match)
            if match:
                self.grid.addWidget(box, row, column)
                column += 1
                if column >= self.columns:
                    column = 0
                    row += 1
        self._visible = sum(
            1 for name in self.names
            if not keyword or keyword in name.lower())
        self._update_counter()

    def _update_counter(self, *_args):
        chosen = sum(1 for box in self.checkboxes.values() if box.isChecked())
        self.counter.setText(f"已选 {chosen} 项 · 当前显示 {getattr(self, '_visible', len(self.names))} 项")

    def selected_names(self):
        """按原始顺序返回勾选项，保证写回配置时顺序稳定。"""
        return [name for name in self.names if self.checkboxes[name].isChecked()]

    def set_selected(self, names):
        """按给定集合重设勾选状态（不动搜索框）。"""
        chosen = set(names)
        for name, box in self.checkboxes.items():
            box.setChecked(name in chosen)
        self._update_counter()
