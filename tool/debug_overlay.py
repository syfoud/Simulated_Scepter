"""调试识别遮罩：把状态机命中的状态和位置画在游戏窗口上方。

遮罩是程序自己创建的独立置顶窗口，不向游戏进程注入任何代码，也不接收鼠标；
只有全局调试模式打开时，状态机才把命中结果交给它。
窗口位置按进程当前的 DPI 上下文换算，与 Qt 自己的窗口坐标一致，高缩放下同样能贴住游戏画面。

注意：识别用的截图仍是前台屏幕截取（见 tool/screenshot.py 的 GDI BitBlt），遮罩直接画在游戏画面上，
红框和状态名会被一起截进画面，实机测试时会对模板匹配与 OCR 造成一定干扰，因此它只用于调试观察。
"""

import time

import win32gui
from PyQt5.QtCore import QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from tool import GLOBAL
from tool.log import CUS_LOGGER
from tool.utils.game_window import find_game_window


class OverlaySignal(QObject):
    """跨线程把状态机命中结果交给主线程的遮罩窗口。"""

    match_signal = pyqtSignal(str, object)  # (状态名, 识别框或 None)


overlay_signal = OverlaySignal()


def publish_match(name, box):
    """发布一次状态机命中；非全局调试模式直接忽略。

    Args:
        name: 状态机命中的状态名，取自动作脚本里的 name。
        box: 识别框 [左, 上, 右, 下]，1920x1080 客户区像素坐标；纯状态触发没有位置时为 None。
    """
    if not GLOBAL.DEBUG_MODE:
        return
    overlay_signal.match_signal.emit(name, box)


def ui_client_rect(hwnd):
    """客户区在程序界面坐标系中的矩形 (左, 上, 宽, 高)。

    这里不能像截图那样临时切到物理像素上下文：Qt 的窗口坐标跟随进程的 DPI 感知级别，
    进程不感知 DPI 时系统会连尺寸一起缩放，只有用同一套坐标，遮罩才能贴住游戏画面。
    """
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x0, y0 = win32gui.ClientToScreen(hwnd, (left, top))
    x1, y1 = win32gui.ClientToScreen(hwnd, (right, bottom))
    return x0, y0, x1 - x0, y1 - y0


class DebugOverlay(QWidget):
    """覆盖在游戏窗口上方的透明遮罩，用红框标出状态机命中的状态与位置。"""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # 遮罩随整个程序存活，关闭主界面时不能因为它还开着而留下进程
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.marks = []
        self.scale_x = self.scale_y = 1.0
        # 定位游戏窗口失败后停用遮罩：调试显示出错不能拖垮任务
        self.available = True
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.expire)

    def add_mark(self, name, box):
        """记录一次命中并立即重画；同名状态只保留最新一条。"""
        if not self.available:
            return
        self.marks = [mark for mark in self.marks if mark["name"] != name]
        self.marks.append({"name": name, "box": box, "time": time.monotonic()})
        # 同一轮里可能连续命中多个状态，只保留最近几条，避免旧标记糊满画面
        self.marks = self.marks[-8:]
        if self.place():
            self.show()
            self.raise_()
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def place(self):
        """把遮罩对准游戏客户区，返回是否找到了可用的游戏窗口。"""
        try:
            window = find_game_window(prefer_foreground=True)
            if window is None:
                self.hide()
                return False
            left, top, width, height = ui_client_rect(window.hwnd)
        except Exception as error:
            # 枚举窗口可能与游戏窗口重建竞争；异常一旦传进 Qt 槽，PyQt 会直接终止进程
            CUS_LOGGER.warning("调试识别遮罩定位游戏窗口失败，已停止显示：%s", error)
            self.available = False
            self.marks = []
            self.timer.stop()
            self.hide()
            return False
        if width <= 0 or height <= 0:
            self.hide()
            return False
        self.setGeometry(left, top, width, height)
        # 识别框按 1920x1080 客户区绘制，窗口尺寸变化时按同一比例缩放
        self.scale_x, self.scale_y = width / 1920, height / 1080
        return True

    def expire(self):
        """丢弃超时未刷新的标记；全部过期后隐藏遮罩。"""
        now = time.monotonic()
        # 状态机每轮都会重新发布，超过 1 秒没刷新的标记说明已经不再命中
        marks = [mark for mark in self.marks if now - mark["time"] < 1.0]
        if len(marks) == len(self.marks):
            return
        self.marks = marks
        if marks:
            self.update()
        else:
            self.timer.stop()
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 逐像素透明窗口要先清成透明色，否则上一帧的红框会留在画面上
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for mark in self.marks:
            box = mark["box"]
            width = metrics.horizontalAdvance(mark["name"]) + 12
            height = metrics.height() + 6
            if box is None:
                # 纯状态触发没有识别位置：只在画面顶部居中标注状态名
                label = QRect((self.width() - width) // 2, 8, width, height)
            else:
                left = round(box[0] * self.scale_x)
                top = round(box[1] * self.scale_y)
                frame = QRect(left, top, round(box[2] * self.scale_x) - left,
                              round(box[3] * self.scale_y) - top)
                painter.fillRect(frame, QColor(255, 0, 0, 40))
                painter.setPen(QPen(QColor(255, 0, 0), 2))
                painter.drawRect(frame)
                # 状态名贴在识别框上方；贴出窗口顶部时改画在框内
                label = QRect(left, top - height if top - height >= 0 else top, width, height)
            painter.fillRect(label, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 0, 0))
            painter.drawText(label, Qt.AlignCenter, mark["name"])
