"""后台输入通道：把按键/鼠标消息直接投递给游戏窗口，不需要游戏处于前台。

两个通道的实现边界不一样，分开表达：

- `BackgroundKeyboard`：纯消息，完全不用真实光标，也不需要激活以外的副作用；
  操作前补一条伪造的 WM_ACTIVATE。
- `BackgroundMouse`：消息投递给窗口，但**落点仍依赖真实光标** —— 实测只发
  WM_MOUSEMOVE/LBUTTONDOWN 而不移动光标时游戏不响应；先把光标挪到目标再发消息才生效。
  所以每次点击/拖动会短暂借用光标，结束后归还（用户中途动过鼠标就不硬拽）。

滚轮和相对转视角不走后台：滚轮需要真实焦点，转视角是相对鼠标，消息无法伪造。
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


class WindowActivation:
    """伪造 / 撤销游戏窗口的激活状态。

    后台通道投递的键鼠消息，游戏只有在「自认为激活」时才会处理；窗口被别的程序盖住后
    它会认为自己是失活状态，消息就石沉大海。所以操作前补一条 WM_ACTIVATE(1)，
    任务结束再补 WM_ACTIVATE(0)；窗口本来就是前台时不伪造，避免干扰真实焦点。

    键盘和鼠标**必须共用同一个实例**：各持一份的话，键盘抬键撤销激活后鼠标还以为自己是激活的，
    紧接着的点击就会被丢弃。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.activated = False
        self.previous_foreground = 0

    def game_is_foreground(self):
        """游戏窗口当前是否为前台窗口。"""
        return win32gui.GetForegroundWindow() == self.hwnd

    def activate(self, force=False):
        """让游戏窗口认为自己是激活状态。

        Args:
            force: 即使已经记过"已激活"也重新发一次。鼠标通道必须用 force——
                用户中途切过窗口后，游戏其实已经失活，但缓存还写着 True，
                不重发的话投递的点击会被直接丢掉（正是"点了没反应"的现场）。
        """
        if self.activated and not force:
            return
        current = win32gui.GetForegroundWindow()
        if current == self.hwnd:
            self.activated = True
            return
        if not self.previous_foreground:
            self.previous_foreground = current
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

    def __init__(self, hwnd, activation=None):
        self.hwnd = hwnd
        # 激活状态由调用方注入，键盘和鼠标必须是同一个实例：
        # 两份各自记账会互相拆台（键盘抬起时撤销激活，鼠标却以为自己还是激活的）
        self.activation = activation or WindowActivation(hwnd)
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
        """抬起一个键。

        这里**不撤销激活**：撤销了会让共用同一份激活状态的鼠标通道漏掉激活
        （键盘一次按键 → 窗口失活 → 紧接着的点击被丢弃）。激活在任务结束统一释放。
        """
        info = _key_info(key)
        self._post_key(key, info, key_up=True)
        self.held.discard(key)

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


_warned = set()
# 排查「点了没反应」时打开：每次点击都记录落点、激活状态与消息送达结果
_VERBOSE_CLICK = True


def _warn_once(key, message):
    """同一类告警只记一次，避免长跑时刷屏。"""
    if key in _warned:
        return
    _warned.add(key)
    CUS_LOGGER.warning(message)


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

    借用光标的流程（点击约 200ms：等空闲 + 激活稳定 120ms + 消息往返；拖动按 duration 更长）：

    1. 等真实光标空闲（用户正在动鼠标时先等一等，避免抢走他正在用的光标）；
    2. 记住原位置，把光标挪到目标点；
    3. 向窗口投递 WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP（拖动是连续 MOVE）；
    4. 把光标放回原处。

    因此**焦点可以留在别的窗口**，但用户的鼠标会被短暂借用，这是 Unity 只认系统光标
    位置决定的，绕不过去。
    """

    MOVE_STEPS_PER_SECOND = 60
    # 伪造激活后等一下再发鼠标消息：游戏处理焦点变化需要一点时间，
    # 立刻点会被丢掉（实测表现为“偶尔点得动、多数点不动”）
    ACTIVATE_SETTLE = 0.12
    IDLE_TOLERANCE = 3        # 像素：小于这个位移认为光标是静止的
    IDLE_TIMEOUT = 0.4        # 秒：等用户停手最多等这么久（等不到也照常点）

    def __init__(self, hwnd, activation=None):
        self.hwnd = hwnd
        self.activation = activation or WindowActivation(hwnd)

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
        if not self.wait_cursor_idle():
            # 光标一直在动（可能是用户，也可能是游戏自己抓着光标）：
            # 不能因此整个跳过，否则就成了"后台点击全部被跳过"、什么界面都推不动
            _warn_once("后台鼠标:忙", "光标一直有动作，仍按落点点击（可能打断用户的鼠标操作）")
        original = win32api.GetCursorPos()
        self.activation.activate(force=True)
        try:
            # 激活刚发出去时游戏还没处理完焦点变化，立刻点会被丢掉
            sleep(self.ACTIVATE_SETTLE)
            target = (int(screen_point[0]), int(screen_point[1]))
            win32api.SetCursorPos(target)
            client = self.to_client(screen_point)
            self._post(WM_MOUSEMOVE, 0, client)
            # 发按下消息前再对齐一次光标：游戏按真实光标位置判定落点，
            # 用户在这几十毫秒里挪了鼠标就会点歪
            actual = win32api.GetCursorPos()
            if (abs(actual[0] - target[0]) > self.IDLE_TOLERANCE
                    or abs(actual[1] - target[1]) > self.IDLE_TOLERANCE):
                _warn_once("后台鼠标:被挪开", "点击前光标被移开（用户正在操作鼠标），本次点击可能落空")
                win32api.SetCursorPos(target)
            handled = self._post(WM_LBUTTONDOWN, MK_LBUTTON, client)
            if _VERBOSE_CLICK:
                CUS_LOGGER.info(
                    "后台点击落点 client=%s 屏幕=%s 激活=%s 送达=%s",
                    client, target, self.activation.activated, handled)
            sleep(0.05)
            self._post(WM_LBUTTONUP, 0, client)
            return True
        finally:
            self._restore_cursor(original, screen_point)
            # 成对撤销：只发不撤会让游戏处于半激活状态，
            # 连用户自己的真实点击都会被它忽略（实机复现过）
            self.activation.deactivate()

    def drag(self, start, end, duration=0.4, sleep=time.sleep):
        """从 start 拖到 end（屏幕坐标）；按 60Hz 步进投递移动消息。"""
        self.wait_cursor_idle()
        original = win32api.GetCursorPos()
        steps = max(8, int(duration * self.MOVE_STEPS_PER_SECOND))
        step_sleep = duration / steps
        self.activation.activate()
        try:
            sleep(self.ACTIVATE_SETTLE)
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
            return True
        finally:
            self._restore_cursor(original, end)
            self.activation.deactivate()

    def _restore_cursor(self, original, expected):
        """把光标放回原处；用户中途动过鼠标就不硬拽（那样会把他的操作打断）。"""
        current = win32api.GetCursorPos()
        if (abs(current[0] - int(expected[0])) <= self.IDLE_TOLERANCE
                and abs(current[1] - int(expected[1])) <= self.IDLE_TOLERANCE):
            win32api.SetCursorPos(original)

    def release(self):
        """任务结束时撤销伪造激活，把焦点还给用户原来的窗口。"""
        self.activation.deactivate()

    def _post(self, message, wparam, client):
        """带超时地投递一条鼠标消息；窗口卡住时放弃这一条，不让线程挂死。"""
        try:
            handled = win32gui.SendMessageTimeout(
                self.hwnd, message, wparam, _lparam(client),
                SMTO_BLOCK | SMTO_ABORTIFHUNG, 500,
            )
        except Exception as error:
            CUS_LOGGER.warning("后台鼠标消息 %s 投递失败：%s", hex(message), error)
            return
        if not handled:
            # 超时/目标无响应时 SendMessageTimeout 返回 0 且不抛异常，
            # 不记一笔的话，现场就只剩「日志显示点了、游戏没反应」
            _warn_once(f"后台鼠标超时:{message}",
                       f"后台鼠标消息 {hex(message)} 超时未处理（窗口可能卡住）")
