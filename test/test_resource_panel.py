"""离屏验证资源卡片的数据展示、后台采样与销毁清理。"""

import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from tool.gui.appearance import apply_appearance
from tool.gui.resource_panel import (
    ResourcePanel,
    format_bytes,
    format_percent,
    format_share,
)
from tool.process_metrics import ResourceSample


class ResourcePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        apply_appearance()
        self.panel = ResourcePanel()
        self.panel.resize(264, self.panel.sizeHint().height())
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def wait_text(self, text):
        for _ in range(50):
            if self.panel.values["cpu"].text() == text:
                return
            QTest.qWait(20)
        self.fail(f"未显示预期的 CPU 采样：{text}")

    def test_values_units_and_unavailable_gpu_remain_distinct_from_zero(self):
        self.panel.update_sample(ResourceSample(cpu=2.5, cpu_usage=0.15, cpu_cores=6,
                                                memory=256 * 1024**2, memory_total=16 * 1024**3,
                                                commit=384 * 1024**2, commit_limit=32 * 1024**3,
                                                read=1024, write=0, gpu=7,
                                                dedicated=32 * 1024**2, dedicated_total=8 * 1024**3,
                                                shared=8 * 1024**2, shared_total=8 * 1024**3))
        self.assertEqual(self.panel.values["cpu"].text(), "2.5%")
        self.assertIn("0.15 / 6", self.panel.details["cpu"].text())
        self.assertEqual(self.panel.values["memory"].text(), "256.0 MB · 1.6%")
        self.assertIn("总内存 16.0 GB", self.panel.details["memory"].text())
        self.assertIn("提交 384.0 MB · 1.2%", self.panel.details["memory"].text())
        self.assertEqual(self.panel.values["io"].text(), "读 1.0 KB/s")
        self.assertEqual(self.panel.details["io"].text(), "写 0 B/s")
        self.assertIn("32.0 MB / 8.0 GB · 0.4%", self.panel.details["gpu"].text())
        self.assertIn("384.0 MB", self.panel.values["memory"].toolTip())
        self.panel.update_sample(ResourceSample(gpu_error="驱动未提供计数器"))
        self.assertEqual(self.panel.values["gpu"].text(), "不可用")
        self.assertIn("驱动", self.panel.values["gpu"].toolTip())
        self.assertIsNone(self.panel.graphs["gpu"].values[-1])
        self.assertEqual(format_bytes(None), "—")
        self.assertEqual(format_bytes(0), "0 B")

    def test_private_memory_and_small_loads_are_visible_with_matching_scope(self):
        self.panel.update_sample(ResourceSample(cpu=0.025, gpu=0.03, private_memory=128 * 1024**2,
                                                memory=256 * 1024**2, commit=384 * 1024**2,
                                                gpu_engine="3D", dedicated=1024, shared=2048))
        self.assertEqual(self.panel.values["cpu"].text(), "<0.1%")
        self.assertEqual(self.panel.values["gpu"].text(), "<0.1%")
        self.assertEqual(self.panel.values["memory"].text(), "128.0 MB · —")
        self.assertIn("256.0 MB", self.panel.details["memory"].text())
        self.assertIn("3D", self.panel.details["gpu"].text())
        self.assertIn(f"PID {os.getpid()}", self.panel.caption.text())
        self.assertIn("更新", self.panel.updated.text())
        self.assertEqual(format_percent(0), "0.0%")
        self.panel.update_sample(ResourceSample(gpu_engine="3D"))
        self.assertEqual(self.panel.values["gpu"].text(), "采样中")
        self.panel.update_sample(ResourceSample())
        self.assertEqual(self.panel.values["gpu"].text(), "未使用")

    def test_unknown_or_zero_capacity_never_becomes_a_fabricated_zero_percent(self):
        self.assertEqual(format_share(0, 1024), "0.0%")
        self.assertEqual(format_share(1, 1024**3), "<0.1%")
        for used, total in ((1024, None), (1024, 0), (None, 1024), (0, 0)):
            self.assertEqual(format_share(used, total), "—")
        self.panel.update_sample(ResourceSample(cpu_usage=1, cpu_error="大核读取失败", memory=1024,
                                                dedicated=1024, capacity_error="显存容量未匹配"))
        self.assertEqual(self.panel.values["cpu"].text(), "不可用")
        self.assertIn("1.00 / —", self.panel.details["cpu"].text())
        self.assertEqual(self.panel.values["memory"].text(), "1.0 KB · —")
        self.assertIn("1.0 KB / — · —", self.panel.details["gpu"].text())
        self.assertIn("未匹配", self.panel.details["gpu"].toolTip())

    def test_history_is_bounded_and_both_palettes_render_without_clipping(self):
        for index in range(90):
            self.panel.update_sample(ResourceSample(cpu=index, cpu_usage=5.34, cpu_cores=6,
                                                    memory=1024**3, memory_total=64 * 1024**3,
                                                    read=1024, write=2048, gpu=10, gpu_engine="Compute_0",
                                                    dedicated=1024**3, dedicated_total=12 * 1024**3,
                                                    shared=1024**3, shared_total=32 * 1024**3))
        self.assertEqual(len(self.panel.graphs["cpu"].values), 60)
        for theme in ("dark", "light"):
            apply_appearance(theme)
            self.panel.resize(264, self.panel.sizeHint().height())
            self.app.processEvents()
            self.assertFalse(self.panel.grab().isNull())
            for label in list(self.panel.values.values()) + list(self.panel.details.values()):
                self.assertGreaterEqual(label.height(), label.sizeHint().height())
                self.assertGreaterEqual(label.width(), label.minimumSizeHint().width())

    def test_sampling_runs_in_background_pauses_when_hidden_and_releases_on_destruction(self):
        calls = []
        collector = Mock()
        collector.sample.side_effect = lambda: calls.append(threading.get_ident()) or ResourceSample(cpu=7.5, memory=1024)
        with patch("tool.gui.resource_panel.ProcessMetrics", return_value=collector):
            self.panel.start_monitor()
            sampler = self.panel.sampler
            self.wait_text("7.5%")
            self.assertNotEqual(calls[0], threading.get_ident())
            self.panel.hide()
            count = len(calls)
            QTest.qWait(1150)
            self.assertEqual(len(calls), count)
            self.panel.show()
            for _ in range(50):
                if len(calls) > count:
                    break
                QTest.qWait(20)
            self.assertGreater(len(calls), count)
            self.panel.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(sip.isdeleted(sampler) or not sampler.isRunning())
            collector.close.assert_called_once()
            # tearDown 仍需一个有效的 QWidget。
            self.panel = ResourcePanel()

    def test_unexpected_sampling_failure_is_reported_and_releases_collector(self):
        collector = Mock()
        collector.sample.side_effect = RuntimeError("采样中断")
        with patch("tool.gui.resource_panel.ProcessMetrics", return_value=collector), patch("tool.gui.resource_panel.CUS_LOGGER") as logger:
            self.panel.start_monitor()
            for _ in range(50):
                if "不可用" in self.panel.updated.text():
                    break
                QTest.qWait(20)
            self.assertIn("采样中断", self.panel.updated.toolTip())
            self.assertEqual(self.panel.values["cpu"].text(), "不可用")
            logger.exception.assert_called_once()
            collector.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
