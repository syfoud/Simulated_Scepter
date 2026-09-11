"""差分宇宙神赐珍宝子包。"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)  # 直接运行包内脚本时也能导入仓库根目录的入口模块
