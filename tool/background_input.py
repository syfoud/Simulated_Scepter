"""后台键盘输入：把按键消息直接投递给游戏窗口，不需要游戏处于前台。

鼠标、滚轮和转视角仍走前台实现（需要真实光标），本模块目前只提供键盘通道。
操作前给游戏补一条伪造的 WM_ACTIVATE，让它认为自己是激活状态；窗口本来就是前台时
不发伪造激活，避免干扰真实的焦点状态。
"""

import time

import win32api
import win32con
import win32gui

from tool.log import CUS_LOGGER

# 后台键盘支持的物理键名 -> (虚拟键码, 是否扩展键)
# 只收录游戏键位和固定键里实际会用到的键；不在表里的键由调用方跳过并记录一次警告。
_KEYS = {
    "space": (0x20, False),
    "enter": (0x0D, False),
    "return": (0x0D, False),
    "esc": (0x1B, False),
    "escape": (0x1B, False),
    "tab": (0x09, False),
    "backspace": (0x08, False),
    "shiftleft": (0x10, False),
    "shiftright": (0x10, False),
    "ctrlleft": (0x11, False),
    "ctrlright": (0x11, True),
    "altleft": (0x12, False),
    "altright": (0x12, True),
}
for _index in range(26):
    _KEYS[chr(ord("a") + _index)] = (0x41 + _index, False)
for _index in range(10):
    _KEYS[str(_index)] = (0x30 + _index, False)
for _index in range(12):
    _KEYS[f"f{_index + 1}"] = (0x70 + _index, False)


def _key_info(key):
    """返回物理键名对应的 (虚拟键码, 是否扩展键)；不支持的键抛出 ValueError。"""
    try:
        return _KEYS[key]
    except KeyError:
        raise ValueError(f"后台键盘不支持按键 {key!r}") from None


def scan_code(vk):
    """虚拟键码对应的扫描码；取不到时返回 0（个别扩展键只认虚拟键码）。"""
    return win32api.MapVirtualKey(vk, 0)


def key_lparam(scan, extended, key_up, sys_key=False):
    """拼出 WM_KEYDOWN/UP 的 lParam。

    Args:
        scan: 扫描码。
        extended: 是否为扩展键（右 Ctrl/Alt 等）。
        key_up: True 表示抬起消息。
        sys_key: 是否为 WM_SYSKEY*（Alt 组合）。

    Returns:
        lParam 整数值：重复次数 1、扫描码、扩展位、上下文位与抬起标志。
    """
    lparam = 1 | (scan << 16)
    if extended:
        lparam |= 1 << 24
    if sys_key:
        lparam |= 1 << 29
    if key_up:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


class BackgroundKeyboard:
    """向游戏窗口投递键盘消息的后台输入通道。

    Args:
        hwnd: 游戏窗口句柄。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        # 是否已经给游戏发过伪造激活；窗口本来就是前台时保持 False
        self.activated = False
        # 伪造激活前的前台窗口，用于发现游戏借机抢到前台时还原
        self.previous_foreground = 0
        # 当前仍处于按下状态的键名
        self.held = set()

    @staticmethod
    def supports(key):
        """判断后台通道是否支持该物理键名。"""
        return key in _KEYS

    def game_is_foreground(self):
        """游戏窗口当前是否为前台窗口。"""
        return win32gui.GetForegroundWindow() == self.hwnd

    def activate(self):
        """让游戏窗口认为自己是激活状态；窗口本来就是前台时不伪造激活。"""
        if self.activated:
            return
        self.previous_foreground = win32gui.GetForegroundWindow()
        if self.previous_foreground == self.hwnd:
            return
        win32gui.PostMessage(self.hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        self.activated = True

    def deactivate(self):
        """撤销伪造激活；游戏借机抢到前台时把焦点还原到原来的窗口。"""
        if not self.activated:
            return
        win32gui.PostMessage(self.hwnd, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, 0)
        self.activated = False
        if self.previous_foreground and self.game_is_foreground():
            try:
                win32gui.SetForegroundWindow(self.previous_foreground)
            except Exception as error:  # 系统可能拒绝后台进程切换前台窗口
                CUS_LOGGER.warning("后台按键结束后游戏仍在前台，恢复原窗口失败：%s", error)

    def key_down(self, key):
        """按下一个键（保持按下，直到 key_up 或 release_all）。"""
        info = _key_info(key)
        self.activate()
        self._post_key(key, info, key_up=False)
        self.held.add(key)

    def key_up(self, key):
        """抬起一个键；没有其它键按下时撤销伪造激活。"""
        info = _key_info(key)
        self._post_key(key, info, key_up=True)
        self.held.discard(key)
        if not self.held:
            self.deactivate()

    def press(self, key, duration=0, sleep=time.sleep):
        """按下并抬起一个键，duration 秒内保持按下。"""
        self.key_down(key)
        try:
            if duration > 0:
                sleep(duration)
        finally:
            if key in self.held:
                self.key_up(key)

    def release_all(self):
        """抬起所有仍按下的键并撤销伪造激活，可重复调用。"""
        for key in list(self.held):
            try:
                self.key_up(key)
            except Exception as error:
                CUS_LOGGER.warning("释放后台按键 %s 失败：%s", key, error)
                self.held.discard(key)
        self.deactivate()

    def _post_key(self, key, info, key_up):
        """把单个按键消息投递给游戏窗口。"""
        vk, extended = info
        sys_key = key.startswith("alt")
        if sys_key:
            message = win32con.WM_SYSKEYUP if key_up else win32con.WM_SYSKEYDOWN
        else:
            message = win32con.WM_KEYUP if key_up else win32con.WM_KEYDOWN
        win32gui.PostMessage(
            self.hwnd,
            message,
            vk,
            key_lparam(scan_code(vk), extended, key_up, sys_key),
        )
