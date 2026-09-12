"""差分宇宙神赐珍宝子包：面具流程与图鉴采集（入场入口仍在仓库根目录）。"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    # 包内脚本被直接运行（如 --worker 子进程）时，也要能导入根目录的入口模块。
    sys.path.insert(0, ROOT)
