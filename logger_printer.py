import base64
import datetime
import os

import cv2
import numpy
import numpy as np
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QApplication

from load_ui import QMainWindowLoadUI
from route import PATHS
from tool import GLOBAL


class QMainWindowLog(QMainWindowLoadUI):
    signal_dialog = pyqtSignal(str, str)  # 标题, 正文
    signal_print_to_ui = pyqtSignal(str, str, bool)
    signal_image_to_ui = pyqtSignal(numpy.ndarray)

    def __init__(self):
        # 继承父类构造方法
        super().__init__()

        # 链接防呆弹窗
        self.signal_dialog.connect(self.show_dialog)

        # 并不是直接输出, 其emit方法是 一个可以输入 缺省的颜色 或 时间参数 来生成文本 调用 signal_print_to_ui_1
        GLOBAL.PRINT_TO_UI = self.MidSignalPrint(signal_1=self.signal_print_to_ui, theme=self.theme)

        # 真正的 发送信息激活 print 的函数, 被链接到直接发送信息到ui的函数
        self.signal_print_to_ui.connect(self.print_to_ui)

        # 用于支持 输入 路径 或 numpy.ndarray
        GLOBAL.IMAGE_TO_UI = self.MidSignalImage(signal_1=self.signal_image_to_ui)

        # 真正的 发送图片到ui的函数, 被链接到直接发送图片到ui的函数
        self.signal_image_to_ui.connect(self.image_to_ui)

        # 储存在全局
        GLOBAL.DIALOG = self.signal_dialog

        # 打印默认输出提示
        self.start_print()

    class MidSignalPrint:
        """
        模仿信号的类, 但其实本身完全不是信号, 是为了可以接受缺省参数而模仿的中间类,
        该类的emit方法是 一个可以输入 缺省的颜色 或 时间参数 来生成文本的方法
        并调用信号发送真正的信息
        """

        def __init__(self, signal_1, theme):
            super().__init__()
            self.signal_1 = signal_1
            match theme:
                case 'light':
                    self.color_scheme = {
                        1: "C80000",  # 深红色
                        2: "E67800",  # 深橙色暗调
                        3: "006400",  # 深绿色
                        4: "009688",  # 深宝石绿
                        5: "0056A6",  # 深海蓝
                        6: "003153",  # 普鲁士蓝
                        7: "5E2D79",  # 深兰花紫
                        8: "4B0082",  # 靛蓝
                        9: "999999",  # 我也不知道啥色
                    }
                case 'dark':
                    self.color_scheme = {
                        1: "FF4C4C",  # 鲜红色
                        2: "FFA500",  # 橙色
                        3: "00FF00",  # 亮绿色
                        4: "20B2AA",  # 浅海绿色
                        5: "1E90FF",  # 道奇蓝
                        6: "4682B4",  # 钢蓝色
                        7: "9370DB",  # 中兰花紫
                        8: "8A2BE2",  # 蓝紫色
                        9: "CCCCCC",  # 浅灰色
                    }

        def emit(self, text, color_level=9, color=None, time=True, is_line=False, line_type="normal"):
            """
            :param text: 正文文本
            :param color_level: int 1 to 9
            :param color: 支持直接使用颜色代码
            :param time: 是否显示打印时间
            :param is_line: 是否替换本行为横线
            :param line_type: str normal/top/bottom
            :return:
            """
            if color_level in self.color_scheme:
                color = self.color_scheme[color_level]
            elif not color:
                color = self.color_scheme[9]
            if is_line:
                text = "—" * 44
                time = False
                if line_type == "top":
                    text = "‾" * 67
                if line_type == "bottom":
                    text = "_" * 59
            # 处理缺省参数
            self.signal_1.emit(text, color, time)

    class MidSignalImage:
        """
        模仿信号的类, 但其实本身完全不是信号, 是为了可以接受缺省参数而模仿的中间类,
        该类的emit方法是 一个可以输入 numpy.ndarray 或 图片路径 并判断是否读取的方法
        并调用信号发送真正的图片
        """

        def __init__(self, signal_1):
            super().__init__()
            self.signal_1 = signal_1

        def emit(self, image):
            # 根据 路径 或者 numpy.ndarray 选择是否读取
            if type(image) is not np.ndarray:
                # 读取目标图像,中文路径兼容方案
                image_ndarray = cv2.imdecode(buf=np.fromfile(file=image, dtype=np.uint8), flags=-1)
            else:
                image_ndarray = image
            # 处理缺省参数
            self.signal_1.emit(image_ndarray)

    def start_print(self):
        """打印默认输出提示"""
        if self.check_model_file():
            GLOBAL.PRINT_TO_UI.emit(
                text="您好，高级用户！！！欢迎使用ω- u13权杖系统。本系统将用于求解铁血战士计算的终点,一道完美的「毁灭」方程式……",
                color_level=1,
                time=False)
        else:
            GLOBAL.PRINT_TO_UI.emit(
                text="用户，您好！欢迎使用ω- u13权杖系统。本系统将用于求解铁血战士第一因。",
                color_level=2,
                time=False)

        GLOBAL.PRINT_TO_UI.emit(
            text="如果认为本项目对您践行「毁灭」有帮助,可以为开发者于github点免费的star以表支持,或是赞助请开发者喝杯咖啡~",
            color_level=4,
            time=False)
        GLOBAL.PRINT_TO_UI.emit(
            text="项目开源地址:https://github.com/syfoud/Simulated_Scepter 一群:1072802257（已满）二群:870863632",
            color_level=3,
            time=False)

    # 用于展示弹窗信息的方法
    @QtCore.pyqtSlot(str, str)
    def show_dialog(self, title, message):
        # 创建/获取对话框实例
        if not hasattr(self, 'log_dialog') or not self.log_dialog:
            self.log_dialog = QtWidgets.QDialog()
            self.log_dialog.setWindowTitle("对话框 - 用户级运行日志")
            self.log_dialog.resize(800, 400)

            # 创建带滚动条的文本框
            self.text_browser = QtWidgets.QTextBrowser(self.log_dialog)
            layout = QtWidgets.QVBoxLayout(self.log_dialog)
            layout.addWidget(self.text_browser)

            # 添加关闭按钮
            btn_close = QtWidgets.QPushButton("关闭", self.log_dialog)
            btn_close.clicked.connect(self.cleanup_dialog)  # 修改连接方法

            layout.addWidget(btn_close)

            # 绑定关闭事件
            self.log_dialog.finished.connect(self.cleanup_dialog)

        # 格式化日志内容
        log_content = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {title}: {message}\n"

        # 追加内容并自动滚动
        self.text_browser.append(log_content)
        self.text_browser.verticalScrollBar().setValue(
            self.text_browser.verticalScrollBar().maximum()
        )

        # 显示对话框
        if not self.log_dialog.isVisible():
            self.log_dialog.show()

    def cleanup_dialog(self):
        """清理对话框资源"""
        if self.log_dialog:
            self.text_browser.clear()  # 清空内容
            self.log_dialog.deleteLater()
            self.log_dialog = None

    def print_to_ui(self, text, color, time, *args):
        """打印文本到输出框 """
        if args:
            # 使用空格连接多个参数
            text = text + " " + " ".join(str(arg) for arg in args)

        # 时间文本
        text_time = "[{}] ".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")) if time else ""

        # 颜色文本
        text_all = f'<span style="color:#{color};">{text_time}{text}</span>'

        # 限制最大行数为1000行，避免内存爆炸
        max_lines = 1000
        document = self.TextBrowser.document()
        if document.blockCount() > max_lines:
            # 删除最旧的日志块
            cursor = self.TextBrowser.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 删除换行符

        # 输出到输出框
        self.TextBrowser.append(text_all)

        # 自动滚动到最新消息
        self.TextBrowser.verticalScrollBar().setValue(
            self.TextBrowser.verticalScrollBar().maximum()
        )


    def image_to_ui(self, image_ndarray: numpy.ndarray):
        """
        :param image_ndarray: 必须是 numpy.ndarray 对象
        :return:
        """

        # 編碼字節流
        _, img_encoded = cv2.imencode('.png', image_ndarray)

        # base64
        img_base64 = base64.b64encode(img_encoded).decode('utf-8')

        image_html = f"<img src='data:image/png;base64,{img_base64}'>"

        # self.TextBrowser.insertHtml(image_html)

        # 输出到输出框
        self.TextBrowser.append(image_html)

        # 实时输出
        cursor = self.TextBrowser.textCursor()
        cursor.setPosition(cursor.position(), QTextCursor.MoveMode.MoveAnchor)
        cursor.setPosition(cursor.position() + 1, QTextCursor.MoveMode.KeepAnchor)  # 移动到末尾
        self.TextBrowser.setTextCursor(cursor)
        QApplication.processEvents()

    def check_model_file(self):

        model_path = os.path.join(PATHS["root"], "resource", "models", "kesln.onnx")
        model_exists = os.path.exists(model_path)

        if not model_exists:
            self.recording_checkBox2.setEnabled(False)
            self.recording_label_checkbox.setEnabled(False)
            self.recording_time_input.setEnabled(False)
            self.early_stop_checkbox.setEnabled(False)
            self.Iron_blood_first_plane_input.setEnabled(False)
            self.Iron_blood_second_plane_input.setEnabled(False)
            return False
        else:
            self.Aboutupdatelock.setVisible(False)
        return True
