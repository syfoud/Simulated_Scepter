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
        self.input_lock = threading.RLock()  # 物理输入与登记/释放必须原子执行。
        self.input_generation = 0  # clean/stop 使已经出队的旧操作失效。
        self.pressed_keys = set()  # 工作线程登记已按下按键；stop()/clean() 统一释放。
        self.worker_thread = None
        self.worker_error = None
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
        self.coord_scale = 1.0
        self.coord_scale_y = 1.0
        # 用于支持强制操作中断睡眠
        self.sleep_start_time = None
        self.sleep_duration = 0
        self.ending = True

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

    def set_screen_params(self, x1, y1, xx, yy, coord_scale=1.0, coord_scale_y=None):
        """
        设置屏幕参数，用于坐标转换

        Args:
            x1: 屏幕右边界坐标
            y1: 屏幕下边界坐标
            xx: 截取区域宽度（物理像素）
            yy: 截取区域高度（物理像素）
            coord_scale: 基准分辨率横坐标到物理像素的放大系数。
            coord_scale_y: 纵坐标放大系数；省略时沿用横坐标系数。
        """
        self.x1 = x1
        self.y1 = y1
        self.xx = xx
        self.yy = yy
        self.x0 = x1-xx
        self.y0 = y1-yy
        self.coord_scale = coord_scale
        self.coord_scale_y = coord_scale if coord_scale_y is None else coord_scale_y

    def start(self):
        """启动键鼠线程；仍在退出的线程不能与新任务共享输入。"""
        with self.input_lock:
            if self.running:
                return
            if self.worker_thread and self.worker_thread.is_alive():
                raise RuntimeError("键鼠管理器仍在停止，不能重新启动")
            self.running = True
            self.worker_error = None
            with self.queue_lock:
                self.operation_queue.clear()
                self.ending = True
            self.worker_thread = ThreadWithException(target=self._worker, daemon=True, name="键鼠管理")
            self.worker_thread.start()
        CUS_LOGGER.info("启动键鼠管理器线程")

    def stop(self):
        """取消排队和执行中的后续输入，等线程退出并重试释放按键。"""
        self.running = False
        self.clean()
        worker = self.worker_thread
        if worker and worker is not threading.current_thread() and worker.is_alive():
            worker.join()
        self._release_pressed_keys()

    def clean(self):
        """清空操作并释放按键，包括已经出队但尚未发出的输入。"""
        with self.input_lock:
            with self.queue_lock:
                self.input_generation += 1
                self.operation_queue.clear()
                self.end_time = 0
                self.sleep_start_time = None
                self.sleep_duration = 0
            self._release_pressed_keys()

    def _release_pressed_keys(self):
        """释放已登记的按键；失败的按键保留，供停止时重试。"""
        with self.input_lock:
            for key in tuple(self.pressed_keys):
                try:
                    pyautogui.keyUp(key)
                except Exception as exc:
                    CUS_LOGGER.error("释放按键 %s 失败：%s", key, exc)
                else:
                    self.pressed_keys.discard(key)

    def _worker(self):
        """消费输入队列；出队和忙碌状态同步更新，失败时释放已按键。"""
        try:
            while self.running:
                with self.queue_lock:
                    operation = self.operation_queue.popleft() if self.operation_queue else None
                    generation = self.input_generation
                    self.ending = operation is None
                if operation is not None:
                    self._execute_operation(operation, generation)
                    with self.queue_lock:
                        self.ending = True
                else:
                    time.sleep(0.01)
        except Exception as exc:
            self.worker_error = exc
            raise
        finally:
            self.running = False
            self._release_pressed_keys()
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
            # int 是 1920×1080 基准坐标，高分辨率窗口需放大回物理像素
            actual_x = self.x1 - self.xx + int(x * self.coord_scale)
            actual_y = self.y1 - self.yy + int(y * self.coord_scale_y)

        return actual_x, actual_y

    def _execute_operation(self, operation, generation=None):
        """执行操作；每次物理输入前复核停止和清队列代次。"""
        if generation is None:
            generation = self.input_generation
        op_type = operation['type']
        if op_type == 'mouse_move':
            self._direct_mouse_move(operation['dx'], operation.get('fine', 1), generation)
            return
        if op_type == 'sleep':
            self._sleep(operation.get('duration', 0), generation)
            return
        with self.input_lock:
            if not self.running or generation != self.input_generation:
                return
            if op_type in ('keyDown', 'keyUp', 'press'):
                key = self._get_mapping(operation['key'])
                if op_type == 'keyUp':
                    if (self.config and getattr(self.config, 'long_press_sprint', False)
                            and operation['key'] == 'w'):
                        shift = self._get_mapping('shift')
                        pyautogui.keyUp(shift)
                        self.pressed_keys.discard(shift)
                    pyautogui.keyUp(key)
                    self.pressed_keys.discard(key)
                    return
                if op_type == 'press':
                    if operation.get('allow_e', 1) == 0 and key == 'e':
                        return
                    if self.config and getattr(self.config, 'slow', False) and key == 'shift':
                        return
                # 先登记再发送：底层输入发出后抛异常时仍能在 finally 重试释放。
                self.pressed_keys.add(key)
                pyautogui.keyDown(key)
                if op_type == 'keyDown':
                    return
            elif op_type in ('click', 'scroll'):
                win32api.SetCursorPos(self._convert_coordinates(operation['x'], operation['y']))
                if op_type == 'click':
                    pyautogui.click()
                    return
            elif op_type == 'drag':
                win32api.SetCursorPos(self._convert_coordinates(operation['start_x'], operation['start_y']))

        if op_type == 'press':
            try:
                self._sleep(operation.get('duration', 0), generation)
            finally:
                with self.input_lock:
                    pyautogui.keyUp(key)
                    self.pressed_keys.discard(key)
        elif op_type == 'scroll':
            for _ in range(abs(operation['direct'])):
                with self.input_lock:
                    if not self.running or generation != self.input_generation:
                        break
                    pyautogui.scroll(120 if operation['direct'] > 0 else -120)
        elif op_type == 'drag':
            self._sleep(0.2, generation)
            with self.input_lock:
                if not self.running or generation != self.input_generation:
                    return
                end_x, end_y = self._convert_coordinates(operation['end_x'], operation['end_y'])
                try:
                    pyautogui.dragTo(end_x, end_y, operation.get('duration', 0.4), button='left')
                finally:
                    pyautogui.mouseUp(button='left')

    def _direct_mouse_move(self, x, fine=1, generation=None):
        """分段旋转镜头，清队列或停止后不再发送剩余移动。"""
        if generation is None:
            generation = self.input_generation
        if not 0 < fine <= 30:
            raise ValueError("转向精度必须大于 0 且不超过 30")
        while True:
            y = max(-30 // fine, min(30 // fine, x))
            with self.input_lock:
                if not self.running or generation != self.input_generation:
                    return
                dx = int(16.5 * y * self.multi * self.scale)
                CUS_LOGGER.debug("旋转%s°，精度%s，移动距离%s", x, fine, dx)
                win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0)
            self._sleep(0.05 * fine, generation)
            if x == y:
                return
            x -= y

    def _sleep(self, duration, generation=None):
        """
        可中断的sleep方法，支持强制操作中断

        Args:
            duration: 睡眠时间（秒）
        """
        if duration <= 0:
            return
        if generation is None:
            generation = self.input_generation

        with self.queue_lock:
            if not self.running or generation != self.input_generation:
                return
            self.sleep_start_time = time.time()
            self.sleep_duration = duration
            self.end_time = self.sleep_start_time + duration
        while (time.time() < self.end_time and self.running
               and generation == self.input_generation):
            time.sleep(0.005)  # 短暂休眠以避免占用过多CPU
        # 清除睡眠状态
        with self.queue_lock:
            self.sleep_start_time = None
            self.sleep_duration = 0

    def _handle_force_operation(self, operation):
        """
        处理强制操作，如果当前正在睡眠则中断并重新安排剩余时间

        Args:
            operation: 强制操作
        """
        with self.queue_lock:
            if self.sleep_start_time is not None and self.sleep_duration > 0:
                elapsed = time.time() - self.sleep_start_time
                remaining = self.sleep_duration - elapsed
                if remaining > 0.01:
                    self.operation_queue.appendleft({'type': 'sleep', 'duration': remaining})
                self.sleep_start_time = None
                self.sleep_duration = 0
                self.end_time = 0
            self.operation_queue.appendleft(operation)

    def wait(self):
        """等待排队和已出队操作完成；线程失败向业务调用方传播。"""
        while True:
            if self.worker_error is not None:
                raise RuntimeError("键鼠管理器线程执行失败") from self.worker_error
            with self.queue_lock:
                if not self.running or (not self.operation_queue and self.ending):
                    return
            time.sleep(0.01)

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
