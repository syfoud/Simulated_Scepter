"""投资环境优先级：72 个环境 × 5 个级别的勾选表格。

比原来的拖拽列表省事：环境总量只有 72 个（策略有 298 个），一屏表格就能看全，
勾选即可，不需要拖来拖去。同一行只能勾一个级别（勾新的会自动取消同行的旧勾）。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.currency.envirs import ENVIR_NAMES
from core.currency.settings import PRIORITY_KEYS, load_currency_settings, save_currency_settings
from tool.storage import config_path

LEVEL_TITLES = {
    "prior_envir": "必选",
    "envir_1": "优先级 1",
    "envir_2": "优先级 2",
    "envir_3": "优先级 3",
    "envir_4": "优先级 4",
}

# 彩蛋：优先级 0 的位置一直是这句话，别删
EGG_TEXT = "水梦梦天下第一可爱！"


class CurrencyPriorityListWidget(QListWidget):
    """可拖拽排序的列表（上阵角色优先级等仍在用；环境优先级已改成勾选表格）。"""

    def __init__(self):
        super().__init__()
        self.drop_indicator = None
        self.drop_row = None

    def dragMoveEvent(self, event):
        source = event.source()
        source_item = None

        if isinstance(source, CurrencyPriorityListWidget):
            source_item = source.currentItem()

        target_item = self.itemAt(event.pos())

        # 鼠标位于被拖动的 item 上时
        if target_item is source_item and target_item is not None:
            rect = self.visualItemRect(target_item)
            row = self.row(target_item)

            if event.pos().x() < rect.center().x():
                self.drop_indicator = (
                    rect.left(),
                    rect.top(),
                    rect.bottom(),
                )
                self.drop_row = row
            else:
                self.drop_indicator = (
                    rect.right(),
                    rect.top(),
                    rect.bottom(),
                )
                self.drop_row = row + 1

        # 鼠标位于其他 item 上时
        elif target_item is not None:
            rect = self.visualItemRect(target_item)
            row = self.row(target_item)

            if event.pos().x() < rect.center().x():
                self.drop_indicator = (
                    rect.left(),
                    rect.top(),
                    rect.bottom(),
                )
                self.drop_row = row
            else:
                self.drop_indicator = (
                    rect.right(),
                    rect.top(),
                    rect.bottom(),
                )
                self.drop_row = row + 1

        # 鼠标位于列表空白区域
        elif self.count():
            last_item = self.item(self.count() - 1)
            rect = self.visualItemRect(last_item)

            self.drop_indicator = (
                rect.right(),
                rect.top(),
                rect.bottom(),
            )
            self.drop_row = self.count()

        else:
            self.drop_indicator = None
            self.drop_row = 0

        self.viewport().update()

        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self.drop_indicator = None
        self.drop_row = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        source = event.source()

        if not isinstance(source, CurrencyPriorityListWidget):
            event.ignore()
            return

        source_item = source.currentItem()

        if source_item is None or self.drop_row is None:
            event.ignore()
            return

        source_row = source.row(source_item)
        target_row = self.drop_row

        # 如果来自同一个列表，需要修正删除原 item 后的索引
        if source is self and source_row < target_row:
            target_row -= 1

        # 已经在目标位置，不做任何操作
        if source is self and source_row == target_row:
            self.drop_indicator = None
            self.drop_row = None
            self.viewport().update()

            event.setDropAction(Qt.CopyAction)
            event.accept()
            return

        # 完全由我们自己移动 item
        item = source.takeItem(source_row)

        if item is not None:
            target_row = max(0, min(target_row, self.count()))
            self.insertItem(target_row, item)
            self.setCurrentItem(item)

        self.drop_indicator = None
        self.drop_row = None
        self.viewport().update()

        # 防止 Qt 再次执行 MoveAction
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.drop_indicator is None:
            return

        x, top, bottom = self.drop_indicator

        from PyQt5.QtGui import QPainter, QPen

        painter = QPainter(self.viewport())
        painter.setPen(QPen(Qt.black, 2))
        painter.drawLine(x, top, x, bottom)


class CurrencyPriorityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义投资环境优先级")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())

        layout = QVBoxLayout(self)
        hint = QLabel("勾选每个环境的级别（同一环境只能属于一个级别）；不勾表示不参与优先级。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(len(ENVIR_NAMES) + 1, 1 + len(PRIORITY_KEYS), self)
        self.table.setHorizontalHeaderLabels(
            ["投资环境"] + [LEVEL_TITLES[key] for key in PRIORITY_KEYS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        for row, name in enumerate(ENVIR_NAMES):
            title = QTableWidgetItem(name)
            title.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, title)
            for column in range(1, self.table.columnCount()):
                cell = QTableWidgetItem()
                cell.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                cell.setCheckState(Qt.Unchecked)
                self.table.setItem(row, column, cell)

        # 最后一行是彩蛋（原来挂在「优先级 0」那一行，挪进表格最底部，照旧别删）
        egg_row = len(ENVIR_NAMES)
        egg = QTableWidgetItem(EGG_TEXT)
        egg.setFlags(Qt.ItemIsEnabled)
        egg.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(egg_row, 0, egg)
        self.table.setSpan(egg_row, 0, 1, self.table.columnCount())

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.save_current)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        available = self.screen().availableGeometry()
        self.resize(min(860, available.width() - 80), min(880, available.height() - 100))
        self.load_current()

    def on_item_changed(self, item):
        """一行只允许勾一个级别。"""
        if item.column() == 0 or item.checkState() != Qt.Checked:
            return
        for column in range(1, self.table.columnCount()):
            if column == item.column():
                continue
            other = self.table.item(item.row(), column)
            if other.checkState() == Qt.Checked:
                other.setCheckState(Qt.Unchecked)

    def load_current(self):
        currency_settings = load_currency_settings(path=config_path(__file__))
        self.populate(currency_settings["priority"])

    def populate(self, data):
        rows = {name: row for row, name in enumerate(ENVIR_NAMES)}
        self.table.blockSignals(True)
        for row in range(len(ENVIR_NAMES)):
            for column in range(1, self.table.columnCount()):
                self.table.item(row, column).setCheckState(Qt.Unchecked)
        for column, key in enumerate(PRIORITY_KEYS, start=1):
            for name in data.get(key, []):
                row = rows.get(name)
                if row is None:
                    continue  # 旧配置里的过时环境名直接丢弃
                self.table.item(row, column).setCheckState(Qt.Checked)
        self.table.blockSignals(False)

    def collect_current(self):
        """按表格行序收集，同一级别内的先后就是环境列表顺序。"""
        data = {key: [] for key in PRIORITY_KEYS}
        for row in range(len(ENVIR_NAMES)):
            name = self.table.item(row, 0).text()
            for column, key in enumerate(PRIORITY_KEYS, start=1):
                if self.table.item(row, column).checkState() == Qt.Checked:
                    data[key].append(name)
        return data

    def save_current(self):
        data = self.collect_current()
        try:
            currency_settings = load_currency_settings(path=config_path(__file__))
            currency_settings["priority"] = data
            save_currency_settings(currency_settings, path=config_path(__file__))
        except OSError as error:
            QMessageBox.critical(self, "错误", f"投资环境优先级保存失败：{error}")
            return

        QMessageBox.information(self, "提示", "投资环境优先级已保存")
        self.accept()
