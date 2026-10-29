import json
import os
import sys

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from route import PATHS
from tool import EXTRA
from tool.gui.appearance import apply_appearance
from tool.scripts.createicon import create_qt_icon
from tool.settings import ensure_settings, update_settings


class QMainWindowLoadUI(QtWidgets.QMainWindow):
    appearance_changed = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()

        apply_appearance()
        self.opt = None

        uic.loadUi(os.path.join(PATHS["ui"], "UI.ui"), self)

        self.setWindowTitle("ω- u13.exe - 本软件免费且开源")

        self.setWindowIcon(QIcon(os.path.join(PATHS["logo"], "圆角-FetDeathWing-256x-AllSize.ico")))

        self.Title_Version.setText(EXTRA.VERSION)

        self.tray_icon = None
        self.init_tray_icon()

        self.json_to_opt(str(ensure_settings()))
        self.theme = self.opt.get("appearance", "dark")
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.set_appearance(self.theme)
        self.Button_Appearance.clicked.connect(self.toggle_appearance)
        self.Title_Logo.setPixmap(QtGui.QPixmap(
            os.path.join(PATHS["logo"], "圆角-FetDeathWing-450x.png")
        ).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.MainFrame.set_image(os.path.join(PATHS["ui"], "background.png"))
        self.TextBrowser.document().setDefaultStyleSheet(
            "p { margin-top: 0px; margin-bottom: 7px; line-height: 145%; }"
        )
        self.TextBrowser.document().setMaximumBlockCount(1000)
        self.page_animation = QtCore.QPropertyAnimation(self)
        self.page_animation.setPropertyName(b"opacity")
        self.page_animation.setDuration(180)
        self.page_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.animated_page = None
        self.page_animation.finished.connect(self.finish_page_animation)
        self.tabWidget.currentChanged.connect(self.animate_page)

        self.Button_MostMinimized.clicked.connect(self.minimize_to_tray)

        self.resizable = True
        self.resize_margin = 10
        self.resize_mode = None
        self.original_geometry = None

        # 启用鼠标跟踪，这样即使没有按下鼠标按钮也能接收鼠标移动事件
        self.setMouseTracking(True)
        # 为所有子控件也启用鼠标跟踪
        self.enable_mouse_tracking_for_children()
        self.set_resources_visible(self.opt.get("resources_visible", True))
        self.Button_Resources.clicked.connect(self.toggle_resources)
        self.resource_panel.start_monitor()

    def enable_mouse_tracking_for_children(self):
        """为所有子控件启用鼠标跟踪"""
        for child in self.findChildren(QtWidgets.QWidget):
            child.setMouseTracking(True)
            # 安装事件过滤器来处理子控件的鼠标事件
            child.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，处理子控件的鼠标事件"""
        if event.type() == QtCore.QEvent.MouseMove:
            # 将子控件的鼠标移动事件传递给主窗口处理
            self.update_cursor(obj.mapTo(self, event.pos()))

        return super().eventFilter(obj, event)

    def set_exit_and_minimized_btn_icon(self):
        q_color = QtGui.QColor(240, 240, 240) if self.theme == "dark" else QtGui.QColor(15, 15, 15)
        self.Button_Exit.setIcon(create_qt_icon(q_color=q_color, mode="x"))
        self.Button_Minimized.setIcon(create_qt_icon(q_color=q_color, mode="-"))
        self.Button_MostMinimized.setIcon(create_qt_icon(q_color=q_color, mode="v"))
        self.Button_Appearance.setIcon(create_qt_icon(
            q_color=q_color, mode="sun" if self.theme == "dark" else "moon"))
        for button in self.findChildren(QtWidgets.QToolButton):
            if button is self.engine_settings_btn or button.property("kernelSettings"):
                button.setIcon(create_qt_icon(q_color=q_color, mode="gear"))

    def toggle_appearance(self):
        theme = "light" if self.theme == "dark" else "dark"
        try:
            self.opt = update_settings({"appearance": theme})
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "保存失败", f"外观设置无法保存：{error}")
            return
        self.set_appearance(theme)

    def set_appearance(self, theme):
        self.theme = theme
        apply_appearance(theme)
        self.set_exit_and_minimized_btn_icon()
        caption = "切换到白色原皮" if theme == "dark" else "切换到毛玻璃外观"
        self.Button_Appearance.setToolTip(caption)
        self.Button_Appearance.setAccessibleName(caption)
        self.appearance_changed.emit(theme)
        self.update()

    def toggle_resources(self, visible):
        """合并保存展开状态，保存失败时还原按钮和当前布局。"""
        try:
            self.opt = update_settings({"resources_visible": visible})
        except (OSError, ValueError) as error:
            self.Button_Resources.setChecked(not self.resource_panel.isHidden())
            QtWidgets.QMessageBox.warning(self, "保存失败", f"性能栏设置无法保存：{error}")
            return
        self.set_resources_visible(visible)

    def set_resources_visible(self, visible):
        was_visible = not self.resource_panel.isHidden()
        window_size = self.size()
        if visible != was_visible:
            panel_width = self.resource_panel.width() + self.Lay_Tab1.spacing()
            window_size.setWidth(window_size.width() + (panel_width if visible else -panel_width))
        self.resource_panel.setVisible(visible)
        self.Button_Resources.setChecked(visible)
        self.Button_Resources.setArrowType(Qt.LeftArrow if visible else Qt.RightArrow)
        caption = "收起性能栏" if visible else "展开性能栏"
        self.Button_Resources.setToolTip(caption)
        self.Button_Resources.setAccessibleName(caption)
        # 启动时父窗口尚未显示，显式刷新祖先布局，避免最小宽度仍包含已收起的栏。
        widget = self.resource_panel.parentWidget()
        while widget is not None:
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            widget.updateGeometry()
            widget = widget.parentWidget()
        if visible != was_visible:
            # 随性能栏调整整窗宽度，保留输出框宽度和窗口高度。
            self.resize(window_size)

    def animate_page(self, index):
        """页面切换时短暂淡入；完成后移除效果以免持续重绘。"""
        self.page_animation.stop()
        self.finish_page_animation()
        self.animated_page = self.tabWidget.widget(index)
        effect = QtWidgets.QGraphicsOpacityEffect(self.animated_page)
        self.animated_page.setGraphicsEffect(effect)
        self.page_animation.setTargetObject(effect)
        self.page_animation.setStartValue(0.35)
        self.page_animation.setEndValue(1.0)
        self.page_animation.start()

    def finish_page_animation(self):
        if self.animated_page is not None:
            self.animated_page.setGraphicsEffect(None)
            self.animated_page = None

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip("ω- u13.exe - 正在后台运行")

        tray_menu = QMenu()
        self.restore_action = tray_menu.addAction("一键启动")
        quit_action = tray_menu.addAction("退出程序")


        quit_action.triggered.connect(self.close)

        self.tray_icon.setContextMenu(tray_menu)

        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def minimize_to_tray(self):
        self.hide()
        self.tray_icon.showMessage(
            "ω- u13.exe 已最小化",
            "程序正在后台运行",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def restore_from_tray(self):
        self.show()
        self.setWindowState(Qt.WindowState.WindowActive)

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def closeEvent(self, event):
        self.tray_icon.hide()
        event.accept()
        os._exit(0)

    def queryExit(self):
        QtCore.QCoreApplication.instance().exit()

    _startPos = None
    _endPos = None
    _isTracking = None

    def mouseMoveEvent(self, a0: QtGui.QMouseEvent):
        # 更新光标样式，无论是否正在拖动窗口
        self.update_cursor(a0.pos())

        # 处理窗口移动
        if self._startPos:
            self._endPos = a0.pos() - self._startPos
            self.move(self.pos() + self._endPos)
        # 处理窗口调整大小
        elif self.resize_mode and self.original_geometry:
            self.perform_resize(a0.globalPos())

        # 确保事件继续传递给父类处理
        super().mouseMoveEvent(a0)

    def mousePressEvent(self, a0: QtGui.QMouseEvent):
        child = self.childAt(a0.pos())
        if child is not None and (child is self.FrameTitle or self.FrameTitle.isAncestorOf(child)) and not isinstance(child, QtWidgets.QAbstractButton):
            if a0.button() == QtCore.Qt.MouseButton.LeftButton:
                self._isTracking = True
                self._startPos = QtCore.QPoint(a0.pos().x(), a0.pos().y())
        elif self.resizable and not self.isMaximized():
            resize_mode = self.check_resize_mode(a0.pos())
            if resize_mode:
                self.resize_mode = resize_mode
                self.original_geometry = self.geometry()
                a0.accept()
                return
        # 如果不是标题栏也不是边缘，则重置resize_mode
        else:
            self.resize_mode = None
            self.original_geometry = None

    def mouseReleaseEvent(self, a0: QtGui.QMouseEvent):
        if a0.button() == QtCore.Qt.MouseButton.LeftButton:
            self._isTracking = False
            self._startPos = None
            self._endPos = None
            self.resize_mode = None
            self.original_geometry = None

    def check_resize_mode(self, pos):
        """检查鼠标位置是否在窗口边缘，确定缩放模式"""
        rect = self.rect()
        x, y = pos.x(), pos.y()
        width, height = rect.width(), rect.height()

        # 检查是否在窗口边缘
        if x <= self.resize_margin and y <= self.resize_margin:
            return "top_left"
        elif x >= width - self.resize_margin and y <= self.resize_margin:
            return "top_right"
        elif x <= self.resize_margin and y >= height - self.resize_margin:
            return "bottom_left"
        elif x >= width - self.resize_margin and y >= height - self.resize_margin:
            return "bottom_right"
        elif x <= self.resize_margin:
            return "left"
        elif x >= width - self.resize_margin:
            return "right"
        elif y <= self.resize_margin:
            return "top"
        elif y >= height - self.resize_margin:
            return "bottom"
        return None

    def update_cursor(self, pos):
        """根据鼠标位置更新光标样式"""
        if not self.resizable or self.isMaximized():
            self.setCursor(QtCore.Qt.ArrowCursor)
            return

        mode = self.check_resize_mode(pos)
        if mode in ["top_left", "bottom_right"]:
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        elif mode in ["top_right", "bottom_left"]:
            self.setCursor(QtCore.Qt.SizeBDiagCursor)
        elif mode in ["left", "right"]:
            self.setCursor(QtCore.Qt.SizeHorCursor)
        elif mode in ["top", "bottom"]:
            self.setCursor(QtCore.Qt.SizeVerCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)

    def perform_resize(self, global_pos):
        """执行窗口缩放操作"""
        if not self.original_geometry or not self.resize_mode:
            return

        geometry = QtCore.QRect(self.original_geometry)
        pos = self.mapFromGlobal(global_pos)
        min_width, min_height = self.minimumSizeHint().width(), self.minimumSizeHint().height()

        if self.resize_mode == "top_left":
            new_width = geometry.width() - pos.x()
            new_height = geometry.height() - pos.y()
            if new_width >= min_width:
                geometry.setLeft(geometry.right() - new_width)
            if new_height >= min_height:
                geometry.setTop(geometry.bottom() - new_height)

        elif self.resize_mode == "top_right":
            new_width = pos.x()
            new_height = geometry.height() - pos.y()
            if new_width >= min_width:
                geometry.setRight(geometry.left() + new_width)
            if new_height >= min_height:
                geometry.setTop(geometry.bottom() - new_height)

        elif self.resize_mode == "bottom_left":
            new_width = geometry.width() - pos.x()
            new_height = pos.y()
            if new_width >= min_width:
                geometry.setLeft(geometry.right() - new_width)
            if new_height >= min_height:
                geometry.setBottom(geometry.top() + new_height)

        elif self.resize_mode == "bottom_right":
            new_width = pos.x()
            new_height = pos.y()
            if new_width >= min_width:
                geometry.setRight(geometry.left() + new_width)
            if new_height >= min_height:
                geometry.setBottom(geometry.top() + new_height)

        elif self.resize_mode == "left":
            new_width = geometry.width() - pos.x()
            if new_width >= min_width:
                geometry.setLeft(geometry.right() - new_width)

        elif self.resize_mode == "right":
            new_width = pos.x()
            if new_width >= min_width:
                geometry.setRight(geometry.left() + new_width)

        elif self.resize_mode == "top":
            new_height = geometry.height() - pos.y()
            if new_height >= min_height:
                geometry.setTop(geometry.bottom() - new_height)

        elif self.resize_mode == "bottom":
            new_height = pos.y()
            if new_height >= min_height:
                geometry.setBottom(geometry.top() + new_height)

        self.setGeometry(geometry)
    def json_to_opt(self,file) -> None:
        with EXTRA.FILE_LOCK:
            with open(file=file, encoding="UTF-8") as file:
                data = json.load(file)

        self.opt = data
        return None



if __name__ == "__main__":
    def main():
        app = QtWidgets.QApplication(sys.argv)
        my_main_window = QMainWindowLoadUI()
        my_main_window.show()
        app.exec()
        sys.exit()
    main()
