"""Shared Star Rail window discovery and validation helpers."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import dataclass

import win32con
import win32gui

from tool.utils.get_win_rect import get_window_rect

LOCAL_GAME_TITLE = "崩坏：星穹铁道"
CLOUD_GAME_TITLE = "云·星穹铁道"
LOCAL_GAME_CLASS = "UnityWndClass"
CLOUD_GAME_CLASS = "Chrome_WidgetWin_1"

LOCAL_WINDOW_KIND = "local"
CLOUD_WINDOW_KIND = "cloud"

BASE_WIDTH = 1920
BASE_HEIGHT = 1080
CLOUD_SIZE_TOLERANCE = 8


def set_process_dpi_awareness() -> bool:
    """将整个进程切换为 Per-Monitor V2 DPI 感知。

    必须在创建 QApplication、截图或注入键鼠之前调用，使高分辨率/高缩放
    系统下窗口几何、屏幕截图与键鼠坐标统一为物理像素。重复调用安全。
    """
    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
    setter = getattr(ctypes.windll.user32, "SetProcessDpiAwarenessContext", None)
    if setter is not None:
        setter.argtypes = (ctypes.c_void_p,)
        setter.restype = ctypes.c_int
        try:
            if setter(ctypes.c_void_p(-4)):
                return True
        except OSError:
            pass
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE == 2
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except OSError:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return True
    except OSError:
        pass
    return False


@contextmanager
def _physical_pixel_context():
    """Temporarily disable DPI virtualization for Win32 geometry calls."""
    setter = getattr(ctypes.windll.user32, "SetThreadDpiAwarenessContext", None)
    previous = None
    if setter is not None:
        setter.argtypes = (ctypes.c_void_p,)
        setter.restype = ctypes.c_void_p
        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
            previous = setter(ctypes.c_void_p(-4))
        except OSError:
            previous = None
    try:
        yield
    finally:
        if setter is not None and previous:
            try:
                setter(previous)
            except OSError:
                pass


def _get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    with _physical_pixel_context():
        return win32gui.GetClientRect(hwnd)


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    kind: str
    title: str
    class_name: str
    client_width: int
    client_height: int


@dataclass(frozen=True)
class CaptureGeometry:
    """游戏截图区域，屏幕坐标与宽高均为物理像素。"""

    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    full: bool

    @property
    def scale_x(self) -> float:
        return self.width / BASE_WIDTH

    @property
    def scale_y(self) -> float:
        return self.height / BASE_HEIGHT


def get_window_kind(hwnd: int) -> str | None:
    """Return ``local``/``cloud`` only for real game host windows.

    Matching the class is intentional: Windows 11 creates an Explorer-owned
    ``Windows.Internal.Shell.TabProxyWindow`` with the exact cloud-game title.
    Its client area can be 152x0 and must never be treated as the game.
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    title = win32gui.GetWindowText(hwnd)
    class_name = win32gui.GetClassName(hwnd)
    if class_name == LOCAL_GAME_CLASS and title == LOCAL_GAME_TITLE:
        return LOCAL_WINDOW_KIND
    if class_name == CLOUD_GAME_CLASS and title.startswith(CLOUD_GAME_TITLE):
        return CLOUD_WINDOW_KIND
    return None


def is_usable_game_window(hwnd: int) -> bool:
    if get_window_kind(hwnd) is None:
        return False
    if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
        return False
    left, top, right, bottom = _get_client_rect(hwnd)
    return right > left and bottom > top


def inspect_game_window(hwnd: int) -> GameWindow | None:
    kind = get_window_kind(hwnd)
    if kind is None:
        return None
    left, top, right, bottom = _get_client_rect(hwnd)
    return GameWindow(
        hwnd=hwnd,
        kind=kind,
        title=win32gui.GetWindowText(hwnd),
        class_name=win32gui.GetClassName(hwnd),
        client_width=max(0, right - left),
        client_height=max(0, bottom - top),
    )


def is_supported_resolution(kind: str, width: int, height: int) -> bool:
    """本地支持 1080p 与 3840×2160；云游戏保留原有边框容差。"""
    if kind == LOCAL_WINDOW_KIND:
        return (width, height) in ((BASE_WIDTH, BASE_HEIGHT), (3840, 2160))
    if kind == CLOUD_WINDOW_KIND:
        return (
            abs(width - BASE_WIDTH) <= CLOUD_SIZE_TOLERANCE
            and abs(height - BASE_HEIGHT) <= CLOUD_SIZE_TOLERANCE
        )
    return False


def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return the client rectangle in physical screen coordinates."""
    with _physical_pixel_context():
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
    return screen_left, screen_top, screen_right, screen_bottom


def get_capture_geometry(window: GameWindow) -> CaptureGeometry | None:
    """确定本地或云游戏的物理截图区域，无法适配时返回 None。

    本地 3840×2160 先校验真实客户区，再缩回 1920×1080 识别；原有单轴为
    1080p 的超宽/超高窗口继续居中裁剪。云游戏允许小幅浏览器边框差异，
    仍从客户区左上角截取 1920×1080。
    """
    width, height = window.client_width, window.client_height
    if window.kind == CLOUD_WINDOW_KIND:
        left, top, _, _ = get_client_screen_rect(window.hwnd)
        if not is_supported_resolution(window.kind, width, height):
            return None
        return CaptureGeometry(
            left, top, left + BASE_WIDTH, top + BASE_HEIGHT,
            BASE_WIDTH, BASE_HEIGHT, left == 0 and top == 0,
        )

    if window.kind != LOCAL_WINDOW_KIND:
        return None
    rect = get_window_rect(window.hwnd)
    if rect is None:
        return None
    frame_left, frame_top, right, bottom = rect
    if right - frame_left < width or bottom - frame_top < height:
        return None
    full = frame_left == 0 and frame_top == 0
    left, top = right - width, bottom - height

    # 沿用单轴等于基准尺寸时的居中裁剪规则。
    if (width == BASE_WIDTH or height == BASE_HEIGHT) and width >= BASE_WIDTH and height >= BASE_HEIGHT:
        left += (width - BASE_WIDTH) // 2
        top += (height - BASE_HEIGHT) // 2
        width, height = BASE_WIDTH, BASE_HEIGHT
        right, bottom = left + width, top + height

    if not is_supported_resolution(window.kind, width, height):
        return None
    return CaptureGeometry(left, top, right, bottom, width, height, full)


def _candidate_score(window: GameWindow, z_order: int) -> tuple[int, int, int]:
    supported = int(
        is_supported_resolution(
            window.kind,
            window.client_width,
            window.client_height,
        )
    )
    area = window.client_width * window.client_height
    return supported, area, -z_order


def find_game_window(prefer_foreground: bool = True) -> GameWindow | None:
    """Find the real local or cloud game host, excluding shell proxy windows."""
    if prefer_foreground:
        foreground = win32gui.GetForegroundWindow()
        if is_usable_game_window(foreground):
            return inspect_game_window(foreground)

    candidates: list[GameWindow] = []

    def callback(hwnd: int, _extra: object) -> bool:
        if is_usable_game_window(hwnd):
            window = inspect_game_window(hwnd)
            if window is not None:
                candidates.append(window)
        return True

    win32gui.EnumWindows(callback, None)
    if not candidates:
        return None
    return max(
        enumerate(candidates),
        key=lambda item: _candidate_score(item[1], item[0]),
    )[1]


def set_game_foreground() -> GameWindow | None:
    window = find_game_window(prefer_foreground=True)
    if window is None:
        return None
    try:
        if win32gui.IsIconic(window.hwnd):
            win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(window.hwnd)
    except Exception:
        # Windows can deny focus stealing. The caller will keep waiting until
        # the user activates the selected game window.
        pass
    return window


def get_foreground_game_window() -> GameWindow | None:
    hwnd = win32gui.GetForegroundWindow()
    if not is_usable_game_window(hwnd):
        return None
    return inspect_game_window(hwnd)


def canonical_game_title(hwnd: int) -> str | None:
    kind = get_window_kind(hwnd)
    if kind == LOCAL_WINDOW_KIND:
        return LOCAL_GAME_TITLE
    if kind == CLOUD_WINDOW_KIND:
        return CLOUD_GAME_TITLE
    return None


def validate_capture_geometry(hwnd: int, client_size: tuple[int, int], geometry: CaptureGeometry) -> None:
    """拒绝失焦、窗口移动或尺寸变化，防止旧截图与点击区域继续使用。"""
    window = get_foreground_game_window()
    if (window is None or window.hwnd != hwnd or
            (window.client_width, window.client_height) != client_size):
        raise RuntimeError("游戏窗口已失去前台或尺寸发生变化，停止自动操作")
    if get_capture_geometry(window) != geometry:
        raise RuntimeError("游戏窗口位置或截图区域发生变化，停止自动操作")
