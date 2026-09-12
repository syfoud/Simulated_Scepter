"""测试包：把被移入子包的模块目录加入导入路径，使测试与脚本模式的导入名一致。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool" / "divine_treasure"))

