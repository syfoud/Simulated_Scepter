import io
import logging
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

logs_path = Path("logs")
logs_path.mkdir(exist_ok=True, parents=True)

current_time_str = datetime.now().strftime("%Y-%m-%d-%H-%M")

class LogEmitter(QObject):
    """用于跨线程发送日志信号的Qt对象"""
    show_error_signal = pyqtSignal(str, str)  # (标题, 内容)
    find_path_state_signal = pyqtSignal(str)  # (路径状态文本)
    kill_num_signal = pyqtSignal(str)  # (路径状态文本)
    fps_update_signal = pyqtSignal(float)  # (FPS值)


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
        with open(logs_path / f"log_{current_time_str}.txt", "a", encoding="utf-8") as f:
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

        logging_format = "%(levelname)s [%(asctime)s] [%(filename)s:%(lineno)d] %(message)s"
        formatter = Formatter(logging_format)

        # --------- 常规日志文件处理器 ---------

        # file_handler = FileHandler(filename=logs_path / "log.txt", mode="a", encoding="utf-8")
        # file_handler.setFormatter(formatter)
        # file_handler.addFilter(keyword_filter)
        # self.addHandler(file_handler)

        timestamped_file_handler = FileHandler(filename=logs_path / f"log_{current_time_str}.txt", mode="a",
                                               encoding="utf-8")
        timestamped_file_handler.setFormatter(formatter)

        self.addHandler(timestamped_file_handler)
        # --------- 错误日志文件处理器 ---------

        error_file_handler = logging.FileHandler(
            filename=logs_path / "error_log.log",
            mode='w',
            encoding='utf-8'
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d\n'
            '>> %(message)s'
        ))
        self.addHandler(error_file_handler)

        # --------- 高危日志文件处理器 ---------

        critical_file_handler = logging.FileHandler(
            filename=logs_path / 'critical_log.log',
            mode='w',
            encoding='utf-8'
        )
        critical_file_handler.setLevel(logging.CRITICAL)
        critical_file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d\n'
            '>> %(message)s'
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

# 禁用 PyQt5 的 DEBUG 日志
logging.getLogger('PyQt5').setLevel(logging.WARNING)
logging.getLogger('PyQt5.uic').setLevel(logging.WARNING)




def my_print(*args, **kwargs):
    CUS_LOGGER.info(" ".join(map(str, args)))
    # GLOBAL.PRINT_TO_UI.emit(
    #     text=" ".join(map(str, args)),
    #     time=False)
    if len(kwargs):
        print(*args, **kwargs)

def print_exc():
    with io.StringIO() as buf, open("logs/error_log.txt", "a") as f:
        traceback.print_exc(file=buf)
        f.write(buf.getvalue())

if __name__ == '__main__':
    # 测试用例
    CUS_LOGGER.info("这是一个普通日志!")
    CUS_LOGGER.error("这是一个普通错误，应该加入报错日志!")
    x=1/0
