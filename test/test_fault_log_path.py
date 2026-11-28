"""启动阶段崩溃转储的位置：自提权后工作目录会变，路径不能依赖启动目录。"""

import unittest
from pathlib import Path

NEW_GUI = Path(__file__).resolve().parents[1] / "new_gui.py"


class FaultLogPathTests(unittest.TestCase):
    """检查崩溃转储固定写到项目 logs 目录。"""

    def test_crash_dump_uses_project_logs(self):
        """提权实例的 cwd 是 C:\\Windows\\System32，相对路径会让启动阶段直接抛 FileNotFoundError。"""
        source = NEW_GUI.read_text(encoding="utf-8")
        self.assertIn('os.path.join(PATHS["logs"], "crash_dump.txt")', source)
        self.assertNotIn('open("logs/crash_dump.txt"', source)
