"""用 Windows Graphics Capture 持续接收目标窗口的画面。

系统在窗口内容更新时把画面送进回调，采集因此不再依赖整屏截图：Pillow 的
`ImageGrab` 每次都把整个桌面读进内存再裁剪，单帧要 70~90ms，慢的正是这一步。
回调里只做一次裁剪拷贝，录制线程按自己的节拍取走最新一帧即可。
"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes

import numpy as np
from windows_capture import WindowsCapture

from tool.log import CUS_LOGGER


def get_visible_rect(hwnd):
    """读取窗口可见区域的屏幕坐标。

    Args:
        hwnd: 目标窗口句柄。

    Returns:
        (left, top, right, bottom) 屏幕坐标。Graphics Capture 送来的帧正好覆盖这块
        矩形，录制区域要减去该原点才能换算成帧内坐标。

    Raises:
        ValueError: 系统没有返回窗口可见区域（窗口已销毁或系统不支持该属性）。
    """
    rect = (ctypes.c_long * 4)()
    # 9 = DWMWA_EXTENDED_FRAME_BOUNDS：窗口可见区域，不含四周用于拖拽的不可见边框。
    # GetWindowRect 会把那圈不可见边框算进去，和实际画面差几个像素。
    hresult = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        9,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if hresult != 0:
        raise ValueError(f"读取窗口可见区域失败: hresult={hresult}")
    return rect[0], rect[1], rect[2], rect[3]


class WgcCapture:
    """持续采集目标窗口画面，对外只暴露最新一帧与停止接口。

    应在启动后先用 `start()` 等到首帧，再读取 `width`/`height` 建立编码器；
    这两个尺寸来自实际画面，已按编码器要求取偶。

    Args:
        hwnd: 目标窗口句柄。
        region: 录制区域的屏幕坐标 (left, top, right, bottom)。
        interval: 录制线程取帧的间隔（秒）。回调按它的一半限速：比取帧更密的画面
            用不上，全部拷贝只是白占 CPU。
    """

    def __init__(self, hwnd, region, interval):
        self._hwnd = hwnd
        self._region = region
        self._interval = interval
        self._lock = threading.Lock()
        self._latest = None
        # 最近一次已被读走的画面；取帧方需要“没有新画面时沿用上一帧”时读它
        self._last_frame = None
        self._copied_at = 0.0
        self._closed = False
        self._control = None
        self._visible_left = 0
        self._visible_top = 0
        self._frame_shape = None
        self._crop = None
        self._shape_warned = False
        self.width = 0
        self.height = 0

    def start(self):
        """开始接收画面，并等到第一帧。

        Raises:
            ValueError: 超时前没有收到画面，或捕获会话被系统关闭。
        """
        self._visible_left, self._visible_top, _, _ = get_visible_rect(self._hwnd)
        capture = WindowsCapture(
            # 鼠标光标不是录像内容
            cursor_capture=False,
            # 无捕获边框需要 GraphicsCaptureSession.IsBorderRequired，该系统属性从
            # Windows 10.0.20348 起才有；更早的系统请求它会让采集会话直接创建失败，
            # 只能退回默认（由系统画边框，边框只在屏幕上，不进录像画面）
            draw_border=False if sys.getwindowsversion().build >= 20348 else None,
            window_hwnd=self._hwnd,
        )
        # 绑定按处理函数的名字分派事件，这两个名字是它与本模块的约定
        capture.event(self.on_frame_arrived)
        capture.event(self.on_closed)
        try:
            self._control = capture.start_free_threaded()
            self._wait_first_frame()
        except Exception:
            self.stop()
            raise

    def read(self):
        """取走最新一帧画面，交给调用方独占使用。

        Returns:
            height x width x 3 的 BGR 数组。

        Raises:
            ValueError: 尚未收到任何画面（捕获会话已关闭或从未开始）。
        """
        with self._lock:
            latest = self._latest
            self._latest = None
        if latest is None:
            raise ValueError("尚未收到窗口画面")
        return latest

    def read_latest(self):
        """取最近一帧画面；没有新画面时返回上一次读到的画面。

        录制要判重，读不到新帧算异常；识别只需要“当前画面”，可以沿用上一帧。

        Returns:
            height x width x 3 的 BGR 数组。

        Raises:
            ValueError: 尚未收到任何画面（捕获会话已关闭或从未开始）。
        """
        with self._lock:
            if self._latest is not None:
                self._last_frame = self._latest
                self._latest = None
            latest = self._last_frame
        if latest is None:
            raise ValueError("尚未收到窗口画面")
        return latest

    def stop(self):
        """停止捕获会话，可重复调用。"""
        with self._lock:
            control = self._control
            self._control = None
            self._closed = True
        if control is None:
            return
        control.stop()
        control.wait()

    def on_frame_arrived(self, frame, _control):
        """接收一帧画面，由捕获线程调用。"""
        if self._closed:
            return
        now = time.monotonic()
        if now - self._copied_at < self._interval / 2:
            return
        pixels = frame.frame_buffer
        shape = pixels.shape[:2]
        if self._frame_shape is None:
            self._frame_shape = shape
            self._crop = self._resolve_crop(shape)
            self.width = self._crop[2] - self._crop[0]
            self.height = self._crop[3] - self._crop[1]
        elif shape != self._frame_shape:
            if not self._shape_warned:
                self._shape_warned = True
                CUS_LOGGER.warning(
                    f"窗口画面尺寸由 {self._frame_shape} 变为 {shape}，"
                    "录制区域无法跟随，跳过后面的画面"
                )
            return
        left, top, right, bottom = self._crop
        # 帧缓冲在回调返回后即失效，必须拷贝出来；第 4 通道是 alpha，丢掉就是 BGR
        with self._lock:
            self._latest = np.ascontiguousarray(pixels[top:bottom, left:right, :3])
        self._copied_at = now

    def on_closed(self):
        """捕获会话结束（窗口关闭或被系统终止）时由捕获线程调用。"""
        self._closed = True

    def _wait_first_frame(self):
        """等到第一帧画面，明确窗口不可见时要尽快失败。"""
        # 窗口最小化或捕获被系统拒绝时永远等不到画面，必须有上限
        deadline = time.monotonic() + 5.0
        while True:
            with self._lock:
                ready = self._latest is not None
            if ready:
                return
            if self._closed:
                raise ValueError("窗口捕获会话已关闭，无法录制")
            if time.monotonic() > deadline:
                raise ValueError("等待窗口画面超时（5 秒）：目标窗口可能已最小化或不可见")
            time.sleep(0.02)

    def _resolve_crop(self, frame_shape):
        """把屏幕坐标的录制区域换算成帧内坐标，并裁成编码器要求的偶数宽高。

        Args:
            frame_shape: 画面尺寸 (height, width)。

        Returns:
            (left, top, right, bottom) 帧内坐标。

        Raises:
            ValueError: 录制区域与窗口画面没有交集。
        """
        frame_height, frame_width = frame_shape
        left, top, right, bottom = self._region
        # 录制区域可能伸到窗口可见区域之外（偏移量按旧的整窗矩形调过），钳进画面内
        crop_left = min(max(left - self._visible_left, 0), frame_width)
        crop_top = min(max(top - self._visible_top, 0), frame_height)
        crop_right = min(max(right - self._visible_left, 0), frame_width)
        crop_bottom = min(max(bottom - self._visible_top, 0), frame_height)
        # yuv420p 要求偶数宽高；150% 缩放下客户端区域可能是奇数
        crop_right -= (crop_right - crop_left) % 2
        crop_bottom -= (crop_bottom - crop_top) % 2
        if crop_right <= crop_left or crop_bottom <= crop_top:
            raise ValueError(
                f"录像区域无效: {crop_right - crop_left}x{crop_bottom - crop_top}"
            )
        return crop_left, crop_top, crop_right, crop_bottom
