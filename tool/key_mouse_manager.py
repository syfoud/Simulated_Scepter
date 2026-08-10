import threading
import time
from collections import deque

import pyautogui
import win32api
import win32con

from tool.log import CUS_LOGGER
from tool.thread import ThreadWithException


# 延迟导入，避免循环导入
def get_CUS_LOGGER():
    from tool.log import CUS_LOGGER
    return CUS_LOGGER


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
        self.full = False
        self.multi = 1.0
        self.scale = 1.0
        # 用于支持强制操作中断睡眠
        self.sleep_start_time = None
        self.sleep_duration = 0
        self.ending = False

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

    def set_screen_params(self, x1, y1, xx, yy, full=False):
        """
        设置屏幕参数，用于坐标转换

        Args:
            x1: 屏幕右边界坐标
            y1: 屏幕下边界坐标
            xx: 屏幕宽度
            yy: 屏幕高度
            full: 是否全屏模式
        """
        self.x1 = x1
        self.y1 = y1
        self.xx = xx
        self.yy = yy
        self.x0 = x1-xx
        self.y0 = y1-yy
        self.full = False

    def start(self):
        """
        启动键鼠管理器线程
        """
        CUS_LOGGER = get_CUS_LOGGER()
        CUS_LOGGER.info("启动键鼠管理器线程")
        if not self.running:
            self.running = True
            self.operation_queue.clear()
            self.worker_thread = ThreadWithException(target=self._worker, daemon=True,name="键鼠管理")
            self.worker_thread.start()

    def stop(self):
        """
        停止键鼠管理器线程
        """
        CUS_LOGGER = get_CUS_LOGGER()
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
        CUS_LOGGER = get_CUS_LOGGER()
        CUS_LOGGER.debug("清除当前所有操作")
        if self.worker_thread and self.worker_thread.is_alive():
            with self.queue_lock:
                self.operation_queue.clear()  # 清空队列中的所有操作
    def _worker(self):
        """
        工作线程，处理队列中的操作
        """
        CUS_LOGGER = get_CUS_LOGGER()
        while self.running:
            operation = None
            with self.queue_lock:
                if self.operation_queue:
                    operation = self.operation_queue.popleft()

            if operation == "stop":
                # None作为停止信号
                break

            if operation != "stop" and operation is not None:
                self.ending = False
                self._execute_operation(operation)
                self.ending = True
            else:
                # 队列为空，短暂休眠
                time.sleep(0.01)
        CUS_LOGGER.info("键鼠管理器线程已停止")

    def _get_mapping(self, key):
        """
        获取键位映射

        Args:
            key: 原始键位

        Returns:
            映射后的键位
        """
        if self.config and hasattr(self.config, 'origin_key') and hasattr(self.config, 'mapping'):
            if key in self.config.origin_key:
                key = self.config.mapping[self.config.origin_key.index(key)]
        return key

    def _convert_coordinates(self, x, y):
        """
        转换坐标格式

        Args:
            x: x坐标（可能是浮点数比例，也可能是游戏实际坐标）
            y: y坐标（可能是浮点数比例，也可能是有游戏实际坐标）

        Returns:
            (actual_x, actual_y): 实际的屏幕坐标
        """
        # 如果是浮点数表示，则计算实际坐标
        if isinstance(x, float):
            actual_x, actual_y = self.x1 - int(x * self.xx), self.y1 - int(y * self.yy)
        else:
            actual_x, actual_y = self.x1-self.xx+x, self.y1-self.yy+y
        # 全屏模式会有一个偏移
        if self.full:
            actual_x += 9
            actual_y += 9

        return actual_x, actual_y

    def _execute_operation(self, operation):
        """
        执行单个键鼠操作

        Args:
            operation: 操作字典，包含操作类型和参数
        """
        op_type = operation['type']
        CUS_LOGGER = get_CUS_LOGGER()
        CUS_LOGGER.debug(f"执行操作{operation}，当前队列长度{len(self.operation_queue)}")
        if op_type == 'keyDown':
            key = self._get_mapping(operation['key'])
            pyautogui.keyDown(key)

        elif op_type == 'keyUp':
            key = self._get_mapping(operation['key'])
            # 特殊处理shift键
            if (self.config and hasattr(self.config, 'long_press_sprint') and
                self.config.long_press_sprint and operation['key'] == 'w'):
                pyautogui.keyUp(self._get_mapping('shift'))
            pyautogui.keyUp(key)

        elif op_type == 'press':
            key = self._get_mapping(operation['key'])
            duration = operation.get('duration', 0)

            # 检查是否需要跳过该按键
            if operation.get('allow_e', 1) == 0 and key == 'e':
                return

            if (self.config and hasattr(self.config, 'slow') and
                self.config.slow and key == 'shift'):
                return

            pyautogui.keyDown(key)
            if duration > 0:
                self._sleep(duration)
            pyautogui.keyUp(key)

        elif op_type == 'click':
            x, y = operation['x'], operation['y']
            # 转换坐标
            actual_x, actual_y = self._convert_coordinates(x, y)
            win32api.SetCursorPos((actual_x, actual_y))
            pyautogui.click()

        elif op_type == 'mouse_move':
            dx = operation['dx']
            fine = operation.get('fine', 1)
            # 仿照UniverseUtils.mouse_move实现
            self._direct_mouse_move(dx, fine)


        elif op_type == 'scroll':
            x, y = operation['x'], operation['y']
            direct = operation['direct']
            # 转换坐标
            actual_x, actual_y = self._convert_coordinates(x, y)
            win32api.SetCursorPos((actual_x, actual_y))
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
            # 转换起始坐标
            actual_start_x, actual_start_y = self._convert_coordinates(start_x, start_y)
            actual_end_x, actual_end_y = self._convert_coordinates(end_x, end_y)
            win32api.SetCursorPos((actual_start_x, actual_start_y))
            self._sleep(0.2)
            pyautogui.dragTo(actual_end_x, actual_end_y, duration, button='left')
            # pyautogui.drag(actual_end_x - actual_start_x, actual_end_y - actual_start_y, duration)

        elif op_type == 'sleep':
            duration = operation.get('duration', 0)
            self._sleep(duration)

    def _direct_mouse_move(self, x, fine=1):
        """
        直接执行鼠标移动，不通过队列

        Args:
            dx: x轴移动距离
            fine: 精细度控制参数
        """

        if x > 30 // fine:
            y = 30 // fine
        elif x < -30 // fine:
            y = -30 // fine
        else:
            y = x
        dx = int(16.5 * y * self.multi * self.scale)
        CUS_LOGGER.debug(f"旋转{x}°，精度{fine},移动距离{dx}，倍率{self.multi}，缩放比{self.scale}")
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0)  # 进行视角移动
        self._sleep(0.05 * fine)
        if x != y:
            self._direct_mouse_move(x - y, fine)

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

    def wait(self):
        """
        等待直到操作队列为空
        如果当前队列为空则直接返回，否则等待直至队列为空
        """
        while True:
            # 如果队列为空或者只有"stop"信号，则返回
            if not len(self.operation_queue) and self.ending:
                return
            with self.queue_lock:
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
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

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
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def press(self, key, duration=0, allow_e=1, force=False):
        """
        按下并释放按键

        Args:
            key: 要按下的键
            duration: 按下持续时间（秒）
            allow_e: 是否允许按下'e'键（用于特殊场景）
            force: 是否为强制操作
        """
        operation = {
            'type': 'press',
            'key': key,
            'duration': duration,
            'allow_e': allow_e,
            'force': force
        }
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def click(self, x, y, force=False):
        """
        点击指定位置

        Args:
            x: 屏幕x坐标（支持浮点数比例坐标和实际坐标）
            y: 屏幕y坐标（支持浮点数比例坐标和实际坐标）
            force: 是否为强制操作
        """
        operation = {
            'type': 'click',
            'x': x,
            'y': y,
            'force': force
        }
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def mouse_move(self, dx, fine=1, force=False):
        """
        移动鼠标

        Args:
            dx: x轴移动距离
            fine: 精细度控制参数
            force: 是否为强制操作
        """
        operation = {
            'type': 'mouse_move',
            'dx': dx,
            'fine': fine,
            'force': force
        }
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def scroll(self, direct=1, x=0.5, y=0.5, force=False):
        """
        滚动鼠标滚轮

        Args:
            x: 滚动位置x坐标（支持浮点数比例坐标和实际坐标）
            y: 滚动位置y坐标（支持浮点数比例坐标和实际坐标）
            direct: 滚动方向和次数，正数向上滚动，负数向下滚动
            force: 是否为强制操作
        """
        operation = {
            'type': 'scroll',
            'x': x,
            'y': y,
            'direct': direct,
            'force': force
        }
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

    def drag(self, start_x, start_y, end_x, end_y, duration=0.4, force=False):
        """
        拖拽操作

        Args:
            start_x: 起始点x坐标（支持浮点数比例坐标和实际坐标）
            start_y: 起始点y坐标（支持浮点数比例坐标和实际坐标）
            end_x: 结束点x坐标（支持浮点数比例坐标和实际坐标）
            end_y: 结束点y坐标（支持浮点数比例坐标和实际坐标）
            duration: 拖拽持续时间（秒）
            force: 是否为强制操作
        """
        operation = {
            'type': 'drag',
            'start_x': start_x,
            'start_y': start_y,
            'end_x': end_x,
            'end_y': end_y,
            'duration': duration,
            'force': force
        }
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)

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
        if force:
            self._handle_force_operation(operation)
        else:
            with self.queue_lock:
                self.operation_queue.append(operation)
