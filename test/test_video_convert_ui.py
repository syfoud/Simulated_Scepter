"""界面一致性：异常视频转换控件必须存在于进阶设置页，且布局对齐、宽度够用。

断言的是**运行时几何**（控件实际位置与宽度），而不是 XML 里的某个属性名——
这样无论用 sizePolicy 还是 FixedWidth 实现，只要效果正确就能通过。
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt5 import QtCore, QtWidgets, uic

UI_PATH = Path(__file__).resolve().parents[1] / "resource" / "ui" / "UI.ui"


class VideoConvertUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(UI_PATH).getroot()
        # QApplication 与窗口都由类持有：若只在某个测试里创建成局部变量，它会在该测试
        # 结束时被回收，Qt 随之销毁已建的控件，后续测试拿到的是被删除的对象。
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

        cls.window = QtWidgets.QMainWindow()
        uic.loadUi(str(UI_PATH), cls.window)
        cls.window.resize(900, 900)
        cls.window.show()
        cls._settle()
        # 切到进阶设置页，让该页布局真正生效
        tabs = cls.window.findChild(QtWidgets.QTabWidget)
        for index in range(tabs.count()):
            if tabs.tabText(index) == "进阶设置":
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

    def widget(self, name):
        return self.root.find(f".//widget[@name='{name}']")

    def left(self, name):
        widget = getattr(self.window, name)
        return widget.mapTo(self.window, widget.rect().topLeft()).x()

    def test_controls_live_in_advanced_settings_page(self):
        # 控件要挂在「进阶设置」页的滚动区域里，且与“视频保存需求数”同处一个布局
        main_page = self.widget("advanced_settings_main_page")
        self.assertIsNotNone(main_page)

        for name in ("video_convert_label", "video_convert_mode_combo", "video_convert_btn"):
            self.assertIsNotNone(self.widget(name), f"UI.ui 缺少控件 {name}")

        container = main_page.find(".//layout[@name='horizontalLayout_video_convert']")
        self.assertIsNotNone(container)
        self.assertIsNotNone(container.find(".//widget[@name='video_convert_btn']"))

    def test_button_text(self):
        self.assertEqual(
            self.widget("video_convert_btn").findtext("property/string"), "转换")

    def test_combo_aligns_with_the_row_above(self):
        """combobox 左边缘必须与上方输入框一致，中间不留空档。"""
        self.assertEqual(
            self.left("video_convert_mode_combo"), self.left("recording_time_input"),
            "combobox 未与上方输入框左对齐")
        # 两行的标签同宽，这是对齐成立的原因
        self.assertEqual(
            getattr(self.window, "video_convert_label").width(),
            getattr(self.window, "label_23").width(),
            "label 宽度与上方 label 不一致，会导致 combobox 错位")

    def test_only_combo_takes_extra_width(self):
        """加宽窗口时只有 combobox 变宽，标签与按钮不动。"""
        before = {name: getattr(self.window, name).width()
                  for name in ("video_convert_label", "video_convert_mode_combo",
                               "video_convert_btn")}

        self.window.resize(1100, 900)
        self._settle()
        after = {name: getattr(self.window, name).width()
                 for name in before}

        self.assertEqual(after["video_convert_label"], before["video_convert_label"])
        self.assertEqual(after["video_convert_btn"], before["video_convert_btn"])
        self.window.resize(900, 900)
        self._settle()

    def test_convert_button_fits_progress_text(self):
        """按钮宽度必须容得下更长的「转换中...」，否则运行时会截断。"""
        button = self.window.video_convert_btn
        needed = button.fontMetrics().horizontalAdvance("转换中...") + 24  # 内边距与边框
        self.assertGreaterEqual(button.width(), needed,
                                f"按钮宽 {button.width()}px 容不下「转换中...」（约需 {needed}px）")
        self.assertEqual(button.minimumWidth(), button.maximumWidth(),
                         "按钮宽度不固定，文字变化时会挤动 combobox")

    def test_mode_options_are_added_in_code(self):
        # 选项只在代码里添加：若同时写在 .ui 里会与代码添加的叠加成 4 项，
        # 且前两项没有附加模式标识，选中后会静默走错分支。
        combo = self.widget("video_convert_mode_combo")
        self.assertEqual(combo.get("class"), "QComboBox")
        self.assertEqual(combo.findall("item"), [])

        source = (UI_PATH.parents[2] / "new_gui.py").read_text(encoding="utf-8")
        self.assertIn("严格模式：自动删除末尾的不正常帧", source)
        self.assertIn("抢救模式：尽可能保留更多帧，结尾有概率出现异常帧", source)
        self.assertIn('"strict"', source)
        self.assertIn('"rescue"', source)

    def test_code_references_match_ui_names(self):
        source = (UI_PATH.parents[2] / "new_gui.py").read_text(encoding="utf-8")
        for name in ("video_convert_btn", "video_convert_mode_combo"):
            self.assertIn(f"self.{name}", source)
        self.assertIn("self.video_convert_btn.clicked.connect", source)
        self.assertIn("video_convert_finished_signal", source)


if __name__ == "__main__":
    unittest.main()
