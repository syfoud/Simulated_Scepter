"""任务管理器风格的进程资源卡片，后台采样并保留一分钟曲线。"""

import os
import time
from collections import deque
from datetime import datetime
from threading import Event

from PyQt5.QtCore import QPointF, QRectF, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tool.gui.appearance import GlassPanel
from tool.log import CUS_LOGGER
from tool.process_metrics import ProcessMetrics, ResourceSample


def format_bytes(value):
    """格式化容量或速率；缺失数据与真实的零值分开显示。"""
    if value is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024


def format_percent(value):
    """保留低于显示精度的真实占用，避免非零值看上去始终为零。"""
    return "<0.1%" if 0 < value < 0.1 else f"{value:.1f}%"


def format_share(value, total):
    """格式化真实容量占比；缺少分母时留空，零容量不伪装成零占用。"""
    if value is None or total is None or total <= 0:
        return "—"
    return format_percent(value / total * 100)


def format_usage(value, total):
    """显示用量、对应总容量与占比。"""
    return f"{format_bytes(value)} / {format_bytes(total)} · {format_share(value, total)}"


class ResourceSampler(QThread):
    """性能计数器只在此线程使用；隐藏窗口或切页后暂停采集。"""

    sampled = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.active = Event()
        self.stopping = Event()
        self.refresh = Event()

    def run(self):
        metrics = None
        try:
            while not self.stopping.is_set():
                if not self.active.wait(0.5):
                    continue
                if self.stopping.is_set():
                    break
                started = time.monotonic()
                if metrics is None:
                    metrics = ProcessMetrics()
                if self.refresh.is_set():
                    metrics.reset_rates()
                    self.refresh.clear()
                self.sampled.emit(metrics.sample())
                if self.stopping.wait(max(0, 1 - (time.monotonic() - started))):
                    break
        except Exception as error:
            CUS_LOGGER.exception("资源监测已停止，任务运行不受影响")
            self.sampled.emit(ResourceSample(error=f"资源监测已停止：{error}", gpu_error="资源监测已停止"))
        finally:
            if metrics is not None:
                metrics.close()

    @pyqtSlot()
    def shutdown(self):
        self.stopping.set()
        self.active.set()
        self.wait()


class ResourceGraph(QWidget):
    """固定一分钟视窗，None 留空而不是绘制成零占用。"""

    def __init__(self, color, percent=False, parent=None):
        super().__init__(parent)
        self.color = color
        self.percent = percent
        self.values = deque(maxlen=60)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def append(self, value):
        self.values.append(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        light = QApplication.palette().color(QPalette.Window).lightness() >= 128
        color = QColor(self.color)
        if light:
            color = color.darker(135)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.fillRect(rect, QColor(color.red(), color.green(), color.blue(), 12))
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 55), 1))
        painter.drawRect(rect)
        for fraction in (1 / 3, 2 / 3):
            painter.drawLine(QPointF(rect.left(), rect.top() + rect.height() * fraction),
                             QPointF(rect.right(), rect.top() + rect.height() * fraction))
        ceiling = max((value for value in self.values if value is not None), default=1)
        # CPU 按大核折算，含小核/超线程的程序总时间可能超过大核容量，曲线不能截断。
        ceiling = max(ceiling, 100 if self.percent else 1)
        path = QPainterPath()
        connected = False
        for index, value in enumerate(self.values):
            if value is None:
                connected = False
                continue
            point = QPointF(rect.right() - (len(self.values) - 1 - index) / 59 * rect.width(),
                            rect.bottom() - min(value / ceiling, 1) * rect.height())
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setPen(QPen(color, 1.5))
        painter.drawPath(path)


class ResourcePanel(GlassPanel):
    """展示本程序的 CPU、工作集、I/O 与 GPU/显存，不混入整机数据。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sampler = None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("程序资源", self)
        title.setProperty("role", "heading")
        header.addWidget(title)
        header.addStretch()
        self.caption = QLabel(f"PID {os.getpid()}", self)
        self.caption.setProperty("role", "muted")
        header.addWidget(self.caption)
        layout.addLayout(header)
        self.setToolTip("仅统计当前程序进程，每秒刷新；曲线显示最近 60 秒。")
        self.graphs = {}
        self.labels = {}
        self.values = {}
        self.details = {}
        for key, title, color, tooltip in (
            ("cpu", "CPU（大核）", "#75aedb", "程序全部线程的 CPU 时间，按物理大核数折算；1 核表示每秒消耗 1 秒 CPU 时间。分母不计小核或超线程，不限制系统调度；总时间仍包含在小核运行的线程，因此可能超过 100%。没有大小核区分的 CPU 使用物理核心数。"),
            ("memory", "内存", "#bb8dd1", "主值采用任务管理器默认的专用工作集，占比以系统物理内存总量为分母；提交量占比以系统提交上限为分母。不是内存读写带宽。"),
            ("io", "I/O 读写", "#d2ae72", "当前进程的读写传输速率，包含文件、设备等 I/O；缓存和其他 I/O 也会计入，不代表物理磁盘吞吐或内存带宽。"),
            ("gpu", "GPU", "#91bdaf", "当前进程最忙 GPU 引擎的占用；显存显示用量 / 容量及占比，仅汇总本进程涉及的显卡。共享容量是驱动允许使用的系统内存上限，不是已经预留的显存。"),
        ):
            row = QWidget(self)
            row.setToolTip(tooltip)
            content = QVBoxLayout(row)
            content.setContentsMargins(0, 0, 0, 0)
            content.setSpacing(4)
            graph = ResourceGraph(color, key in ("cpu", "gpu"), row)
            text = QVBoxLayout()
            text.setSpacing(2)
            heading = QHBoxLayout()
            heading.setSpacing(4)
            label = QLabel(title, row)
            label.setProperty("role", "muted")
            self.labels[key] = label
            heading.addWidget(label)
            value = QLabel("—", row)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setProperty("role", "resource_value")
            heading.addWidget(value, 1)
            text.addLayout(heading)
            detail = QLabel(row)
            detail.setProperty("role", "muted")
            detail.setWordWrap(True)
            detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            text.addWidget(detail)
            self.details[key] = detail
            content.addLayout(text)
            content.addWidget(graph)
            layout.addWidget(row)
            self.graphs[key] = graph
            self.values[key] = value
        layout.addStretch()
        self.updated = QLabel("等待首次采样…", self)
        self.updated.setProperty("role", "muted")
        layout.addWidget(self.updated)

    def start_monitor(self):
        """正式窗口加载完成后才创建线程，单独加载 UI 不产生采样副作用。"""
        self.sampler = ResourceSampler(QApplication.instance())
        self.sampler.sampled.connect(self.update_sample)
        self.destroyed.connect(self.sampler.shutdown)
        QApplication.instance().aboutToQuit.connect(self.sampler.shutdown)
        self.sampler.finished.connect(self.sampler.deleteLater)
        if self.isVisible():
            self.sampler.refresh.set()
            self.sampler.active.set()
        self.sampler.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self.sampler is not None:
            # 隐藏期间没有逐秒数据，清空曲线避免把长时间间隔伪装成连续一分钟。
            for graph in self.graphs.values():
                graph.values.clear()
            self.sampler.refresh.set()
            self.sampler.active.set()

    def hideEvent(self, event):
        if self.sampler is not None:
            self.sampler.active.clear()
        super().hideEvent(event)

    @pyqtSlot(object)
    def update_sample(self, sample):
        self.updated.setText("采集暂不可用" if sample.error else f"每秒刷新 · 更新 {datetime.fromtimestamp(sample.sample_time):%H:%M:%S}")
        self.updated.setToolTip(sample.error)
        self.values["cpu"].setText(format_percent(sample.cpu) if sample.cpu is not None else ("不可用" if sample.error or sample.cpu_error else "采样中"))
        self.values["cpu"].setToolTip(sample.cpu_error)
        used_cores = "—"
        if sample.cpu_usage is not None:
            used_cores = "<0.01" if 0 < sample.cpu_usage < 0.01 else f"{sample.cpu_usage:.2f}"
        self.details["cpu"].setText(f"大核折算 {used_cores} / {sample.cpu_cores if sample.cpu_cores is not None else '—'} 核")
        memory_title = "内存" if sample.private_memory is not None else "物理内存"
        if self.labels["memory"].text() != memory_title:
            self.graphs["memory"].values.clear()
        self.labels["memory"].setText(memory_title)
        memory = sample.private_memory if sample.private_memory is not None else sample.memory
        self.values["memory"].setText(f"{format_bytes(memory)} · {format_share(memory, sample.memory_total)}")
        self.values["memory"].setToolTip(f"专用工作集 {format_bytes(sample.private_memory)}\n物理工作集 {format_bytes(sample.memory)}\n提交量 {format_usage(sample.commit, sample.commit_limit)}\n{sample.memory_error}")
        self.details["memory"].setText(f"总内存 {format_bytes(sample.memory_total)}\n物理工作集 {format_bytes(sample.memory)}\n提交 {format_bytes(sample.commit)} · {format_share(sample.commit, sample.commit_limit)}")
        self.values["io"].setText("读 " + format_bytes(sample.read) + ("/s" if sample.read is not None else ""))
        self.details["io"].setText("写 " + format_bytes(sample.write) + ("/s" if sample.write is not None else ""))
        if sample.gpu is not None:
            gpu_text = format_percent(sample.gpu)
        elif sample.gpu_engine:
            gpu_text = "采样中"
        else:
            gpu_text = "不可用" if sample.gpu_error else "未使用"
        self.values["gpu"].setText(gpu_text)
        self.values["gpu"].setToolTip("\n".join(filter(None, [sample.gpu_error, sample.capacity_error])))
        context = f"引擎 {sample.gpu_engine}" if sample.gpu_engine else "未发现本进程 GPU 上下文"
        self.details["gpu"].setText(f"{context}\n专用 {format_usage(sample.dedicated, sample.dedicated_total)}\n共享 {format_usage(sample.shared, sample.shared_total)}")
        self.details["gpu"].setToolTip(sample.capacity_error)
        for detail in self.details.values():
            # 新数据增加行数时立即更新最小高度，避免布局仍按首次空文本的单行高度裁切。
            detail.setMinimumHeight(detail.heightForWidth(max(1, detail.width())))
        self.graphs["cpu"].append(sample.cpu)
        self.graphs["memory"].append(memory)
        self.graphs["io"].append(None if sample.read is None or sample.write is None else sample.read + sample.write)
        self.graphs["gpu"].append(sample.gpu)
