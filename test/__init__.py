"""测试包：隔离测试副作用，并让测试写入的日志与正常运行区分开。"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 必须在任何模块 import tool.log 之前设置：日志文件名在 import tool.log 时就已确定。
# tool.log 据此给测试日志加 test_ 前缀，避免测试产物混进正常运行产生的日志。
os.environ.setdefault("SIMS_TEST_LOG_PREFIX", "test_")

# 测试专用的用户目录：避免 config_path()、load_settings() 之类的写入落到真实 user 目录。
TEST_USER_DIR = Path(tempfile.mkdtemp(prefix="simsce-test-user-")).resolve()

from route import PATHS

PATHS["user"] = str(TEST_USER_DIR)
PATHS["backup"] = str(TEST_USER_DIR / "backup")


def _cleanup_test_user_dir():
    shutil.rmtree(TEST_USER_DIR, ignore_errors=True)


atexit.register(_cleanup_test_user_dir)

# 把被移入子包的模块目录加入导入路径，使测试与脚本模式的导入名一致。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool" / "divine_treasure"))

# 手动调试脚本：不参与 unittest 自动发现（登记文件名去掉扩展名）。这类脚本读取本机截图、
# 弹窗显示或接管键鼠，自动执行没有意义甚至阻塞；需要时用 python test/<文件名>.py 手动运行。
MANUAL_TESTS = {"test_rd"}


def load_tests(loader, tests, pattern):
    """从本包收集测试，跳过 MANUAL_TESTS 中登记的手动脚本。

    本包定义 load_tests 后，unittest 会把整个包的发现工作交给它（见
    unittest.loader 的 _find_test_path）。这里只替换文件名过滤规则，其余发现
    流程仍由 loader.discover() 完成，以保留逐文件的导入错误处理、文件名与路径
    校验、排序行为。

    Args:
        loader: unittest 使用的 TestLoader。
        tests: 已从本包 __init__ 载入的测试；本包没有测试类，恒为空。
        pattern: 自动发现使用的文件名模式，对应 -p 参数。

    Returns:
        本包下除手动脚本外的全部测试。
    """
    previous_match_path = loader._match_path

    def match_path(path, full_path, pattern):
        if Path(path).stem in MANUAL_TESTS:
            return False
        return previous_match_path(path, full_path, pattern)

    loader._match_path = match_path
    try:
        # 此时本包已在 loader 的 _loading_packages 中，discover 会跳过包自身、只递归内容。
        return loader.discover(str(Path(__file__).resolve().parent), pattern)
    finally:
        loader._match_path = previous_match_path
