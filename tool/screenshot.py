"""游戏画面截取：前台整屏 BitBlt 与后台窗口捕获。

前台模式用 Screen 从屏幕 DC 拷贝客户区，兼容性最好、开销最低；后台模式改用窗口级
捕获（PrintWindowCapture 或 WgcScreen），游戏窗口被别的窗口盖住时也能取到画面。
后台捕获失败会直接报错，不回退整屏截屏，避免把遮挡窗口的画面当成游戏画面送去识别。
"""

import ctypes
import time
from ctypes import Structure, c_int, c_void_p, wintypes
from ctypes.wintypes import DWORD, LONG, WORD
from threading import Lock

import numpy as np
import win32con
import win32gui

from tool.log import CUS_LOGGER
from tool.utils.game_window import get_client_screen_rect, get_client_size

# PrintWindow 的 nFlags：3 = PW_CLIENTONLY(1) | PW_RENDERFULLCONTENT(2)
_PRINTWINDOW_CLIENT = 3

# 可选择的截图后端；配置为 auto 或未知值时按前台/后台模式自动选择
CAPTURE_BACKENDS = ("screen", "printwindow", "wgc")


class BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]
class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 3)]


def _bitmap_info(width, height):
    """32 位自顶向下的位图描述，宽高与要读取的画面一致。"""
    info = BITMAPINFO()
    info.bmiHeader.biSize = 40
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    info.bmiHeader.biClrUsed = 0
    info.bmiHeader.biClrImportant = 0
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    return info


lock = Lock()
class Screen:
    def __init__(self,w=1920,h=1080):
        self.gdi = ctypes.WinDLL("gdi32")
        self.srcdc  = ctypes.WinDLL("user32").GetWindowDC(0)
        self.memdc = self.gdi.CreateCompatibleDC(self.srcdc)
        self.width, self.height = w, h
        self.bmi = _bitmap_info(w, h)
        self.data = ctypes.create_string_buffer(self.width * self.height * 4)
        self.bmp = self.gdi.CreateCompatibleBitmap(self.srcdc, self.width, self.height)
        self.gdi.SelectObject(self.memdc, self.bmp)

    def close(self):
        """释放当前截图器持有的 GDI 资源。"""
        if self.memdc:
            self.gdi.DeleteDC(self.memdc)
            self.memdc = None
        if self.bmp:
            self.gdi.DeleteObject(self.bmp)
            self.bmp = None
        if self.srcdc:
            ctypes.WinDLL("user32").ReleaseDC(0, self.srcdc)
            self.srcdc = None

    def grab(self, x, y):
        with lock:
            for attempt in range(10):
                try:
                    self.gdi.BitBlt(self.memdc, 0, 0, self.width, self.height, self.srcdc, x, y, 0x40CC0020)
                    bits = self.gdi.GetDIBits(self.memdc, self.bmp, 0, self.height, self.data, self.bmi, 0)
                    if bits != self.height:
                        CUS_LOGGER.warning(f'截图失败！第{attempt + 1}次尝试')
                        time.sleep(0.05)
                        continue
                    return np.frombuffer(bytearray(self.data), dtype=np.uint8).reshape((self.height,self.width,4))[:,:,:3]
                except Exception as e:
                    CUS_LOGGER.warning(f'截图过程中发生异常: {e}, 第{attempt + 1}次尝试')
                    time.sleep(0.05)
                    continue
        CUS_LOGGER.error('截图失败！已达到最大重试次数')
        return np.zeros((self.height,self.width,3), dtype=np.uint8)


class PrintWindowCapture:
    """后台截屏：让游戏窗口把客户区重绘到内存位图。

    Args:
        hwnd: 游戏窗口句柄。
        width: 客户区宽度，物理像素。
        height: 客户区高度，物理像素。
    """

    def __init__(self, hwnd, width, height):
        self.hwnd = hwnd
        self.width, self.height = width, height
        self.lock = Lock()
        self.gdi = ctypes.WinDLL("gdi32")
        self.user32 = ctypes.WinDLL("user32")
        self._configure_prototypes()
        self._bmi = _bitmap_info(width, height)
        self.data = ctypes.create_string_buffer(width * height * 4)
        self._window_dc = None
        self._mem_dc = None
        self._bitmap = None
        try:
            self._window_dc = self.user32.GetDC(hwnd)
            if not self._window_dc:
                raise RuntimeError("获取游戏窗口 DC 失败")
            self._mem_dc = self.gdi.CreateCompatibleDC(self._window_dc)
            self._bitmap = self.gdi.CreateCompatibleBitmap(self._window_dc, width, height)
            if not self._mem_dc or not self._bitmap:
                raise RuntimeError("创建后台截图位图失败")
            self.gdi.SelectObject(self._mem_dc, self._bitmap)
        except Exception:
            self.close()
            raise

    def _configure_prototypes(self):
        """显式声明句柄参数，避免 ctypes 默认按 32 位 int 截断 DC/位图句柄。"""
        self.user32.GetDC.argtypes = (wintypes.HWND,)
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        self.user32.ReleaseDC.restype = c_int
        self.user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
        self.user32.PrintWindow.restype = wintypes.BOOL
        self.user32.SendMessageW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SendMessageW.restype = wintypes.LPARAM
        self.gdi.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateCompatibleBitmap.argtypes = (wintypes.HDC, c_int, c_int)
        self.gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
        self.gdi.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi.GetDIBits.argtypes = (
            wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
            c_void_p, c_void_p, wintypes.UINT)
        self.gdi.GetDIBits.restype = c_int
        self.gdi.DeleteDC.argtypes = (wintypes.HDC,)
        self.gdi.DeleteDC.restype = wintypes.BOOL
        self.gdi.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        self.gdi.DeleteObject.restype = wintypes.BOOL

    def grab(self, x=0, y=0):
        """取一帧客户区画面，返回 height x width x 3 的 BGR 数组。

        Args:
            x: 前台截图用的客户区左上角屏幕坐标；窗口截图固定取客户区，这里不使用。
            y: 同上。
        """
        with self.lock:
            if not self._mem_dc or not win32gui.IsWindow(self.hwnd):
                raise RuntimeError("游戏窗口已关闭，无法后台截图")
            width, height = get_client_size(self.hwnd)
            if (width, height) != (self.width, self.height):
                raise RuntimeError(
                    f"游戏窗口客户区由 {self.width}x{self.height} 变为 {width}x{height}，"
                    "请恢复窗口尺寸后重新运行任务"
                )
            # 先让窗口把待重绘内容画出来，再由 PrintWindow 取客户区画面
            self.user32.SendMessageW(self.hwnd, win32con.WM_PAINT, 0, 0)
            if not self.user32.PrintWindow(self.hwnd, self._mem_dc, _PRINTWINDOW_CLIENT):
                raise RuntimeError("后台截图失败：PrintWindow 没有返回画面")
            lines = self.gdi.GetDIBits(
                self._mem_dc, self._bitmap, 0, self.height,
                self.data, ctypes.byref(self._bmi), 0)
            if lines != self.height:
                raise RuntimeError(f"后台截图读取位图失败：读到 {lines}/{self.height} 行")
            return np.frombuffer(bytearray(self.data), dtype=np.uint8).reshape(
                (self.height, self.width, 4))[:, :, :3]

    def close(self):
        """释放 GDI 资源，可重复调用。"""
        with self.lock:
            if self._bitmap:
                self.gdi.DeleteObject(self._bitmap)
                self._bitmap = None
            if self._mem_dc:
                self.gdi.DeleteDC(self._mem_dc)
                self._mem_dc = None
            if self._window_dc:
                self.user32.ReleaseDC(self.hwnd, self._window_dc)
                self._window_dc = None


class WgcScreen:
    """后台截屏：复用录屏的 WGC 采集会话，识别时取最新一帧。

    采集会话常驻接收窗口画面，不再每帧整屏 BitBlt；窗口最小化或系统拒绝捕获时构造失败。

    Args:
        hwnd: 游戏窗口句柄。
        width: 客户区宽度，物理像素。
        height: 客户区高度，物理像素。
    """

    def __init__(self, hwnd, width, height):
        # 延迟导入：录屏依赖只在真正选择 WGC 截图时才需要
        from tool.window_recorder.wgc_capture import WgcCapture

        self.hwnd = hwnd
        self.width, self.height = width, height
        left, top, right, bottom = get_client_screen_rect(hwnd)
        # 采集节拍 0.05 秒：识别按需取帧，20fps 的新画面已经够用
        self.capture = WgcCapture(hwnd, (left, top, right, bottom), 0.05)
        try:
            self.capture.start()
        except Exception as error:
            raise RuntimeError(f"启动 WGC 窗口捕获失败：{error}") from error
        if (self.capture.width, self.capture.height) != (width, height):
            self.capture.stop()
            raise ValueError(
                f"窗口捕获尺寸 {self.capture.width}x{self.capture.height} "
                f"与客户区 {width}x{height} 不一致"
            )

    def grab(self, x=0, y=0):
        """取最近一帧客户区画面。"""
        frame = self.capture.read_latest()
        if frame.shape[:2] != (self.height, self.width):
            raise RuntimeError("窗口画面尺寸变化，请恢复窗口尺寸后重新运行任务")
        return frame

    def close(self):
        """停止采集会话，可重复调用。"""
        self.capture.stop()


def resolve_capture_backend(settings, background_mode):
    """解析截图后端：显式配置优先，否则前台整屏截屏、后台用 PrintWindow。

    Args:
        settings: 用户 GUI 配置，读取 capture_backend 字段。
        background_mode: 是否启用后台模式。

    Returns:
        CAPTURE_BACKENDS 之一。
    """
    backend = str(settings.get("capture_backend", "auto")).strip().lower()
    if backend in CAPTURE_BACKENDS:
        return backend
    return "printwindow" if background_mode else "screen"


def create_capture(backend, hwnd, width, height):
    """按后端名创建窗口截图对象；screen 后端由调用方直接创建 Screen。"""
    if backend == "printwindow":
        return PrintWindowCapture(hwnd, width, height)
    if backend == "wgc":
        return WgcScreen(hwnd, width, height)
    raise ValueError(f"未知的截图后端：{backend}")
