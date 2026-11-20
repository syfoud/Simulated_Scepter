"""全局滚轮守卫：下拉框/数字框不再被滚轮改值，滚轮继续用于滚动页面。"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import uic
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tool.gui.wheel_guard import install_wheel_guard

ROOT = Path(__file__).resolve().parents[1]


def send_wheel(app, widget, delta):
    """向控件发一条滚轮事件，并返回事件本身以检查是否被接受。"""
    center = widget.rect().center()
    event = QWheelEvent(
        QPointF(center),
        QPointF(widget.mapToGlobal(center)),
        QPoint(),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    app.sendEvent(widget, event)
    return event


class WheelWindow(QWidget):
    """普通界面（不是设置窗口），验证守卫不依赖某个具体配置窗口。"""

    def __init__(self):
        super().__init__()
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignTop)
        self.combo = QComboBox()
        self.combo.addItems(["甲", "乙", "丙"])
        self.combo.setCurrentIndex(1)
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setValue(10)
        self.double_spin = QDoubleSpinBox()
        self.double_spin.setRange(0, 10)
        self.double_spin.setValue(1.5)
        for widget in (self.combo, self.spin, self.double_spin):
            layout.addWidget(widget)
        # 撑高内容，让页面存在可滚动范围。
        for _ in range(40):
            layout.addWidget(QLabel("占位"))
        self.scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(self.scroll)


class WheelGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        install_wheel_guard(cls.app)

    def setUp(self):
        self.window = WheelWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_combo_ignores_wheel(self):
        before = self.window.combo.currentIndex()
        event = send_wheel(self.app, self.window.combo, -120)
        self.assertEqual(self.window.combo.currentIndex(), before)
        # 未接受的事件会被 Qt 继续交给父控件，页面才能滚动。
        self.assertFalse(event.isAccepted())

    def test_focused_combo_still_ignores_wheel(self):
        """即使控件已被点击获得焦点，滚轮也不改值（不采用焦点判定）。"""
        self.window.activateWindow()
        self.window.combo.setFocus()
        self.app.processEvents()
        self.assertTrue(self.window.combo.hasFocus())
        before = self.window.combo.currentIndex()
        event = send_wheel(self.app, self.window.combo, 120)
        self.assertEqual(self.window.combo.currentIndex(), before)
        self.assertFalse(event.isAccepted())

    def test_spin_boxes_ignore_wheel(self):
        before_spin = self.window.spin.value()
        before_double = self.window.double_spin.value()
        spin_event = send_wheel(self.app, self.window.spin, 120)
        double_event = send_wheel(self.app, self.window.double_spin, -120)
        self.assertEqual(self.window.spin.value(), before_spin)
        self.assertEqual(self.window.double_spin.value(), before_double)
        self.assertFalse(spin_event.isAccepted())
        self.assertFalse(double_event.isAccepted())

    def test_page_still_scrolls_with_wheel(self):
        bar = self.window.scroll.verticalScrollBar()
        bar.setValue(0)
        # 未接受的滚轮事件沿父链最终到达滚动区的 viewport，由它滚动页面。
        send_wheel(self.app, self.window.scroll.viewport(), -120)
        self.assertGreater(bar.value(), 0)

    def test_combo_avoids_wheel_focus(self):
        """控件显示时把 WheelFocus 降为 StrongFocus，滚轮不会抢焦点。"""
        self.assertEqual(self.window.combo.focusPolicy(), Qt.StrongFocus)

    def test_main_settings_tab_combo_ignores_wheel(self):
        """主窗口「设置」标签页的下拉框同样受全局守卫保护。"""
        window = uic.loadUi(str(ROOT / "resource/ui/UI.ui"), QMainWindow())
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        window.tabWidget.setCurrentWidget(window.AbyssTab)
        self.app.processEvents()
        combo = window.capture_backend_combo
        combo.addItems(["甲", "乙", "丙"])
        combo.setCurrentIndex(1)
        self.assertEqual(combo.focusPolicy(), Qt.StrongFocus)
        event = send_wheel(self.app, combo, -120)
        self.assertEqual(combo.currentIndex(), 1)
        self.assertFalse(event.isAccepted())


if __name__ == "__main__":
    unittest.main()
