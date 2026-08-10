import ctypes
import threading
import traceback


# 延迟导入，避免循环导入
def get_globals():
    from tool.GLOBAL import PRINT_TO_UI
    return PRINT_TO_UI

def get_logger():
    from tool.log import CUS_LOGGER, log_emitter
    return CUS_LOGGER, log_emitter


class ThreadWithException(threading.Thread):
    def __init__(self, target, kwargs=None, name="My Thread", is_print=True, daemon=True):
        """
        重写的python threading线程方法.
        支持通过抛出异常来实现结束线程, 该方法会立刻中断run方法, 不需要循环式编程.
        支持捕获结束参数.
        :param target: 目标函数
        :param kwargs: 目标函数参数(字典形式)
        :param name: 线程名称(用于print)
        :param is_print: 是否print一些线程本身的调试信息
        :param daemon: 是否将线程设置为守护线程
        """
        super().__init__(target=target, kwargs=kwargs, name=name, daemon=daemon)
        threading.Thread.__init__(self)

        # 转化None 为空字典
        if kwargs is None:
            kwargs = {}

        # 默认参数
        self.target = target
        self.kwargs = kwargs
        self.name = name
        self.is_print = is_print

        # 额外参数
        self.return_value = None  # 用于获取函数返回值

    def run(self):
        try:
            CUS_LOGGER, log_emitter = get_logger()
            if self.is_print:
                CUS_LOGGER.debug(f"[{self.name}] Start")
            self.return_value = self.target(**self.kwargs)
        except Exception:
            PRINT_TO_UI = get_globals()
            PRINT_TO_UI.emit("任务发生错误, 子线程已中断, 详见日志或信息框体.")
            _, log_emitter = get_logger()
            err_msg = traceback.format_exc()
            log_emitter.show_error_signal.emit(f"任务执行器的子线程中发生错误 - {self.name}", err_msg)
            CUS_LOGGER.error(err_msg)
        finally:
            CUS_LOGGER, _ = get_logger()
            if self.is_print:
                CUS_LOGGER.debug(f"[{self.name}] End")

    def get_id(self):
        """获取进程的唯一id"""
        # returns id of the respective thread
        if hasattr(self, '_thread_id'):
            return self._thread_id
        for id, thread in threading._active.items():
            if thread is self:
                return id

    def get_return_value(self):
        threading.Thread.join(self)  # 等待 目标函数 执行完毕
        try:
            return self.return_value
        except Exception:
            CUS_LOGGER, _ = get_logger()
            CUS_LOGGER.error(Exception)
            return None

    def raise_exception(self):
        """发送错误 终止线程"""
        thread_id = self.get_id()
        # 精髓就是这句话，给线程发过去一个exceptions，线程就那边响应完就停了
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, ctypes.py_object(SystemExit))
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            CUS_LOGGER, _ = get_logger()
            CUS_LOGGER.debug('Exception raise failure')

    def stop(self):
        """等效的终止线程"""
        self.raise_exception()
