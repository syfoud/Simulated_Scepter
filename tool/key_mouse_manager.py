import threading
import time
from collections import deque

import pyautogui
import win32api
import win32con

from tool.log import CUS_LOGGER
from tool.thread import ThreadWithException

# 程序目前仅支持 1920x1080 这一种游戏分辨率；
# 云游戏窗口因浏览器边框允许 8px 误差，内部分辨率同样是 1920x1080；
# 代码里写死的坐标、日志里打印的坐标统一用像素坐标：
# 原点在客户区左上角，x 向右、y 向下。
# 客户区左上角的屏幕坐标由右、下边界减客户区尺寸反推：各机器标题栏高度不同，
# 客户区上边界会漂，而右下角始终紧贴窗口右下角，从右下角反推才不会偏。


# 游戏内键位配置的来源：user/gui_settings.json 的 game_keys 字段，
# 默认值在 resource/gui_settings_default.json，形如 {"interact": "f", "move_w": "w", ...}。
# 调用点一律传"逻辑键名"（如 "interact"、"move_w"），由 resolve_key 换成用户设置的物理键，
# 这样键位改动只影响本文件，不需要改任何调用点。
_GAME_KEYS = {}
_DEFAULT_KEYS = {}
_DEFAULT_KEY_TO_NAME = {}
_game_keys_loaded = False
_warned_keys = set()

# 游戏内允许设置的键位范围：字母、数字、F1-F12、空格、Enter、左右 Ctrl/Shift/Alt。
# 与设置界面里的校验规则保持一致。
_ALLOWED_KEY_NAMES = (
    set("abcdefghijklmnopqrstuvwxyz")
    | set("0123456789")
    | {f"f{i}" for i in range(1, 13)}
    | {"space", "enter", "ctrlleft", "ctrlright", "shiftleft", "shiftright", "altleft", "altright"}
)

# 游戏界面上的写法（LeftShift/LeftAlt）与 pyautogui 的键名（shiftleft/altleft）不一致，
# 裸修饰键也统一成"左"，便于配置比较与去重判断。
_KEY_NAME_ALIASES = {
    "leftshift": "shiftleft", "rightshift": "shiftright",
    "leftctrl": "ctrlleft", "rightctrl": "ctrlright",
    "leftalt": "altleft", "rightalt": "altright",
    "leftcontrol": "ctrlleft", "rightcontrol": "ctrlright",
    "control": "ctrlleft", "ctrl": "ctrlleft",
    "shift": "shiftleft", "alt": "altleft",
    # keyboard 库把左右修饰键写成带空格的形式，读旧配置时要能认出来
    "left shift": "shiftleft", "right shift": "shiftright",
    "left ctrl": "ctrlleft", "right ctrl": "ctrlright",
    "left control": "ctrlleft", "right control": "ctrlright",
    "left alt": "altleft", "right alt": "altright",
    # 编辑键/扩展键同理：程序热键允许设置这些键，两套命名要能互相转换
    "page up": "pageup", "page down": "pagedown",
    "caps lock": "capslock", "num lock": "numlock",
    "scroll lock": "scrolllock", "print screen": "printscreen",
}


def _normalize_key_name(name):
    """归一化物理键名；不认识的键名原样返回，由调用方决定是否回退。"""
    name = name.strip().lower()
    return _KEY_NAME_ALIASES.get(name, name)


def normalize_key_name(name):
    """把界面或配置文件里的键名统一成 pyautogui 键名（LeftShift→shiftleft、Ctrl→ctrlleft）。"""
    return _normalize_key_name(str(name))


def is_valid_key_name(name):
    """判断键名是否落在允许设置的范围内，键位设置界面用它做保存前校验。"""
    return _normalize_key_name(str(name)) in _ALLOWED_KEY_NAMES


def _warn_once(key, message):
    if key in _warned_keys:
        return
    _warned_keys.add(key)
    CUS_LOGGER.warning(message)


def _load_game_keys():
    """读取用户键位配置，缺失项回退到默认键位。"""
    global _GAME_KEYS, _DEFAULT_KEYS, _DEFAULT_KEY_TO_NAME, _game_keys_loaded
    # 延迟导入：导入 tool.GLOBAL 时就会构造 KeyMouseManager，而 load_settings 有写盘副作用，
    # 不能在模块导入阶段读配置。
    from tool.settings import load_default_settings, load_settings
    try:
        defaults = (load_default_settings() or {}).get("game_keys") or {}
    except Exception as error:
        CUS_LOGGER.error(f"读取默认键位配置失败，本轮按键将按逻辑名原样下发：{error}")
        defaults = {}
    try:
        user = (load_settings() or {}).get("game_keys") or {}
    except Exception as error:
        CUS_LOGGER.error(f"读取用户键位配置失败，本轮按键使用默认键位：{error}")
        user = {}

    default_keys = {str(name): _normalize_key_name(str(value)) for name, value in defaults.items()}
    merged = {}
    for name, default_value in default_keys.items():
        value = user.get(name)
        value = _normalize_key_name(str(value)) if value else default_value
        if value not in _ALLOWED_KEY_NAMES:
            _warn_once(name, f"键位配置中 {name} 的值 {value!r} 不合法，已回退为默认键 {default_value}")
            value = default_value
        merged[name] = value

    _DEFAULT_KEYS = default_keys
    # 默认物理键→逻辑名，用于兼容 JSON 脚本和历史写法里的 press("f")、press("w")
    _DEFAULT_KEY_TO_NAME = {}
    for name, value in default_keys.items():
        _DEFAULT_KEY_TO_NAME.setdefault(value, name)
    _GAME_KEYS = merged
    _game_keys_loaded = True


def resolve_key(key):
    """
    把逻辑键名解析成 pyautogui 可用的物理键名

    解析顺序：
    0. 含大写字母的键名（"V"、"R"）→ 视为程序内固定键，绕过配置直接下发小写键
    1. 命中 game_keys 的逻辑名（"interact"）→ 用户当前设置的物理键
    2. 命中某逻辑名的默认物理键（"f"）→ 按该逻辑名解析，兼容 JSON 脚本参数
    3. 其余原样小写下发（"esc" 等固定键走这条）

    Args:
        key: 逻辑键名或物理键名

    Returns:
        物理键名
    """
    if not _game_keys_loaded:
        _load_game_keys()
    if not isinstance(key, str):
        key = str(key)
    key = key.strip()
    # 逻辑键名一律小写，所以"含大写字母"唯一含义就是程序内固定键（战斗内按键等）。
    # pyautogui 对单个大写字母会自动补按 Shift，必须先转小写再下发。
    if key != key.lower():
        return key.lower()
    name = _normalize_key_name(key)
    if name in _GAME_KEYS:
        return _GAME_KEYS[name]
    logical_name = _DEFAULT_KEY_TO_NAME.get(name)
    if logical_name:
        return _GAME_KEYS.get(logical_name) or _DEFAULT_KEYS.get(logical_name, name)
    return name


def reload_game_keys():
    """重新读取游戏内键位配置，保存键位设置后调用。"""
    global _game_keys_loaded
    _game_keys_loaded = False
    _warned_keys.clear()
    _load_game_keys()


class KeyMouseManager:
    """
    键鼠操作管理器，通过队列管理所有键鼠操作，确保线程安全和操作顺序
    """

    def __init__(self):
        self.operation_queue = deque()  # 使用deque支持在队首插入操作
        self.queue_lock = threading.Lock()  # 保护队列的锁
        self.worker_thread = None
        self.running = False
        #键鼠配置
        self.config = None
        self.x1 = 0
        self.x0 = 0
        self.y1 = 0
        self.y0 = 0
        self.xx = 1
        self.yy = 1
        self.multi = 1.0
        self.scale = 1.0
        # 用于支持强制操作中断睡眠
        self.sleep_start_time = None
        self.sleep_duration = 0
        self.ending = True
        # 最近一次因越界被跳过的操作，用于避免同一偏离反复刷屏
        self.skipped_pointer = None

    def set_config(self, config):
        """
        设置配置对象

        Args:
            config: 配置对象，包含键位映射等信息
        """
        self.config = config
        if hasattr(config, 'multi'):
            self.multi = config.multi
        if hasattr(config, 'scale'):
            self.scale = config.scale

    def set_screen_params(self, x1, y1, xx, yy):
        """
        设置屏幕参数，用于坐标转换

        客户区左上角的屏幕坐标由右、下边界减客户区尺寸反推：
        各机器标题栏高度不同，客户区上边界会漂，而右下角始终紧贴窗口右下角。

        Args:
            x1: 屏幕右边界坐标
            y1: 屏幕下边界坐标
            xx: 屏幕宽度
            yy: 屏幕高度
        """
        self.x1 = x1
        self.y1 = y1
        self.xx = xx
        self.yy = yy
        self.x0 = x1-xx
        self.y0 = y1-yy

    def start(self):
        """
        启动键鼠管理器线程
        """
        CUS_LOGGER.info("启动键鼠管理器线程")
        if not self.running:
            self.running = True
            with self.queue_lock:
                self.operation_queue.clear()
                self.ending = True
            self.worker_thread = ThreadWithException(target=self._worker, daemon=True,name="键鼠管理")
            self.worker_thread.start()

    def stop(self):
        """
        停止键鼠管理器线程
        """
        CUS_LOGGER.info("停止键鼠管理器线程")
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            # 发送停止信号
            with self.queue_lock:
                self.operation_queue.clear()  # 清空队列中的所有操作
                self.operation_queue.append("stop")
            self.worker_thread.join()

    def clean(self):
        """
        清除当前键鼠管理器线程所有操作
        """
        CUS_LOGGER.debug("清除当前所有操作")
        if self.worker_thread and self.worker_thread.is_alive():
            with self.queue_lock:
                self.operation_queue.clear()  # 清空队列中的所有操作

    def _worker(self):
        """
        工作线程，处理队列中的操作
        """
        while self.running:
            operation = None
            with self.queue_lock:
                if self.operation_queue:
                    operation = self.operation_queue.popleft()
                    self.ending = False

            if operation == "stop":
                # None作为停止信号
                break

            if operation != "stop" and operation is not None:
                self._execute_operation(operation)
                with self.queue_lock:
                    self.ending = True
            else:
                # 队列为空，短暂休眠
                time.sleep(0.01)
        CUS_LOGGER.info("键鼠管理器线程已停止")

    def _game_point(self, op_type, x, y):
        """
        把 1920x1080 像素坐标换算成屏幕坐标，并确认落点在游戏窗口内

        落点在游戏窗口之外时（例如像素坐标超出 1920x1080 会换算到窗口外），
        照常移动光标会把点击送给别的窗口、抢走游戏前台，因此放弃这次操作，
        并按同一偏离只警告一次记录原因。

        Args:
            op_type: 操作名称，用于日志
            x: 请求的 x 像素坐标
            y: 请求的 y 像素坐标

        Returns:
            (actual_x, actual_y): 游戏窗口内的屏幕坐标；越界时返回None
        """
        actual_x, actual_y = self.x0 + x, self.y0 + y
        if self.x0 <= actual_x <= self.x1 and self.y0 <= actual_y <= self.y1:
            return actual_x, actual_y
        if self.skipped_pointer != (op_type, x, y):
            self.skipped_pointer = (op_type, x, y)
            CUS_LOGGER.warning(
                "%s原本要落在游戏窗口(%s, %s)-(%s, %s)内，请求坐标(%s, %s)换算为屏幕坐标(%s, %s)已越界，跳过本次操作",
                op_type, self.x0, self.y0, self.x1, self.y1,
                x, y, actual_x, actual_y
            )
        return None

    def _execute_operation(self, operation):
        """
        执行单个键鼠操作

        Args:
            operation: 操作字典，包含操作类型和参数
        """
        op_type = operation['type']
        CUS_LOGGER.debug(f"执行操作{operation}，当前队列长度{len(self.operation_queue)}")
        if op_type == 'keyDown':
            pyautogui.keyDown(resolve_key(operation['key']))

        elif op_type == 'keyUp':
            key = resolve_key(operation['key'])
            # 长按加速：走 W 的时候把加速键一并松开，否则会一直处于加速状态
            if (self.config and hasattr(self.config, 'long_press_sprint') and
                self.config.long_press_sprint and operation['key'] == 'move_w'):
                pyautogui.keyUp(resolve_key('sprint'))
            pyautogui.keyUp(key)

        elif op_type == 'press':
            key = resolve_key(operation['key'])
            duration = operation.get('duration', 0)

            # 检查是否需要跳过该按键
            if operation.get('allow_e', 1) == 0 and operation['key'] == 'technique':
                return

            pyautogui.keyDown(key)
            if duration > 0:
                self._sleep(duration)
            pyautogui.keyUp(key)

        elif op_type == 'click':
            x, y = operation['x'], operation['y']
            # 转换坐标，并确认落点在游戏窗口内
            point = self._game_point("点击", x, y)
            if point is None:
                return
            win32api.SetCursorPos(point)
            pyautogui.click()

        elif op_type == 'turn':
            degrees = operation['degrees']
            fine = operation.get('fine', 1)
            self._direct_turn(degrees, fine)

        elif op_type == 'scroll':
            x, y = operation['x'], operation['y']
            direct = operation['direct']
            # 转换坐标，并确认落点在游戏窗口内
            point = self._game_point("滚轮", x, y)
            if point is None:
                return
            win32api.SetCursorPos(point)
            count = abs(direct)
            for _ in range(count):
                if direct > 0:
                    pyautogui.scroll(120)
                else:
                    pyautogui.scroll(-120)

        elif op_type == 'drag':
            start_x, start_y = operation['start_x'], operation['start_y']
            end_x, end_y = operation['end_x'], operation['end_y']
            duration = operation.get('duration', 0.4)
            # 转换坐标，并确认起止点都在游戏窗口内
            start = self._game_point("拖拽起点", start_x, start_y)
            end = self._game_point("拖拽终点", end_x, end_y)
            if start is None or end is None:
                return
            win32api.SetCursorPos(start)
            self._sleep(0.2)
            pyautogui.dragTo(end[0], end[1], duration, button='left')
            # pyautogui.drag(end[0] - start[0], end[1] - start[1], duration)

        elif op_type == 'sleep':
            duration = operation.get('duration', 0)
            self._sleep(duration)

    def _direct_turn(self, degrees, fine=1):
        """
        直接执行视角转动，不通过队列

        以逐段移动鼠标的方式转动视角：一次最多转 30/fine 度，每度对应的鼠标
        横向移动量约为 16.5 像素，再乘以玩家的灵敏度倍率（multi）与 DPI 缩放比（scale）。

        Args:
            degrees: 转动角度，单位为度；正数向右转（俯视顺时针），负数向左转
            fine: 精细度控制参数，越大单段转动的角度上限越小、越慢
        """
        if degrees > 30 // fine:
            step = 30 // fine
        elif degrees < -30 // fine:
            step = -30 // fine
        else:
            step = degrees
        dx = int(16.5 * step * self.multi * self.scale)
        CUS_LOGGER.debug(f"旋转{degrees}°，精度{fine},移动距离{dx}，倍率{self.multi}，缩放比{self.scale}")
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0)  # 进行视角移动
        self._sleep(0.05 * fine)
        if degrees != step:
            self._direct_turn(degrees - step, fine)

    def _sleep(self, duration):
        """
        可中断的sleep方法，支持强制操作中断

        Args:
            duration: 睡眠时间（秒）
        """
        if duration <= 0:
            return

        # 记录睡眠开始时间和总时长
        self.sleep_start_time = time.time()
        self.sleep_duration = duration
        # 循环检查是否需要中断睡眠
        self.end_time = self.sleep_start_time + duration
        while time.time() < self.end_time and self.running:
            time.sleep(0.005)  # 短暂休眠以避免占用过多CPU
        # 清除睡眠状态
        self.sleep_start_time = None
        self.sleep_duration = 0

    def _handle_force_operation(self, operation):
        """
        处理强制操作，如果当前正在睡眠则中断并重新安排剩余时间

        Args:
            operation: 强制操作
        """
        # 检查当前是否正在睡眠
        put=True
        if self.sleep_start_time is not None and self.sleep_duration > 0:
            # 计算剩余睡眠时间
            elapsed = time.time() - self.sleep_start_time
            remaining = self.sleep_duration - elapsed

            # 如果还有剩余时间，将其作为sleep操作插入队首
            if remaining > 0.01:
                CUS_LOGGER.debug(f"强制操作{operation}，剩余睡眠时间{remaining}秒")
                sleep_operation = {
                    'type': 'sleep',
                    'duration': remaining
                }
                with self.queue_lock:
                    self.operation_queue.appendleft(sleep_operation)
                    self.operation_queue.appendleft(operation)
                    put=False

            # 清除睡眠状态
            self.sleep_start_time = None
            self.sleep_duration = 0
            self.end_time = 0
        if put:
            # 将强制操作插入队首
            with self.queue_lock:
                self.operation_queue.appendleft(operation)

    def _enqueue(self, operation):
        """
        把操作放进队列

        强制操作插到队首，并抢在可中断的 sleep 之前执行。

        Args:
            operation: 操作字典，需自带 force 字段
        """
        if operation['force']:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def wait(self):
        """
        等待操作队列及正在执行的动作全部完成，停止时提前返回。
        """
        while True:
            with self.queue_lock:
                if not self.running:
                    return
                if self.worker_thread is not None and not self.worker_thread.is_alive():
                    raise RuntimeError("键鼠管理器线程异常退出，动作未能完成，请查看错误日志")
                if not self.operation_queue and self.ending:
                    return
                if len(self.operation_queue) == 1 and self.operation_queue[0] == "stop":
                    return
            # 等待一小段时间再检查
            time.sleep(0.1)

    def keyDown(self, key, force=False):
        """
        按下按键

        Args:
            key: 要按下的键
            force: 是否为强制操作
        """
        operation = {
            'type': 'keyDown',
            'key': key,
            'force': force
        }
        self._enqueue(operation)

    def keyUp(self, key, force=False):
        """
        释放按键

        Args:
            key: 要释放的键
            force: 是否为强制操作
        """
        operation = {
            'type': 'keyUp',
            'key': key,
            'force': force
        }
        self._enqueue(operation)

    def press(self, key, duration=0, allow_e=1, force=False):
        """
        按下并释放按键

        Args:
            key: 要按下的键，逻辑键名（"interact"）或含大写的固定键（"V"）
            duration: 按下持续时间（秒）
            allow_e: 是否允许施放秘技（technique 键），0 表示跳过（用于特殊场景）
            force: 是否为强制操作
        """
        operation = {
            'type': 'press',
            'key': key,
            'duration': duration,
            'allow_e': allow_e,
            'force': force
        }
        self._enqueue(operation)

    def turn(self, degrees, fine=1, force=False):
        """
        水平转动视角

        Args:
            degrees: 转动角度，单位为度；正数向右转（俯视顺时针），负数向左转
            fine: 精细度控制参数，越大单次转动越细碎、越慢
            force: 是否为强制操作
        """
        operation = {
            'type': 'turn',
            'degrees': degrees,
            'fine': fine,
            'force': force
        }
        self._enqueue(operation)

    def click_point(self, x, y, force=False, box=None):
        """
        按 1920x1080 像素坐标点击，原点在游戏客户区左上角。

        入队的就是像素坐标本身，换算成屏幕坐标在 _game_point 里统一做，
        所以日志里打印的坐标和这里传的完全一致。
        视觉识别算出的中心常带小数（如 (1263 + 1317) / 2 = 1290.0、796.5），
        而 win32api 只接受整数坐标，入队前四舍五入到整像素。

        Args:
            x: 1920x1080 坐标系下的 x 坐标，向右为正
            y: 1920x1080 坐标系下的 y 坐标，向下为正
            force: 是否为强制操作
            box: 这次点击来源的框 [x1, x2, y1, y2]（同一坐标系），只写进日志，
                用来核对落点是不是点在了框该在的位置
        """
        x, y = int(round(x)), int(round(y))
        operation = {
            'type': 'click',
            'x': x,
            'y': y,
            'force': force
        }
        if box is not None:
            operation['box'] = [int(round(value)) for value in box]
        self._enqueue(operation)

    def scroll_point(self, x, y, direct=1, force=False):
        """
        在 1920x1080 像素坐标处滚动滚轮。

        Args:
            x: 1920x1080 坐标系下的 x 坐标
            y: 1920x1080 坐标系下的 y 坐标
            direct: 滚动方向和次数，正数向上滚动，负数向下滚动
            force: 是否为强制操作
        """
        # 与点击一致：识别算出的中心可能带小数，入队前四舍五入到整像素。
        x, y = int(round(x)), int(round(y))
        self._enqueue({
            'type': 'scroll',
            'x': x,
            'y': y,
            'direct': direct,
            'force': force
        })

    def drag_point(self, start_x, start_y, end_x, end_y, duration=0.4, force=False):
        """
        按 1920x1080 像素坐标拖拽。

        Args:
            start_x: 起始点 x 像素坐标
            start_y: 起始点 y 像素坐标
            end_x: 结束点 x 像素坐标
            end_y: 结束点 y 像素坐标
            duration: 拖拽持续时间（秒）
            force: 是否为强制操作
        """
        # 与点击一致：识别算出的中心可能带小数，入队前四舍五入到整像素。
        start_x, start_y = int(round(start_x)), int(round(start_y))
        end_x, end_y = int(round(end_x)), int(round(end_y))
        self._enqueue({
            'type': 'drag',
            'start_x': start_x,
            'start_y': start_y,
            'end_x': end_x,
            'end_y': end_y,
            'duration': duration,
            'force': force
        })

    def sleep(self, duration, force=False):
        """
        可中断的sleep操作

        Args:
            duration: 睡眠时间（秒）
            force: 是否为强制操作
        """
        operation = {
            'type': 'sleep',
            'duration': duration,
            'force': force
        }
        self._enqueue(operation)
