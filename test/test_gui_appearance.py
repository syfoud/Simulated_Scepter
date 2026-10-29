"""离屏验证外观切换、输出内容与绘制资源，不启动游戏或热键监听。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QAbstractAnimation, QEvent, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget

from load_ui import QMainWindowLoadUI
from logger_printer import QMainWindowLog
from route import PATHS
from tool import GLOBAL
from tool.gui.settings_dialog import SettingsDialog


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "gui_settings.json"
        defaults = json.loads((Path(PATHS["root"]) / "resource/gui_settings_default.json").read_text(encoding="utf-8"))
        defaults.update({"appearance": "dark", "skin_type": 8, "other": {"keep": True}})
        self.config.write_text(json.dumps(defaults), encoding="utf-8")
        self.enterContext(patch.dict(PATHS, {"user": folder.name}))
        self.enterContext(patch.multiple(GLOBAL, PRINT_TO_UI=None, IMAGE_TO_UI=None, DIALOG=None, create=True))
        self.window = QMainWindowLog()
        self.addCleanup(self.dispose)
        self.window.resize(1240, 760)
        self.window.show()
        self.app.processEvents()

    def dispose(self):
        # 主窗口的 closeEvent 会退出进程，测试仅释放自己创建的 Qt 资源。
        self.window.hide()
        self.window.tray_icon.hide()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def foreground(self, text):
        cursor = self.window.TextBrowser.document().find(text)
        self.assertFalse(cursor.isNull())
        return cursor.charFormat().foreground().color().name().upper()

    def test_switch_button_precedes_window_controls_and_persists_only_appearance(self):
        window = self.window
        self.assertLess(window.Button_Appearance.x(), window.Button_MostMinimized.x())
        self.assertFalse(window.Button_Appearance.icon().isNull())
        window.Button_Appearance.click()
        self.assertEqual(window.theme, "light")
        self.assertGreater(self.app.palette().color(QPalette.Window).lightness(), 240)
        settings = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(settings["appearance"], "light")
        self.assertEqual(settings["other"], {"keep": True})
        self.assertEqual(settings["skin_type"], 8)
        self.assertIn("毛玻璃", window.Button_Appearance.toolTip())
        window.Button_Appearance.click()
        self.assertEqual(window.theme, "dark")

    def test_saved_native_appearance_is_restored_on_reopen(self):
        self.window.Button_Appearance.click()
        other = QMainWindowLoadUI()
        try:
            self.assertEqual(other.theme, "light")
            self.assertGreater(self.app.palette().color(QPalette.Window).lightness(), 240)
        finally:
            other.tray_icon.hide()
            other.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_native_window_buttons_keep_original_size_and_transparent_chrome(self):
        self.window.set_appearance("light")
        self.app.processEvents()
        image = self.window.MainFrame.grab().toImage()
        for button in (self.window.Button_Appearance, self.window.Button_MostMinimized,
                       self.window.Button_Minimized, self.window.Button_Exit):
            self.assertEqual((button.width(), button.height()), (40, 40))
            point = button.mapTo(self.window.MainFrame, button.rect().topLeft())
            # 旧版按钮的角落直接露出白色背景，没有 Qt 原生按钮的灰色边框。
            self.assertEqual(image.pixelColor(point.x() + 2, point.y() + 2).getRgb(), (255, 255, 255, 255))

    def test_resource_card_and_stop_control_remain_visible_at_minimum_size(self):
        self.window.resize(1240, 760)
        self.app.processEvents()
        for widget in (self.window.resource_panel, self.window.stop_btn):
            point = widget.mapTo(self.window.Tab1, widget.rect().bottomRight())
            self.assertTrue(self.window.Tab1.rect().contains(point))
        self.assertGreater(self.window.resource_panel.x(), self.window.side_panel.geometry().right())
        self.assertEqual(self.window.resource_panel.y(), self.window.side_panel.y())
        self.assertEqual(self.window.resource_panel.height(), self.window.side_panel.height())
        self.assertGreater(self.window.TextBrowser.width(), self.window.side_panel.width() + self.window.resource_panel.width())
        self.assertGreaterEqual(self.window.TextBrowser.width(), 584)

    def test_performance_toggle_resizes_window_and_preserves_output_width(self):
        window = self.window
        for theme in ("dark", "light"):
            window.set_appearance(theme)
            window.resize(1460, 800)
            self.app.processEvents()
            original_width = window.TextBrowser.width()
            original_size = window.size()
            original_position = window.pos()
            panel_width = window.resource_panel.width() + window.Lay_Tab1.spacing()
            text = window.TextBrowser.toPlainText()
            window.Button_Resources.click()
            self.app.processEvents()
            self.assertTrue(window.resource_panel.isHidden())
            self.assertFalse(window.resource_panel.sampler.active.is_set())
            self.assertEqual(window.width(), original_size.width() - panel_width)
            self.assertEqual(window.height(), original_size.height())
            self.assertEqual(window.pos(), original_position)
            self.assertEqual(window.TextBrowser.width(), original_width)
            self.assertEqual(window.TextBrowser.toPlainText(), text)
            settings = json.loads(self.config.read_text(encoding="utf-8"))
            self.assertFalse(settings["resources_visible"])
            self.assertEqual(settings["other"], {"keep": True})
            window.Button_Resources.click()
            self.app.processEvents()
            self.assertTrue(window.resource_panel.isVisible())
            self.assertTrue(window.resource_panel.sampler.active.is_set())
            self.assertEqual(window.size(), original_size)
            self.assertEqual(window.pos(), original_position)
            self.assertEqual(window.TextBrowser.width(), original_width)
            self.assertIn("收起", window.Button_Resources.toolTip())

    def test_collapsed_resources_restore_on_reopen_and_allow_compact_window(self):
        expanded_minimum = self.window.minimumSizeHint().width()
        self.window.Button_Resources.click()
        other = QMainWindowLoadUI()
        try:
            other.show()
            other.resize(960, 760)
            self.app.processEvents()
            self.assertTrue(other.resource_panel.isHidden())
            self.assertFalse(other.Button_Resources.isChecked())
            self.assertFalse(other.resource_panel.sampler.active.is_set())
            self.assertLess(other.width(), expanded_minimum)
            compact_width = other.width()
            output_width = other.TextBrowser.width()
            panel_width = other.resource_panel.width() + other.Lay_Tab1.spacing()
            other.Button_Resources.click()
            self.app.processEvents()
            self.assertTrue(other.resource_panel.isVisible())
            self.assertGreaterEqual(other.width(), expanded_minimum)
            self.assertEqual(other.width(), compact_width + panel_width)
            self.assertEqual(other.TextBrowser.width(), output_width)
            self.assertTrue(other.Tab1.rect().contains(other.resource_panel.geometry().bottomRight()))
        finally:
            other.hide()
            other.tray_icon.hide()
            other.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_performance_save_failure_keeps_panel_and_button_state(self):
        original_size = self.window.size()
        output_width = self.window.TextBrowser.width()
        with patch("load_ui.update_settings", side_effect=OSError("只读配置")), patch.object(QMessageBox, "warning") as warning:
            self.window.Button_Resources.click()
        self.assertTrue(self.window.resource_panel.isVisible())
        self.assertTrue(self.window.Button_Resources.isChecked())
        self.assertEqual(self.window.size(), original_size)
        self.assertEqual(self.window.TextBrowser.width(), output_width)
        self.assertTrue(json.loads(self.config.read_text(encoding="utf-8"))["resources_visible"])
        warning.assert_called_once()

    def test_promotions_and_log_history_survive_round_trip_with_readable_colors(self):
        window = self.window
        initial = window.TextBrowser.toPlainText()
        for text in ("免费的star", "赞助", "https://github.com/syfoud/Simulated_Scepter", "870863632"):
            self.assertIn(text, initial)
        GLOBAL.PRINT_TO_UI.emit("切换前的错误", color_level=1, time=False)
        cursor = window.TextBrowser.document().find("免费的star")
        window.TextBrowser.setTextCursor(cursor)
        selection = cursor.selectedText()
        before = window.TextBrowser.toPlainText()
        window.Button_Appearance.click()
        self.assertEqual(window.TextBrowser.toPlainText(), before)
        self.assertEqual(window.TextBrowser.textCursor().selectedText(), selection)
        self.assertEqual(self.foreground("切换前的错误"), "#C80000")
        GLOBAL.PRINT_TO_UI.emit("切换后的错误", color_level=1, time=False)
        self.assertEqual(self.foreground("切换后的错误"), "#C80000")
        window.Button_Appearance.click()
        self.assertEqual(self.foreground("切换前的错误"), "#F0A5B4")
        self.assertEqual(self.foreground("切换后的错误"), "#F0A5B4")

    def test_output_keeps_most_width_and_native_background_is_opaque_white(self):
        for theme in ("dark", "light"):
            self.window.set_appearance(theme)
            for width in (1240, 1800):
                self.window.resize(width, 760)
                self.app.processEvents()
                self.assertGreater(self.window.TextBrowser.width(), self.window.side_panel.width() + self.window.resource_panel.width())
                self.assertGreaterEqual(self.window.TextBrowser.width(), 584)
            if theme == "light":
                image = self.window.TextBrowser.viewport().grab().toImage()
                self.assertEqual(image.pixelColor(image.width() // 2, image.height() - 20).getRgb(), (255, 255, 255, 255))

    def test_page_effects_are_released_after_rapid_switches(self):
        for index in (1, 2, 0, 2, 1):
            self.window.tabWidget.setCurrentIndex(index)
            self.app.processEvents()
        QTest.qWait(240)
        self.assertIsNone(self.window.animated_page)
        for index in range(self.window.tabWidget.count()):
            self.assertIsNone(self.window.tabWidget.widget(index).graphicsEffect())

    def test_hover_finishes_and_disabled_controls_do_not_emit_clicks(self):
        button = self.window.calibrate_btn
        self.app.sendEvent(button, QEvent(QEvent.Enter))
        QTest.qWait(170)
        self.assertAlmostEqual(button.hover, 1.0)
        self.assertEqual(button.hover_animation.state(), QAbstractAnimation.Stopped)
        self.app.sendEvent(button, QEvent(QEvent.Leave))
        QTest.qWait(170)
        self.assertAlmostEqual(button.hover, 0.0)
        clicked = Mock()
        button.clicked.connect(clicked)
        button.setEnabled(False)
        QTest.mouseClick(button, Qt.LeftButton)
        clicked.assert_not_called()

    def test_saving_failure_keeps_current_appearance(self):
        with patch("load_ui.update_settings", side_effect=OSError("只读配置")), patch.object(QMessageBox, "warning") as warning:
            self.window.Button_Appearance.click()
        self.assertEqual(self.window.theme, "dark")
        warning.assert_called_once()

    def test_dialog_palette_tracks_both_appearances_and_no_skin_page_remains(self):
        self.assertIsNone(self.window.findChild(QWidget, "skin1"))
        for theme in ("dark", "light"):
            self.window.set_appearance(theme)
            dialog = SettingsDialog("配置", self.window)
            try:
                self.assertEqual(dialog.palette().color(QPalette.Window), self.app.palette().color(QPalette.Window))
            finally:
                dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
