"""运行计数文件（user/backup/count.txt）按行区分内核，互不覆盖。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from importing import load_img

# 内核在导入期会读图像记忆切片，必须先预热图片缓存
load_img()

from core.any_fate.text_key import FATES  # noqa: E402
from core.any_fate.utils import FateUtils  # noqa: E402
from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402


def make_engine(count_line, count=0):
    """只装计数功能所需字段的替身：跳过 __init__ 的窗口与录像初始化。"""
    engine = object.__new__(FateUtils)
    engine.count_line = count_line
    engine.count = count
    return engine


class CountLineTest(unittest.TestCase):
    def test_each_kernel_owns_a_different_line(self):
        self.assertEqual(FateUtils.count_line, 2)
        self.assertEqual(IronBloodUniverse.count_line, 0)
        self.assertEqual(FingerSnap.count_line, 1)

    def test_every_kernel_can_resolve_its_own_fate(self):
        """三个内核共用 FATES 顺序表；下标错位会让祝福优先级整体偏移。"""
        for fate in ("毁灭", "丰饶", "巡猎"):
            self.assertIn(fate, FATES)


class UpdateCountTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.backup = Path(self.folder.name)
        self.paths = self.enterContext(patch.dict(
            "core.any_fate.utils.PATHS", {"backup": str(self.backup)}
        ))
        self.file = self.backup / "count.txt"

    def write_lines(self, lines):
        self.file.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    def read_lines(self):
        return [int(line) for line in self.file.read_text(encoding="utf-8").split()]

    def test_read_uses_the_configured_line(self):
        self.write_lines([5, 6, 7])
        for count_line, expected in ((0, 5), (1, 6), (2, 7)):
            with self.subTest(count_line=count_line):
                engine = make_engine(count_line)
                engine.update_count()
                self.assertEqual(engine.count, expected)

    def test_increment_writes_only_its_own_line(self):
        self.write_lines([5, 6, 7])
        engine = make_engine(1, count=6)

        engine.update_count(False)

        self.assertEqual(self.read_lines(), [5, 7, 7])
        self.assertEqual(engine.count, 7)

    def test_missing_file_is_created_with_zero_lines(self):
        engine = make_engine(2)

        engine.update_count()

        self.assertEqual(self.read_lines(), [0, 0, 0])
        self.assertEqual(engine.count, 0)

    def test_short_file_is_padded_before_writing(self):
        self.write_lines([9])
        engine = make_engine(2, count=0)

        engine.update_count(False)

        self.assertEqual(self.read_lines(), [9, 0, 1])
        self.assertEqual(engine.count, 1)


if __name__ == "__main__":
    unittest.main()
