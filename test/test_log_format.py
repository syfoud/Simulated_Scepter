"""验证日志位置使用项目相对路径，并支持在行尾追加调用者位置。"""

import logging
import os
import unittest

from route import PATHS
from tool.log import CusLogFormatter, _relative_source_path


class RelativeSourcePathTests(unittest.TestCase):
    def test_project_file_is_relative_to_root(self):
        """项目内文件输出相对仓库根目录的路径，分隔符统一为正斜杠。"""
        path = os.path.join(PATHS["root"], "core", "any_fate", "engine.py")
        self.assertEqual(_relative_source_path(path), "core/any_fate/engine.py")

    def test_external_file_falls_back_to_basename(self):
        """项目外路径（虚拟环境、标准库）仍然只显示文件名。"""
        self.assertEqual(
            _relative_source_path(r"C:\Python\Lib\site-packages\PyQt5\QtCore.py"),
            "QtCore.py",
        )

    def test_pseudo_path_is_kept(self):
        """exec/compile 产生的伪路径原样保留。"""
        self.assertEqual(_relative_source_path("<string>"), "<string>")


class CusLogFormatterTests(unittest.TestCase):
    FORMAT = "%(levelname)s [%(relpath)s:%(lineno)d] %(message)s%(caller_suffix)s"

    def make_record(self, caller=None):
        record = logging.LogRecord(
            "my customize logger", logging.DEBUG,
            os.path.join(PATHS["root"], "core", "any_fate", "engine.py"), 42,
            "消息", None, None)
        if caller is not None:
            record.caller = caller
        return record

    def test_location_uses_relative_path(self):
        formatted = CusLogFormatter(self.FORMAT).format(self.make_record())
        self.assertIn("[core/any_fate/engine.py:42]", formatted)
        self.assertNotIn("\\", formatted)

    def test_caller_is_appended(self):
        """extra 里的 caller 会追加到行尾，格式与业务日志一致。"""
        record = self.make_record("core/any_fate/engine.py:1123")
        formatted = CusLogFormatter(self.FORMAT).format(record)
        self.assertTrue(formatted.endswith("，调用者[core/any_fate/engine.py:1123]"))

    def test_no_caller_keeps_line_unchanged(self):
        """没有 caller 时不追加任何内容。"""
        formatted = CusLogFormatter(self.FORMAT).format(self.make_record())
        self.assertNotIn("调用者", formatted)


if __name__ == "__main__":
    unittest.main()
