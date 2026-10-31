"""界面一致性：文件清理区每行末尾的「文件位置」按钮，以及打开对应目录的行为。"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets, uic

import new_gui
from tool.cleanup import CATEGORIES, CATEGORY_NAMES
from tool.gui.appearance import apply_appearance

UI_PATH = Path(__file__).resolve().parents[1] / "resource" / "ui" / "UI.ui"


class CleanupLocationButtonTests(unittest.TestCase):
    """检查位置按钮的位置、文案、信号，以及主窗口打开目录的处理。"""

    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(UI_PATH).getroot()
        # QApplication 与窗口都由类持有：局部创建的控件会在后续测试前被回收。
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.addClassCleanup(cls.app.setFont, cls.app.font())

        cls.window = QtWidgets.QMainWindow()
        # 直接加载 .ui 不会执行主窗口的字体初始化，测量前复用正式字体。
        apply_appearance()
        cls.window.setFont(cls.app.font())
        uic.loadUi(str(UI_PATH), cls.window)
        cls.section = new_gui.CleanupSettingsSection(cls.window)
        # 1220 是任务页决定的最小窗口宽度；这里验证该宽度下清理行不会撑出横向滚动条。
        cls.window.resize(1220, 800)
        cls.window.show()
        cls._settle()
        tabs = cls.window.findChild(QtWidgets.QTabWidget)
        for index in range(tabs.count()):
            if tabs.widget(index) is cls.window.AbyssTab:
                tabs.setCurrentIndex(index)
                break
        cls._settle()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    @classmethod
    def _settle(cls, ms=250):
        """跑一段真实事件循环：Qt 的布局重算是延迟排队的，不跑不会生效。"""
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def test_buttons_are_the_last_column_of_each_row(self):
        """每个清理对象各有一个末尾列按钮，不再新增更右侧的列。"""
        grid = self.root.find(".//layout[@name='gridLayout_cleanup']")
        self.assertIsNotNone(grid)
        columns = {int(item.get("column")) for item in grid.findall("item")}
        self.assertEqual(max(columns), 4, "位置按钮之后不应再有其他列")

        for row, category in enumerate(CATEGORIES):
            item = grid.find(f".//item[@row='{row}'][@column='4']")
            self.assertIsNotNone(item, f"UI.ui 缺少 {category} 行的位置按钮")
            widget = item.find("widget")
            self.assertEqual(widget.get("name"), f"Cleanup_{category}_open_btn")
            self.assertEqual(widget.get("class"), "AnimatedButton")
            self.assertEqual(
                widget.findtext("property/string"),
                f"{CATEGORY_NAMES[category]}位置",
            )

    def test_buttons_sit_after_the_last_cleanup_text(self):
        """按钮在运行时位于该行最后，且整行仍在滚动区可视宽度内。"""
        area = self.window.advanced_settings_scroll_area
        contents = self.window.advanced_settings_scroll_contents
        self.assertFalse(area.horizontalScrollBar().isVisible(),
                         "清理行被位置按钮撑出横向滚动条")

        for category in CATEGORIES:
            button = getattr(self.window, f"Cleanup_{category}_open_btn")
            label = getattr(self.window, f"Cleanup_{category}_last_label")
            self.assertTrue(button.isVisible(), f"{category} 行的位置按钮不可见")

            left = button.mapTo(contents, QtCore.QPoint(0, 0)).x()
            label_right = label.mapTo(
                contents, QtCore.QPoint(label.width(), 0)).x()
            self.assertGreater(left, label_right,
                               f"{category} 行的位置按钮没有排在「上次清理」之后")
            self.assertLessEqual(left + button.width(), contents.width(),
                                 f"{category} 行的位置按钮超出可视区域")

    def test_click_requests_directory_for_that_category(self):
        """点击按钮只发出打开请求，不在此处直接操作文件系统。"""
        emitted = []
        self.section.open_location_requested.connect(emitted.append)
        try:
            for category in CATEGORIES:
                getattr(self.window, f"Cleanup_{category}_open_btn").click()
        finally:
            self.section.open_location_requested.disconnect(emitted.append)

        self.assertEqual(emitted, list(CATEGORIES))

    def test_main_window_connects_the_request(self):
        """主窗口必须把请求接到打开目录的槽上，否则按钮点了没有反应。"""
        source = (UI_PATH.parents[2] / "new_gui.py").read_text(encoding="utf-8")
        self.assertIn(
            "self.cleanup_section.open_location_requested.connect("
            "self.open_cleanup_directory)",
            source,
        )

    def test_open_directory_opens_the_category_root(self):
        """存在的目录交给资源管理器打开。"""
        directory = tempfile.gettempdir()
        with patch.object(new_gui, "category_directory", return_value=directory), \
                patch.object(new_gui.os, "startfile") as startfile:
            # 只测槽函数本身：完整主窗口依赖键鼠监听与内核注册，这里用普通窗口充当 QWidget 父级。
            new_gui.MainWindow.open_cleanup_directory(self.window, "log")

        startfile.assert_called_once_with(directory)

    def test_missing_directory_is_reported_without_opening(self):
        """目录尚未生成时只提示路径，不创建目录也不打开资源管理器。"""
        missing = str(Path(tempfile.gettempdir()) / "simsce-不存在的目录" / "video")
        with patch.object(new_gui, "category_directory", return_value=missing), \
                patch.object(new_gui.os, "startfile") as startfile, \
                patch.object(new_gui, "QMessageBox") as message_box:
            new_gui.MainWindow.open_cleanup_directory(self.window, "video")

        startfile.assert_not_called()
        message_box.information.assert_called_once()
        self.assertIn(missing, message_box.information.call_args[0][2])

    def test_open_failure_is_reported(self):
        """资源管理器打不开时保留原始错误，并提示用户。"""
        error = OSError("无法关联资源管理器")
        with patch.object(new_gui, "category_directory",
                          return_value=tempfile.gettempdir()), \
                patch.object(new_gui.os, "startfile", side_effect=error), \
                patch.object(new_gui, "QMessageBox") as message_box, \
                patch.object(new_gui, "CUS_LOGGER") as logger:
            new_gui.MainWindow.open_cleanup_directory(self.window, "temp")

        message_box.warning.assert_called_once()
        logger.warning.assert_called_once()
        self.assertIn(error, logger.warning.call_args[0])
        self.assertIn(str(error), message_box.warning.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
