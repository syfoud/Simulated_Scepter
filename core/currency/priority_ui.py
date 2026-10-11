
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.currency.settings import (
    load_currency_settings,
    load_default_priority,
    save_currency_settings,
)
from tool.storage import config_path


class CurrencyPriorityListWidget(QListWidget):
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


class Priority0ListWidget(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)

        viewport = self.viewport()
        assert viewport is not None

        width = viewport.width()
        self.setGridSize(QSize(width, 32))

        if self.count():
            item = self.item(0)
            assert item is not None
            item.setSizeHint(QSize(width, 32))


class CurrencyPriorityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("自定义投资环境优先级")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
        self.resize(1050, 850)

        self.priority_lists = []

        main_layout = QVBoxLayout(self)

        sections = [
            ("必选环境", "prior_envir"),
        ]

        for title, key in sections:
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(label)

            list_widget = self.create_priority_list()
            list_widget.priority_key = key
            self.priority_lists.append(list_widget)
            main_layout.addWidget(list_widget)

        priority_0_label = QLabel("优先级0")
        priority_0_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(priority_0_label)

        priority_0_list = self.create_priority_0_list()
        main_layout.addWidget(priority_0_list)

        sections = [
            ("优先级1环境", "envir_1"),
            ("优先级2环境", "envir_2"),
            ("优先级3环境", "envir_3"),
            ("优先级4环境", "envir_4"),
        ]

        for title, key in sections:
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(label)

            list_widget = self.create_priority_list()
            list_widget.priority_key = key
            self.priority_lists.append(list_widget)
            main_layout.addWidget(list_widget)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.restore_default_button = QPushButton("恢复默认")
        self.save_button = QPushButton("保存")

        button_layout.addWidget(self.restore_default_button)
        button_layout.addWidget(self.save_button)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self.restore_default_button.clicked.connect(
            self.restore_default
        )
        self.save_button.clicked.connect(
            self.save_current
        )

        self.load_current()

    @staticmethod
    def create_priority_list():
        list_widget = CurrencyPriorityListWidget()

        list_widget.setViewMode(QListWidget.IconMode)
        list_widget.setFlow(QListWidget.LeftToRight)
        list_widget.setWrapping(True)
        list_widget.setResizeMode(QListWidget.Adjust)

        list_widget.setDragEnabled(True)
        list_widget.setAcceptDrops(True)
        list_widget.setDropIndicatorShown(False)
        list_widget.setDragDropMode(QAbstractItemView.DragDrop)
        list_widget.setDefaultDropAction(Qt.MoveAction)

        list_widget.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        list_widget.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        list_widget.setSpacing(5)
        list_widget.setGridSize(QSize(175, 38))

        list_widget.setMinimumHeight(75)
        list_widget.setMaximumHeight(150)

        return list_widget

    @staticmethod
    def create_priority_0_list():
        list_widget = Priority0ListWidget()

        list_widget.setViewMode(QListWidget.IconMode)
        list_widget.setFlow(QListWidget.LeftToRight)
        list_widget.setWrapping(False)
        list_widget.setResizeMode(QListWidget.Adjust)

        list_widget.setDragEnabled(False)
        list_widget.setAcceptDrops(False)
        list_widget.setDropIndicatorShown(False)
        list_widget.setMovement(QListWidget.Static)

        list_widget.setSelectionMode(
            QAbstractItemView.NoSelection
        )
        list_widget.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        list_widget.setSpacing(0)
        list_widget.setGridSize(QSize(175, 32))
        list_widget.setFixedHeight(42)

        item = QListWidgetItem("水梦梦天下第一可爱！")
        item.setSizeHint(QSize(0, 32))
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)

        list_widget.addItem(item)

        return list_widget

    def load_current(self):
        currency_settings = load_currency_settings(path=config_path(__file__))
        priority = currency_settings["priority"]
        self.populate_lists(priority)

    def populate_lists(self, data):
        for list_widget in self.priority_lists:
            list_widget.clear()

            for text in data.get(list_widget.priority_key, []):
                item = QListWidgetItem(text)
                item.setSizeHint(QSize(165, 32))
                list_widget.addItem(item)

    def collect_current(self):
        data = {}

        for list_widget in self.priority_lists:
            data[list_widget.priority_key] = [
                list_widget.item(index).text()
                for index in range(list_widget.count())
            ]

        return data

    def save_current(self):
        data = self.collect_current()

        try:
            currency_settings = load_currency_settings(path=config_path(__file__))
            currency_settings["priority"] = data
            save_currency_settings(currency_settings, path=config_path(__file__))
        except OSError as error:
            QMessageBox.critical(
                self,
                "错误",
                f"投资环境优先级保存失败：{error}",
            )
            return

        QMessageBox.information(
            self,
            "提示",
            "投资环境优先级已保存",
        )

    def restore_default(self):
        default_priority = load_default_priority()
        self.populate_lists(default_priority)

        try:
            currency_settings = load_currency_settings(path=config_path(__file__))
            currency_settings["priority"] = default_priority
            save_currency_settings(currency_settings, path=config_path(__file__))
        except OSError as error:
            QMessageBox.critical(
                self,
                "错误",
                f"恢复默认失败：{error}",
            )
            return

        QMessageBox.information(
            self,
            "提示",
            "投资环境优先级已恢复默认",
        )

