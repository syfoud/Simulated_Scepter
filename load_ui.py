import json
import os
import shutil
import sys

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase, QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from route import PATHS
from tool import EXTRA
from tool.scripts.createicon import create_qt_icon

ZOOM_RATE = None


def readQss(style):
    with open(style) as f:
        return f.read()


class QMainWindowLoadUI(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()

        self.opt = None

        uic.loadUi(PATHS["ui"] + '\\UI.ui', self)

        self.setWindowTitle("ω- u13.exe - 本软件免费且开源")

        self.setWindowIcon(QIcon(PATHS["logo"] + "\\圆角-FetDeathWing-256x-AllSize.ico"))

        self.Title_Version.setText(EXTRA.VERSION)

        self.theme = self.get_theme()

        self.theme_highlight_color = QtWidgets.QApplication.palette().color(QtGui.QPalette.ColorRole.Highlight).name()

        self.tray_icon = None
        self.init_tray_icon()

        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        self.json_to_opt(settings_path)
        self.skin_set()
        self.font_set()

        self.run_diver_btn.setVisible(False)
        self.tabWidget.setTabVisible(4, False)
        self.label_7.setVisible(False)
        self.Diver_debug_checkbox.setVisible(False)
        self.Simul_debug_checkbox.setVisible(False)
        self.debug_checkox2.setVisible(False)
        self.Diver_speed_checkbox.setVisible(False)
        self.Diver_weekly_checkbox.setVisible(False)
        self.Diver_cpu_checkbox.setVisible(False)
        self.label_10.setVisible(False)
        self.Diver_difficulty_combo.setVisible(False)
        self.label_11.setVisible(False)
        self.Diver_team_combo.setVisible(False)
        self.label_12.setVisible(False)
        self.Diver_save_cnt_combo.setVisible(False)
        self.label_17.setVisible(False)
        self.Diver_timezone_combo.setVisible(False)
        self.label_18.setVisible(False)
        self.Diver_max_run_input.setVisible(False)

        self.Button_MostMinimized.clicked.connect(self.minimize_to_tray)

        self.resizable = True
        self.resize_margin = 10
        self.resize_mode = None
        self.original_geometry = None

        # 启用鼠标跟踪，这样即使没有按下鼠标按钮也能接收鼠标移动事件
        self.setMouseTracking(True)
        # 为所有子控件也启用鼠标跟踪
        self.enable_mouse_tracking_for_children()

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
            self.update_cursor(event.pos())

        return super().eventFilter(obj, event)

    def get_theme(self):
        if self.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128:
            theme = "dark"
        else:
            theme = "light"
        return theme

    def set_theme_common(self):
        self.set_no_border()

        self.set_logo_shadow()

        self.set_exit_and_minimized_btn_icon()

        self.set_image_resource()

    def set_common_theme(self):

        style_sheet = self.styleSheet()

        style_sheet += "#MainFrame{border-radius: 8px; border: 1px solid #3c3d3e;} "

        style_sheet = self.styleSheet()

        match self.theme:
            case "dark":
                style_sheet += "#MainFrame{background-color: #1e1e1e;}"
            case "light":
                style_sheet += "#MainFrame{background-color: #FFFFFF;}"

        self.setStyleSheet(style_sheet)

    def set_logo_shadow(self):
        effect_shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        effect_shadow.setOffset(0, 0)
        effect_shadow.setBlurRadius(6)
        effect_shadow.setColor(QtCore.Qt.GlobalColor.gray)
        self.Title_Logo.setGraphicsEffect(effect_shadow)

    def set_no_border(self):
        self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_exit_and_minimized_btn_icon(self):
        q_color = QtGui.QColor(240, 240, 240) if self.theme == "dark" else QtGui.QColor(15, 15, 15)
        self.Button_Exit.setIcon(create_qt_icon(q_color=q_color, mode="x"))
        self.Button_Minimized.setIcon(create_qt_icon(q_color=q_color, mode="-"))
        self.Button_MostMinimized.setIcon(create_qt_icon(q_color=q_color, mode="v"))


    def set_image_resource(self):

        cus_path = PATHS["root"] + "\\resource\\logo\\圆角-FetDeathWing-450x.png"
        cus_path = cus_path.replace("\\", "/")

        pixmap = QtGui.QPixmap(cus_path).scaled(
            40,
            40,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation
        )
        self.Title_Logo.setPixmap(pixmap)
        self.Title_Logo.setFixedSize(40, 40)
        self.Title_Logo.setScaledContents(True)

        cus_path = PATHS["ui"] + "\\background.png"
        cus_path = cus_path.replace("\\", "/")
        style_sheet = f"""
            #SkinWidget{{
            background-image: url({cus_path});
            background-repeat: no-repeat;
            background-position: center;
            border: none;
            }}
        """

        self.SkinWidget.setStyleSheet(style_sheet)

    def set_theme_default(self):

        self.MainFrame.setStyleSheet("")

        self.set_tab_bar_style()

    def set_main_window_shadow(self):
        effect_shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        effect_shadow.setOffset(0, 0)
        effect_shadow.setBlurRadius(8)
        effect_shadow.setColor(QtCore.Qt.GlobalColor.black)
        self.MainFrame.setGraphicsEffect(effect_shadow)

    def set_tab_bar_style(self):

        style_sheet = self.MainFrame.styleSheet()
        selected_text_color = "#FFFFFF" if self.theme == "dark" else "#000000"

        style_sheet += f"""
            QTabBar::tab {{
                min-width: 136px;
                height: 20px;
                border-style: solid;
                border-top-color: transparent;
                border-right-color: transparent;
                border-left-color: transparent;
                border-bottom-color: transparent;
                border-bottom-width: 1px;
                border-style: solid;
                color: #808086;
                padding: 3px;
                margin-left:3px;
            }}
            QTabBar::tab:selected, QTabBar::tab:last:selected, QTabBar::tab:hover {{
                border-style: solid;
                border-top-color: transparent;
                border-right-color: transparent;
                border-left-color: transparent;
                border-bottom-color: {self.theme_highlight_color};
                border-bottom-width: 2px;
                border-style: solid;
                color: {selected_text_color};
                padding-left: 3px;
                padding-bottom: 2px;
                margin-left:3px;
            }}
            QTabWidget::tab-bar {{
                alignment: center;
            }}
            QTabWidget::pane{{
                border:none;
            }}
            """

        self.MainFrame.setStyleSheet(style_sheet)

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(PATHS["logo"] + "\\圆角-FetDeathWing-256x-AllSize.ico"))
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
        if self.childAt(a0.pos().x(), a0.pos().y()).objectName() == "FrameTitle":
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

    def on_skin_state_changed(self, checked):

        sender = self.sender()

        skin_dict = {
            self.skin1: 1,
            self.skin2: 2,
            self.skin3: 3,
            self.skin4: 4,
            self.skin5: 5,
            self.skin6: 6,
            self.skin7: 7,
            self.skin8: 8,
            self.skin9: 9,
            self.skin10: 10,
            self.skin11: 11
        }
        if checked:
            current_option = skin_dict[sender]
            self.change_style(current_option)


    def getstylefile(self, num):
        skin_path_dict = {
            1: None,
            2: PATHS["theme"] + "\\feiyang\\blacksoft.css",
            3: PATHS["theme"] + "\\feiyang\\flatgray.css",
            4: PATHS["theme"] + "\\feiyang\\lightblue.css",
            5: PATHS["theme"] + "\\GTRONICK\\ElegantDark.qss",
            6: PATHS["theme"] + "\\GTRONICK\\MaterialDark.qss",
            7: PATHS["theme"] + "\\GTRONICK\\NeonButtons.qss",
            8: PATHS["theme"] + "\\GTRONICK\\Aqua.qss",
            9: PATHS["theme"] + "\\GTRONICK\\ManjaroMix.qss",
            10: PATHS["theme"] + "\\GTRONICK\\MacOS.qss",
            11: PATHS["theme"] + "\\GTRONICK\\Ubuntu.qss"
        }

        path = skin_path_dict.get(num)
        return path

    def skin_set(self) -> None:
        my_opt = self.opt["skin_type"]
        self.skin_dict = {
            1: self.skin1,
            2: self.skin2,
            3: self.skin3,
            4: self.skin4,
            5: self.skin5,
            6: self.skin6,
            7: self.skin7,
            8: self.skin8,
            9: self.skin9,
            10: self.skin10,
            11: self.skin11
        }
        for skin in self.skin_dict.values():
            skin.toggled.connect(self.on_skin_state_changed)

        skin = self.skin_dict.get(my_opt)
        if skin:
            skin.setChecked(True)
        self.change_style(my_opt)
    def change_style(self,setting):

        styleFile = self.getstylefile(setting)
        if styleFile is not None:
            qssStyle = readQss(styleFile)
            self.set_theme_common()
            self.MainFrame.setStyleSheet(qssStyle)
            self.set_common_theme()

        else:
            self.set_theme_common()
            self.set_theme_default()
            self.set_common_theme()

    def font_set(self) -> None:
        """
        加载字体文件并设置应用程序默认字体
        通过文件名精确匹配排除base.ttf
        """
        font_dir = PATHS["font"]
        font_database = QFontDatabase()
        first_font_family = None
        valid_font_count = 0
        if os.path.exists(font_dir):
            font_files = os.listdir(font_dir)
            for font_file in font_files:
                if font_file == "base.ttf":
                    continue
                if font_file.endswith(".ttf") or font_file.endswith(".otf"):
                    font_path = os.path.join(font_dir, font_file)
                    font_id = font_database.addApplicationFont(font_path)
                    if font_id != -1:
                        family_names = font_database.applicationFontFamilies(font_id)
                        if valid_font_count == 0 and family_names:
                            first_font_family = family_names[0]
                        valid_font_count += 1

        if first_font_family:
            font = QFont(first_font_family, 8)
            QtWidgets.QApplication.setFont(font)

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
        min_width, min_height = 300, 200  # 最小窗口尺寸

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
