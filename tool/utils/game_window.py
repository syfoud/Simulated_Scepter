"""Shared Star Rail window discovery and validation helpers."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import dataclass

import win32con
import win32gui

LOCAL_GAME_TITLE = "崩坏：星穹铁道"
CLOUD_GAME_TITLE = "云·星穹铁道"
LOCAL_GAME_CLASS = "UnityWndClass"
CLOUD_GAME_CLASS = "Chrome_WidgetWin_1"

LOCAL_WINDOW_KIND = "local"
CLOUD_WINDOW_KIND = "cloud"

BASE_WIDTH = 1920
BASE_HEIGHT = 1080
CLOUD_SIZE_TOLERANCE = 8


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
    """Validate local strictly and cloud with a small browser-frame tolerance."""
    if kind == LOCAL_WINDOW_KIND:
        return width == BASE_WIDTH and height == BASE_HEIGHT
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
