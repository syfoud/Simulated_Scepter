import io
import logging
import os
import sys
import traceback
from datetime import datetime
from logging import (
    DEBUG,
    INFO,
    FileHandler,
    Formatter,
    StreamHandler,
)
from pathlib import Path

import colorlog
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from route import PATHS


# 延迟导入 GLOBAL，避免循环导入
def get_GLOBAL():
    try:
        from tool import GLOBAL
        return GLOBAL
    except ImportError:
        # 如果直接运行此文件，可能无法导入config模块
        # 返回一个模拟对象以避免错误
        class MockGlobal:
            PRINT_TO_UI = None
        return MockGlobal()

logs_path = Path(PATHS["logs"])
logs_path.mkdir(exist_ok=True, parents=True)

current_time_str = datetime.now().strftime("%Y-%m-%d-%H-%M")

# 测试运行时由 test/__init__.py 设置该环境变量，让测试写入的日志带 test_ 前缀，
# 便于把测试产物和正常运行产生的日志区分开；正常运行该变量不存在，前缀为空。
LOG_PREFIX = os.environ.get("SIMS_TEST_LOG_PREFIX", "")


def timed_log_filename() -> str:
    """返回按分钟命名的日志文件名（测试运行时带 test_ 前缀）。"""
    return f"{LOG_PREFIX}log_{current_time_str}.txt"


def current_log_file() -> str:
    """返回本次运行正在写入的日志文件名。

    Returns:
        形如 log_年-月-日-时-分.txt 的文件名（测试运行时带 test_ 前缀），与 logs 目录下的实际文件同名。
    """
    return timed_log_filename()


# pathname 到显示路径的映射只取决于项目根目录，运行期不会变化，可以直接缓存。
_relative_path_cache = {}


def _relative_source_path(pathname: str) -> str:
    """把源码路径转成相对项目根目录的路径，项目外路径只保留文件名。

    日志里的位置需要区分不同路径下的同名文件，
    因此统一以项目根目录为基准并改用正斜杠；虚拟环境、标准库等外部路径
    仍然只显示文件名，避免日志里出现一长串 ``..``。
    """
    cached = _relative_path_cache.get(pathname)
    if cached is not None:
        return cached
    if pathname.startswith("<") and pathname.endswith(">"):
        result = pathname
    else:
        try:
            relative = os.path.relpath(pathname, PATHS["root"])
        except ValueError:
            # Windows 下不同盘符无法计算相对路径
            result = os.path.basename(pathname)
        else:
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                result = os.path.basename(pathname)
            else:
                result = relative.replace(os.sep, "/")
    _relative_path_cache[pathname] = result
    return result


def get_caller_location() -> str:
    """返回调用本函数的代码所在文件之外第一层调用位置。

    供工具层函数记录“是谁调用了这次操作”：同文件内的辅助函数会被跳过，
    所以返回的是工具模块之外的真实调用方，形如 ``core/any_fate/engine.py:123``；
    整个调用栈都找不到外部文件时返回 ``unknown``。
    """
    frame = sys._getframe(1)
    origin = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
    while frame is not None:
        filename = frame.f_code.co_filename
        if (not filename.startswith("<")
                and os.path.normcase(os.path.abspath(filename)) != origin):
            return f"{_relative_source_path(filename)}:{frame.f_lineno}"
        frame = frame.f_back
    return "unknown"


class CusLogFormatter(Formatter):
    """文件日志的 Formatter：输出相对路径，并追加可选的调用者位置。

    调用方可通过 ``extra={"caller": ...}`` 传入调用位置；没有该字段时不追加。
    控制台和 UI 的 Formatter 不读取这两个字段，因此保持原样。
    """

    def format(self, record):
        record.relpath = _relative_source_path(record.pathname)
        caller = getattr(record, "caller", None)
        record.caller_suffix = f"，调用者[{caller}]" if caller and caller != "unknown" else ""
        return super().format(record)


class LogEmitter(QObject):
    """用于跨线程发送日志信号的Qt对象"""
    show_error_signal = pyqtSignal(str, str)  # (标题, 内容)
    find_path_state_signal = pyqtSignal(str)  # (路径状态文本)
    kill_num_signal = pyqtSignal(str)  # (路径状态文本)
    fps_update_signal = pyqtSignal(float)  # (FPS值)
    cleanup_finished_signal = pyqtSignal(object)  # (本次清理结果列表)
    video_convert_finished_signal = pyqtSignal(int, int)  # (成功数, 失败数)


log_emitter = LogEmitter()

def set_debug(my_logger, debug: bool = False):
    my_logger.setLevel(DEBUG if debug else INFO)

class UILogHandler(StreamHandler):
    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))

    def emit(self, record):
        GLOBAL = get_GLOBAL()
        # 非调试模式下过滤 DEBUG 日志
        if not getattr(GLOBAL, 'DEBUG_MODE', True) and record.levelno < logging.INFO:
            return

        if GLOBAL.PRINT_TO_UI is not None:
            msg = self.format(record)
            level_colors = {
                'DEBUG': 4, 'INFO': 5, 'WARNING': 2, 'ERROR': 1, 'CRITICAL': 1
            }
            color_level = level_colors.get(record.levelname, 5)
            GLOBAL.PRINT_TO_UI.emit(text=msg, color_level=color_level, time=True)

class KeywordFilter(logging.Filter):
    """多关键词过滤器"""

    def __init__(self, keywords):
        super().__init__()
        self.keywords = keywords

    def filter(self, record):
        return not any(keyword in record.getMessage() for keyword in self.keywords)

class PrintToFileLogger:
    """专门用于处理print输出并同时写入日志文件和原始输出的类"""
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.linebuf = ''

    def write(self, buf):
        temp_linebuf = self.linebuf + buf
        self.linebuf = ''
        for line in temp_linebuf.splitlines(True):
            if line[-1] == '\n':
                # 检查是否为logger输出，如果是则不记录为PRINT（避免重复）
                stripped_line = line.rstrip()
                # 检查是否包含典型的logger标识符
                is_logger_output = self._is_logger_output(stripped_line)

                if not is_logger_output:
                    # 不是logger输出，记录为PRINT
                    self._write_to_logfiles(stripped_line)

                # 总是输出到原始stdout（控制台）
                self.original_stdout.write(line)
            else:
                self.linebuf = line

    def flush(self):
        if self.linebuf != '':
            # 写入剩余内容到原始输出
            self.original_stdout.write(self.linebuf)

            # 检查是否为logger输出
            is_logger_output = self._is_logger_output(self.linebuf)

            if not is_logger_output:
                self._write_to_logfiles(self.linebuf)

            self.linebuf = ''

    def _is_logger_output(self, line):
        """判断是否为logger输出"""
        line_lower = line.lower()

        # 检查是否包含典型的logger标识符
        if any(indicator.lower() in line_lower for indicator in ['INFO:', 'WARNING:', 'ERROR:', 'DEBUG:', 'CRITICAL:', 'my customize logger']):
            return True

        # 检查是否为标准格式的logger输出（包含时间戳和级别）
        if '[' in line and any(level in line for level in ['INFO', 'WARNING', 'ERROR', 'DEBUG', 'CRITICAL']):
            # 进一步检查格式，如包含asctime、日期时间等
            # 例如: "2026-01-20 21:26:03,156 - INFO - 这是一个logger info信息"
            import re
            # 检查是否符合时间戳格式
            timestamp_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}'
            if re.search(timestamp_pattern, line):
                return True

        # 检查是否包含formatter中的特定字段
        if any(field in line_lower for field in ['asctime', 'levelname', 'filename', 'lineno', 'message']):
            return True

        return False

    def _write_to_logfiles(self, message):
        # 只写入到日志文件
        with open(logs_path / "log.txt", "a", encoding="utf-8") as f:
            f.write(f"PRINT - {message}\n")
        with open(logs_path / timed_log_filename(), "a", encoding="utf-8") as f:
            f.write(f"PRINT - {message}\n")

# 先保存原始的stdout和stderr，然后立即重定向
original_stdout = sys.stdout
original_stderr = sys.stderr

# 创建print捕获器并重定向stdout/stderr
print_capture = PrintToFileLogger(original_stdout)

# 重定向stdout和stderr（在创建logger之前）
sys.stdout = print_capture
sys.stderr = print_capture

class CusLogger(logging.Logger):
    """自定义logger类"""

    def __init__(self, name):
        super().__init__(name)

        # 固定 Logger 级别为 DEBUG，让所有日志都能产生
        set_debug(self, True)

        # 其他原有处理器配置...
        keywords = ["property", "widget", "push", "layout"]
        keyword_filter = KeywordFilter(keywords)

        logging_format = (
            "%(levelname)s [%(asctime)s] [%(relpath)s:%(lineno)d] "
            "%(message)s%(caller_suffix)s"
        )
        formatter = CusLogFormatter(logging_format)

        # --------- 常规日志文件处理器 ---------

        # file_handler = FileHandler(filename=logs_path / "log.txt", mode="a", encoding="utf-8")
        # file_handler.setFormatter(formatter)
        # file_handler.addFilter(keyword_filter)
        # self.addHandler(file_handler)

        timestamped_file_handler = FileHandler(filename=logs_path / timed_log_filename(), mode="a",
                                               encoding="utf-8")
        timestamped_file_handler.setFormatter(formatter)

        self.addHandler(timestamped_file_handler)
        # --------- 错误日志文件处理器 ---------

        error_file_handler = logging.FileHandler(
            filename=logs_path / "error_log.log",
            mode='a',
            encoding='utf-8'
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(CusLogFormatter(
            '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d\n'
            '>> %(message)s%(caller_suffix)s'
        ))
        self.addHandler(error_file_handler)

        # --------- 高危日志文件处理器 ---------

        critical_file_handler = logging.FileHandler(
            filename=logs_path / 'critical_log.log',
            mode='a',
            encoding='utf-8'
        )
        critical_file_handler.setLevel(logging.CRITICAL)
        critical_file_handler.setFormatter(CusLogFormatter(
            '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d\n'
            '>> %(message)s%(caller_suffix)s'
        ))
        self.addHandler(critical_file_handler)

        # --------- 控制台处理器 ---------
        # 为了避免与print输出重复记录，使用原始的stdout，而不是被重定向的stdout
        # 但为了区分，我们不使用StreamHandler，而是直接将彩色输出写入原始stdout
        import sys
        # 只在控制台显示，不在日志文件中重复记录
        console_formatter = colorlog.ColoredFormatter('%(log_color)s%(asctime)s - %(levelname)s - %(message)s')

        class ConsoleOnlyHandler(logging.Handler):
            def __init__(self, original_stdout):
                super().__init__()
                self.original_stdout = original_stdout
                self.setFormatter(console_formatter)
                self.addFilter(keyword_filter)

            def emit(self, record):
                msg = self.format(record)
                self.original_stdout.write(msg + '\n')
                self.original_stdout.flush()

        console_handler = ConsoleOnlyHandler(original_stdout)
        self.addHandler(console_handler)

        ui_handler = UILogHandler()
        self.addHandler(ui_handler)

        # 异常处理
        sys.excepthook = self.handle_exception

    def handle_exception(self, exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        self.critical("未捕获的严重异常发生! ", exc_info=(exc_type, exc_value, exc_traceback))
# 保留上面的PrintToUILogger类，这里不再需要PrintCaptureLogger类

app = QApplication.instance() or QApplication(sys.argv)
logging.setLoggerClass(CusLogger)
CUS_LOGGER = logging.getLogger('my customize logger')

# 后续 Logger 恢复使用 Python 默认 Logger，
# 避免 PyQt5 的层级 Logger 被错误创建为 CusLogger。
logging.setLoggerClass(logging.Logger)

# --------- PyQt5 日志处理 ---------

pyqt_logger = logging.getLogger('PyQt5')
pyqt_logger.setLevel(logging.DEBUG)

# 防止 PyQt5 日志继续传播到 root logger，避免以后再次重复。
pyqt_logger.propagate = False

# PyQt5 日志：每条只写入一次普通日志文件。
pyqt_file_handler = FileHandler(
    filename=logs_path / timed_log_filename(),
    mode="a",
    encoding="utf-8"
)
pyqt_file_handler.setFormatter(
    CusLogFormatter(
        "%(levelname)s [%(asctime)s] [%(relpath)s:%(lineno)d] "
        "%(message)s%(caller_suffix)s"
    )
)
pyqt_logger.addHandler(pyqt_file_handler)

# PyQt5 日志：控制台只显示未被关键词过滤的日志。
pyqt_console_handler = StreamHandler(original_stdout)
pyqt_console_handler.setFormatter(
    colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(levelname)s - %(message)s'
    )
)
pyqt_console_handler.addFilter(
    KeywordFilter(["property", "widget", "push", "layout"])
)
pyqt_logger.addHandler(pyqt_console_handler)

# 让 PyQt5.uic 及其子 Logger 产生 DEBUG 日志，
# 并通过 PyQt5 Logger 的两个 Handler 统一处理。
logging.getLogger('PyQt5.uic').setLevel(logging.DEBUG)


def my_print(*args, **kwargs):
    CUS_LOGGER.info(" ".join(map(str, args)))
    # GLOBAL.PRINT_TO_UI.emit(
    #     text=" ".join(map(str, args)),
    #     time=False)
    if len(kwargs):
        print(*args, **kwargs)

def print_exc():
    with io.StringIO() as buf, open(logs_path / f"{LOG_PREFIX}error_log.txt", "a", encoding="utf-8") as f:
        traceback.print_exc(file=buf)
        f.write(buf.getvalue())

if __name__ == '__main__':
    # 测试用例
    CUS_LOGGER.info("这是一个普通日志!")
    CUS_LOGGER.error("这是一个普通错误，应该加入报错日志!")
    x=1/0
