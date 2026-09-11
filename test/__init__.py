"""测试包：把移动到 tool/divine_treasure 的模块目录加入导入路径。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool" / "divine_treasure"))
