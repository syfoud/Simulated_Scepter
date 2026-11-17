"""后台输入通道：把按键/鼠标消息直接投递给游戏窗口，不需要游戏处于前台。

两个通道的实现边界不一样，分开表达：

- `BackgroundKeyboard`：纯消息，完全不用真实光标，也不需要激活以外的副作用；
  操作前补一条伪造的 WM_ACTIVATE。
- `BackgroundMouse`：消息投递给窗口，但**落点仍依赖真实光标** —— 实测（见
  `temp/` 下的 PoC）只发 WM_MOUSEMOVE/LBUTTONDOWN 而不移动光标，游戏不响应；
  先把光标挪到目标再发消息才生效。所以每次点击/拖动会短暂借用光标，结束后归还。

滚轮和相对转视角不走后台：滚轮需要真实焦点，转视角是相对鼠标，消息无法伪造。
"""

import ctypes
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


class WindowActivation:
    """伪造 / 撤销游戏窗口的激活状态。

    后台通道投递的键鼠消息，游戏只有在「自认为激活」时才会处理；窗口被别的程序盖住后
    它会认为自己是失活状态，消息就石沉大海。所以每批操作前补一条 WM_ACTIVATE(1)，
    结束后补 WM_ACTIVATE(0)；窗口本来就是前台时不伪造，避免干扰真实焦点。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.activated = False
        self.previous_foreground = 0

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
        try:
            win32gui.PostMessage(self.hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        except Exception as error:      # 窗口已关闭 / 句柄失效
            CUS_LOGGER.warning("伪造激活失败（窗口可能已关闭）：%s", error)
            return
        self.activated = True

    def deactivate(self):
        """撤销伪造激活；游戏借机抢到前台时把焦点还原到原来的窗口。"""
        if not self.activated:
            return
        try:
            win32gui.PostMessage(self.hwnd, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, 0)
        except Exception as error:
            CUS_LOGGER.warning("撤销伪造激活失败：%s", error)
        self.activated = False
        if self.previous_foreground and self.game_is_foreground():
            try:
                win32gui.SetForegroundWindow(self.previous_foreground)
            except Exception as error:  # 系统可能拒绝后台进程切换前台窗口
                CUS_LOGGER.warning("后台操作结束后游戏仍在前台，恢复原窗口失败：%s", error)


class BackgroundKeyboard:
    """向游戏窗口投递键盘消息的后台输入通道。

    Args:
        hwnd: 游戏窗口句柄。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.activation = WindowActivation(hwnd)
        # 当前仍处于按下状态的键名
        self.held = set()

    @property
    def activated(self):
        """是否已经给游戏发过伪造激活（兼容旧调用方的直接读取）。"""
        return self.activation.activated

    @property
    def previous_foreground(self):
        """伪造激活前的前台窗口句柄。"""
        return self.activation.previous_foreground

    @staticmethod
    def supports(key):
        """判断后台通道是否支持该物理键名。"""
        return key in _KEYS

    def game_is_foreground(self):
        """游戏窗口当前是否为前台窗口。"""
        return self.activation.game_is_foreground()

    def activate(self):
        """让游戏窗口认为自己是激活状态。"""
        self.activation.activate()

    def deactivate(self):
        """撤销伪造激活，必要时把焦点还原。"""
        self.activation.deactivate()

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


SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


def _lparam(point):
    """把客户区坐标打包成鼠标消息的 lParam。"""
    return (int(point[1]) << 16) | (int(point[0]) & 0xFFFF)


class BackgroundMouse:
    """后台鼠标：消息投给游戏窗口，落点借用真实光标。

    借用光标的流程（每次操作约 70~100ms，拖动按 duration 更长）：

    1. 等真实光标空闲（用户正在动鼠标时先等一等，避免抢走他正在用的光标）；
    2. 记住原位置，把光标挪到目标点；
    3. 向窗口投递 WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP（拖动是连续 MOVE）；
    4. 把光标放回原处。

    因此**焦点可以留在别的窗口**，但用户的鼠标会被短暂借用，这是 Unity 只认系统光标
    位置决定的，绕不过去。
    """

    MOVE_STEPS_PER_SECOND = 60
    IDLE_TOLERANCE = 3        # 像素：小于这个位移认为光标是静止的
    IDLE_TIMEOUT = 1.5        # 秒：等用户停手最多等这么久

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.activation = WindowActivation(hwnd)

    def game_is_foreground(self):
        """游戏窗口当前是否为前台窗口。"""
        return self.activation.game_is_foreground()

    def client_origin(self):
        """客户区左上角在屏幕上的坐标。"""
        return win32gui.ClientToScreen(self.hwnd, (0, 0))

    def to_client(self, screen_point):
        """屏幕坐标 → 客户区坐标（消息里用的是客户区坐标）。"""
        left, top = self.client_origin()
        return int(screen_point[0]) - left, int(screen_point[1]) - top

    def wait_cursor_idle(self, timeout=None):
        """等真实光标停下来，避免把用户正在操作的鼠标抢走。"""
        timeout = self.IDLE_TIMEOUT if timeout is None else timeout
        start = win32api.GetCursorPos()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.03)
            current = win32api.GetCursorPos()
            if (abs(current[0] - start[0]) <= self.IDLE_TOLERANCE
                    and abs(current[1] - start[1]) <= self.IDLE_TOLERANCE):
                return True
            start = current
        return False

    def click(self, screen_point, sleep=time.sleep):
        """在屏幕坐标处点一下（借用光标后归还）。"""
        self.wait_cursor_idle()
        original = win32api.GetCursorPos()
        self.activation.activate()
        try:
            win32api.SetCursorPos((int(screen_point[0]), int(screen_point[1])))
            sleep(0.02)
            client = self.to_client(screen_point)
            self._post(WM_MOUSEMOVE, 0, client)
            self._post(WM_LBUTTONDOWN, MK_LBUTTON, client)
            sleep(0.05)
            self._post(WM_LBUTTONUP, 0, client)
        finally:
            win32api.SetCursorPos(original)
            self.activation.deactivate()

    def drag(self, start, end, duration=0.4, sleep=time.sleep):
        """从 start 拖到 end（屏幕坐标）；按 60Hz 步进投递移动消息。"""
        self.wait_cursor_idle()
        original = win32api.GetCursorPos()
        steps = max(8, int(duration * self.MOVE_STEPS_PER_SECOND))
        step_sleep = duration / steps
        self.activation.activate()
        try:
            win32api.SetCursorPos((int(start[0]), int(start[1])))
            sleep(0.08)
            client = self.to_client(start)
            self._post(WM_MOUSEMOVE, 0, client)
            self._post(WM_LBUTTONDOWN, MK_LBUTTON, client)
            for index in range(1, steps + 1):
                ratio = index / steps
                point = (int(start[0] + (end[0] - start[0]) * ratio),
                         int(start[1] + (end[1] - start[1]) * ratio))
                win32api.SetCursorPos(point)
                self._post(WM_MOUSEMOVE, MK_LBUTTON, self.to_client(point))
                sleep(step_sleep)
            self._post(WM_LBUTTONUP, 0, self.to_client(end))
        finally:
            win32api.SetCursorPos(original)
            self.activation.deactivate()

    def _post(self, message, wparam, client):
        """带超时地投递一条鼠标消息；窗口卡住时放弃这一条，不让线程挂死。"""
        try:
            win32gui.SendMessageTimeout(
                self.hwnd, message, wparam, _lparam(client),
                SMTO_BLOCK | SMTO_ABORTIFHUNG, 500,
            )
        except Exception as error:
            CUS_LOGGER.warning("后台鼠标消息 %s 投递失败：%s", hex(message), error)
