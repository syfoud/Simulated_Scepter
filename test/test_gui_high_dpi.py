"""验证高 DPI 下界面保持固定像素尺寸，右侧栏内容不被裁切。

界面按 96 DPI 的固定像素设计（UI.ui 的栏宽、qss 的 padding 都是 px），字号也必须
用 px：改成 pt 后字号会随屏幕真实 DPI 放大 2 倍（Windows 200%），固定 264 像素宽的
「运行概览」「程序资源」两栏文字就会被裁掉。检查放在全新进程里，用 QT_FONT_DPI=192
模拟 200% 缩放下的字体 DPI，确认字号和栏宽都不随 DPI 变化。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]

# 子进程里先把日志与图片目录改到临时位置，再导入 new_gui 并加载真实 UI.ui 量尺寸。
PROBE = """
import os

import route

scratch = {scratch!r}
route.PATHS["logs"] = os.path.join(scratch, "logs")
images = os.path.join(scratch, "imgs")
os.makedirs(images, exist_ok=True)
route.PATHS["image"] = images

import new_gui  # 导入入口模块并初始化界面资源

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow

from tool.gui.appearance import apply_appearance

app = QApplication.instance()
apply_appearance("dark")
window = QMainWindow()
uic.loadUi(os.path.join(route.PATHS["ui"], "UI.ui"), window)
window.resize(1240, 760)
window.show()
app.processEvents()

print("FONT_PIXEL_SIZE", app.font().pixelSize())
print("HEADING_WIDTH", window.Label_BaseConfig.sizeHint().width())
print("SIDE_WIDTH", window.side_panel.width())
print("SIDE_MIN_WIDTH", window.sidebar_contents.minimumSizeHint().width())
print("RESOURCE_MIN_WIDTH", window.resource_panel.minimumSizeHint().width())
scroll = window.control_scroll
print("HSCROLL_AS_NEEDED", scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded)

# 模拟字号放大后内容超宽：应能水平滚动，而不是把右侧文字直接裁掉。
scroll.widget().setMinimumWidth(600)
app.processEvents()
print("HSCROLL_VISIBLE", scroll.horizontalScrollBar().isVisible())
window.close()
"""


class HighDpiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "probe.txt"
            env = dict(
                os.environ,
                QT_QPA_PLATFORM="offscreen",
                QT_FONT_DPI="192",
                SIMS_TEST_LOG_PREFIX="test_",
            )
            with output.open("w", encoding="utf-8") as sink:
                cls.completed = subprocess.run(
                    [sys.executable, "-c", PROBE.format(scratch=folder)],
                    cwd=ROOT,
                    env=env,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                )
            text = output.read_text(encoding="utf-8", errors="replace")
        cls.values = {}
        for line in text.splitlines():
            key, _, value = line.partition(" ")
            if value in ("True", "False") or value.isdigit():
                cls.values[key] = value if value in ("True", "False") else int(value)
        cls.output = text

    def value(self, key):
        self.assertEqual(self.completed.returncode, 0, self.output)
        self.assertIn(key, self.values, self.output)
        return self.values[key]

    def test_font_stays_pixel_based_on_high_dpi(self):
        """字号用 px，屏幕 192 DPI 时不应被放大（pt 会放大到 2 倍）。"""
        self.assertGreater(self.value("FONT_PIXEL_SIZE"), 0)
        self.assertLessEqual(self.value("HEADING_WIDTH"), 100)

    def test_side_panels_fit_fixed_width_on_high_dpi(self):
        """固定宽度的两栏内容在 200% 缩放字体 DPI 下仍能放下，不被裁切。"""
        self.assertLessEqual(self.value("SIDE_MIN_WIDTH"), self.value("SIDE_WIDTH"))
        self.assertLessEqual(self.value("RESOURCE_MIN_WIDTH"), self.value("SIDE_WIDTH"))

    def test_sidebar_allows_horizontal_scroll_when_content_overflows(self):
        """侧栏内容超宽时应出现水平滚动条，而不是把右侧文字直接裁掉。"""
        self.assertTrue(self.value("HSCROLL_AS_NEEDED"))
        self.assertTrue(self.value("HSCROLL_VISIBLE"))
