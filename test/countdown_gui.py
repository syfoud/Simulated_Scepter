"""倒计时最大化模拟器 GUI。

启动方式：``python test/countdown_gui.py``。窗口先显示，识图与每个当前状态的
蒙特卡洛续采样均在后台线程运行。
"""

from __future__ import annotations

import os
import sys
import traceback

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

try:
    from .countdown_backend import (
        ALL_EFFECTS, CAMPAIGN_DEFAULT_TARGETS, CampaignProgress,
        CountdownSession, EFFECT_NAMES, MCConfig, MonteCarloController,
        PHASE_EFFECT, PHASE_PATH, PHASE_TARGET, PHASE_TERMINAL, format_action,
    )
    from .countdown_map_loader import default_map_paths, load_countdown_map
    from .countdown_dp import ExactCountdownDP
except ImportError:
    from countdown_backend import (
        ALL_EFFECTS, CAMPAIGN_DEFAULT_TARGETS, CampaignProgress,
        CountdownSession, EFFECT_NAMES, MCConfig, MonteCarloController,
        PHASE_EFFECT, PHASE_PATH, PHASE_TARGET, PHASE_TERMINAL, format_action,
    )
    from countdown_map_loader import default_map_paths, load_countdown_map
    from countdown_dp import ExactCountdownDP


PHASE_LABELS = {
    PHASE_EFFECT: "效果选择",
    PHASE_TARGET: "慈怀感染目标选择",
    PHASE_PATH: "路径选择",
    PHASE_TERMINAL: "本图结束",
}


def _effect_summary(observations, actions, locked_effect=None, target=None):
    observed = " → ".join(EFFECT_NAMES[value] for value in observations) or "--"
    chosen = " → ".join(format_action(PHASE_EFFECT, action) for action in actions)
    parts = [f"随机：{observed}"]
    if chosen:
        parts.append(f"操作：{chosen}")
    if locked_effect:
        suffix = f" → #{target}" if target is not None else ""
        parts.append(f"最终：{EFFECT_NAMES[locked_effect]}{suffix}")
    return "；".join(parts)


class MapLoadThread(QThread):
    progress_signal = pyqtSignal(int, int, str, int)
    loaded_signal = pyqtSignal(object, int, int)
    failed_signal = pyqtSignal(str, int)

    def __init__(self, image_path, plane, match_mode, generation):
        super().__init__()
        self.image_path, self.plane = image_path, plane
        self.match_mode, self.generation = match_mode, generation

    def run(self):
        try:
            prepared = load_countdown_map(
                self.image_path, self.plane, self.match_mode,
                lambda value, total, text: self.progress_signal.emit(
                    value, total, text, self.generation),
                self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.loaded_signal.emit(prepared, self.generation, self.plane)
        except Exception:
            if not self.isInterruptionRequested():
                self.failed_signal.emit(traceback.format_exc(), self.generation)


class RecommendationThread(QThread):
    progress_signal = pyqtSignal(int, int, str, int)
    done_signal = pyqtSignal(object, int)
    failed_signal = pyqtSignal(str, int)

    def __init__(self, controller, context, target, request_id):
        super().__init__()
        self.controller, self.context = controller, context
        self.target, self.request_id = target, request_id

    def run(self):
        try:
            result = self.controller.recommend(
                self.context, self.target,
                lambda value, total, text: self.progress_signal.emit(
                    value, total, text, self.request_id),
                self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.done_signal.emit(result, self.request_id)
        except Exception:
            if not self.isInterruptionRequested():
                self.failed_signal.emit(traceback.format_exc(), self.request_id)


class DPAnalysisThread(QThread):
    done_signal = pyqtSignal(object, int)
    failed_signal = pyqtSignal(str, int)

    def __init__(self, countdown_map, context, request_id):
        super().__init__()
        self.countdown_map, self.context = countdown_map, context
        self.request_id = request_id

    def run(self):
        try:
            result = ExactCountdownDP(
                self.countdown_map,
                cancelled=self.isInterruptionRequested).solve(self.context)
            if not self.isInterruptionRequested():
                self.done_signal.emit(result, self.request_id)
        except InterruptedError:
            pass
        except Exception:
            if not self.isInterruptionRequested():
                self.failed_signal.emit(traceback.format_exc(), self.request_id)


class MapCanvas(QWidget):
    image_dropped = pyqtSignal(str)
    node_clicked = pyqtSignal(int)
    NODE_RADIUS = 44.0
    NODE_LABELS = {
        "start": "起点", "head": "终点", "boss": "首领", "battle": "战斗",
        "bugbattle": "虫战", "elite": "精英", "event": "事件", "bugevent": "虫事件",
        "reward": "奖励", "trade": "交易", "wait": "等待", "adventure": "奇遇",
    }

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumSize(680, 500)
        self._pixmap = QPixmap()
        self._node_icons = {}
        self._type_icons = {}
        self._current_icon = QPixmap()
        self._node_radius, self._icon_size = self.NODE_RADIUS, 76
        self.prepared = self.state = self.context = self.recommendation = None
        self.historical_frame = None
        self._screen_nodes = {}

    def set_image(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError(f"无法显示图片: {path}")
        self._pixmap = pixmap
        self.update()

    def set_model(self, prepared):
        self.prepared = prepared
        self.set_image(prepared.image_path)
        self._node_icons.clear()
        self._type_icons.clear()
        for node in prepared.model.nodes:
            if not node.get("orig"):
                continue
            symbol_w, symbol_h = max(1, int(round(node.get("w", 50)))), max(1, int(round(node.get("h", 50))))
            margin = max(22, int(round(max(symbol_w, symbol_h) * 0.45)))
            width, height = symbol_w + margin * 2, symbol_h + margin * 2
            left = max(0, int(round(node["cx"] - width / 2)))
            top = max(0, int(round(node["cy"] - height / 2)))
            width, height = min(width, self._pixmap.width() - left), min(height, self._pixmap.height() - top)
            if width > 0 and height > 0:
                crop = self._pixmap.copy(left, top, width, height)
                if not crop.isNull():
                    icon = crop.scaled(76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._node_icons[int(node["idx"])] = icon
                    self._type_icons.setdefault(node.get("name"), icon)
        needed_types = {node.get("name") for node in prepared.model.nodes} - self._type_icons.keys()
        crop_dir = os.path.join(_PROJECT_ROOT, "test", "_node_crops")
        if os.path.isdir(crop_dir):
            for filename in sorted(os.listdir(crop_dir)):
                stem, extension = os.path.splitext(filename)
                if extension.lower() != ".png" or "_" not in stem:
                    continue
                node_type = stem.split("_", 1)[1]
                if node_type in needed_types:
                    icon = QPixmap(os.path.join(crop_dir, filename))
                    if not icon.isNull():
                        self._type_icons[node_type] = icon.scaled(
                            76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        needed_types.remove(node_type)
        icon_dir = os.path.join(_PROJECT_ROOT, "resource", "imgs", "gray_image", "node2")
        for node_type in needed_types:
            icon = QPixmap(os.path.join(icon_dir, f"{node_type}.png"))
            if not icon.isNull():
                self._type_icons[node_type] = icon.scaled(
                    76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._current_icon = QPixmap()
        if prepared.start_detected and prepared.start_crop_rect:
            x1, y1, x2, y2 = map(int, prepared.start_crop_rect)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(self._pixmap.width(), x2), min(self._pixmap.height(), y2)
            if x2 > x1 and y2 > y1:
                self._current_icon = self._pixmap.copy(x1, y1, x2 - x1, y2 - y1).scaled(
                    48, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def set_view(self, state=None, context=None, recommendation=None, frame=None):
        self.state, self.context = state, context
        self.recommendation, self.historical_frame = recommendation, frame
        self.update()

    def _draw_arrow(self, painter, start, end, color, width=3, dashed=False):
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        ux, uy = dx / length, dy / length
        offset = min(self._node_radius, max(0.0, (length - 12.0) / 2.0))
        start = QPointF(start.x() + ux * offset, start.y() + uy * offset)
        end = QPointF(end.x() - ux * offset, end.y() - uy * offset)
        painter.setPen(QPen(color, width, Qt.DashLine if dashed else Qt.SolidLine))
        painter.drawLine(start, end)
        left = QPointF(end.x() - ux * 14 - uy * 7, end.y() - uy * 14 + ux * 7)
        right = QPointF(end.x() - ux * 14 + uy * 7, end.y() - uy * 14 - ux * 7)
        painter.drawLine(end, left)
        painter.drawLine(end, right)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10131d"))
        if not self.prepared:
            painter.setPen(QColor("#8d93a8"))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "拖拽地图图片到这里" if self._pixmap.isNull() else "正在后台识别地图…")
            return
        nodes = self.prepared.model.nodes
        xs, ys = [float(node["cx"]) for node in nodes], [float(node["cy"]) for node in nodes]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        pad_x = max(70.0, min(130.0, self.width() * 0.12))
        pad_top = max(75.0, min(110.0, self.height() * 0.15))
        pad_bottom = max(65.0, min(95.0, self.height() * 0.13))
        self._screen_nodes = {int(node["idx"]): QPointF(
            pad_x + (0.5 if max_x == min_x else (float(node["cx"]) - min_x) / (max_x - min_x))
            * max(1.0, self.width() - pad_x * 2),
            pad_top + (0.5 if max_y == min_y else (float(node["cy"]) - min_y) / (max_y - min_y))
            * max(1.0, self.height() - pad_top - pad_bottom)) for node in nodes}
        points = tuple(self._screen_nodes.values())
        nearest = min(
            (((left.x() - right.x()) ** 2 + (left.y() - right.y()) ** 2) ** 0.5
             for index, left in enumerate(points) for right in points[:index]),
            default=118.0)
        self._node_radius = max(18.0, min(self.NODE_RADIUS, nearest / 2.0 - 14.0))
        self._icon_size = max(34, min(76, int(self._node_radius * 1.72)))
        current = self.state.node_idx if self.state else None
        current_column = self.prepared.model.columns.get(current, -1)
        options = set()
        reports = {}
        recommended = highest_win = None
        if self.context and self.recommendation and self.context.phase in (PHASE_TARGET, PHASE_PATH):
            reports = self.recommendation.reports
            options = {int(action) for action in reports if isinstance(action, int)}
            if isinstance(self.recommendation.recommended_action, int):
                recommended = int(self.recommendation.recommended_action)
            if isinstance(self.recommendation.highest_win_action, int):
                highest_win = int(self.recommendation.highest_win_action)

        painter.setPen(QPen(QColor("#454d61"), 2))
        for source, targets in self.prepared.model.edges.items():
            for target in targets:
                painter.drawLine(self._screen_nodes[source], self._screen_nodes[target])

        for node in nodes:
            idx = int(node["idx"])
            point = self._screen_nodes[idx]
            base_radius = self._node_radius
            uses_current_icon = idx == current and not self._current_icon.isNull()
            icon = (self._current_icon if uses_current_icon else
                    self._node_icons.get(idx, self._type_icons.get(node.get("name"))))
            if icon and not icon.isNull():
                limit = min(self._icon_size, 54) if uses_current_icon else self._icon_size
                scale = min(1.0, limit / max(icon.width(), icon.height()))
                shown = icon if scale == 1.0 else icon.scaled(
                    max(1, int(icon.width() * scale)), max(1, int(icon.height() * scale)),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(
                    int(point.x() - shown.width() / 2), int(point.y() - shown.height() / 2), shown)
            else:
                painter.setPen(QPen(QColor("#566078"), 2))
                painter.setBrush(QColor("#20283a"))
                painter.drawEllipse(point, 30, 30)
                painter.setPen(QColor("#e4e8f2"))
                painter.setFont(QFont("Microsoft YaHei", 9))
                painter.drawText(QRectF(point.x() - 35, point.y() - 10, 70, 20), Qt.AlignCenter,
                                 self.NODE_LABELS.get(node.get("name"), node.get("name", "?")))
            painter.setBrush(Qt.NoBrush)
            if not uses_current_icon:
                color = "#646b7c" if self.prepared.model.columns[idx] <= current_column else "#3c465c"
                painter.setPen(QPen(QColor(color), 1.5))
                painter.drawEllipse(point, base_radius, base_radius)
            if self.state and (self.state.infected >> idx) & 1:
                painter.setPen(QPen(QColor("#32e6e6"), 4))
                painter.drawEllipse(point, base_radius + 4, base_radius + 4)
            if idx in options:
                painter.setPen(QPen(QColor("#f0f2ff"), 2, Qt.DashLine))
                painter.drawEllipse(point, base_radius + 8, base_radius + 8)
            if idx == highest_win and idx != recommended:
                painter.setPen(QPen(QColor("#ffd54f"), 5))
                painter.drawEllipse(point, base_radius + 13, base_radius + 13)
            if idx == recommended:
                painter.setPen(QPen(QColor("#66ff8a"), 5))
                painter.drawEllipse(point, base_radius + 11, base_radius + 11)
            if idx == current and self._current_icon.isNull():
                painter.setPen(QPen(QColor("#42a5f5"), 5))
                painter.drawEllipse(point, base_radius + 17, base_radius + 17)
            painter.setPen(QColor("#d7dce8"))
            painter.setFont(QFont("Microsoft YaHei", 8))
            name = self.NODE_LABELS.get(node.get("name"), node.get("name", "?"))
            painter.drawText(QRectF(point.x() - 60, point.y() + base_radius + 3, 120, 18),
                             Qt.AlignCenter, f"#{idx} {name}  c{self.prepared.model.columns[idx]}")

        if self.historical_frame and current in self._screen_nodes:
            target = self.historical_frame.get("effect_target")
            if target in self._screen_nodes:
                self._draw_arrow(painter, self._screen_nodes[current],
                                 self._screen_nodes[target], QColor("#d66bff"), 3, True)
            actual = int(self.historical_frame["path"])
            if actual in self._screen_nodes:
                self._draw_arrow(painter, self._screen_nodes[current],
                                 self._screen_nodes[actual], QColor("#42a5f5"), 4)
        elif recommended in self._screen_nodes and current in self._screen_nodes:
            self._draw_arrow(
                painter, self._screen_nodes[current], self._screen_nodes[recommended],
                QColor("#66ff8a") if self.context.phase == PHASE_PATH else QColor("#d66bff"),
                4, self.context.phase == PHASE_TARGET)

        for idx, report in reports.items():
            point = self._screen_nodes[idx]
            label = f"均 {report.mean:.2f}"
            if report.win_rate is not None:
                label += f"  胜 {report.win_rate * 100:.4f}%"
            metrics = painter.fontMetrics()
            text_rect = metrics.boundingRect(label).adjusted(-5, -3, 5, 3)
            text_rect.moveCenter((point + QPointF(0, -self._node_radius - 26)).toPoint())
            painter.fillRect(text_rect, QColor(12, 16, 28, 220))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(text_rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._screen_nodes:
            return
        nearest = min(self._screen_nodes, key=lambda idx: (
            self._screen_nodes[idx].x() - event.pos().x()) ** 2
            + (self._screen_nodes[idx].y() - event.pos().y()) ** 2)
        point = self._screen_nodes[nearest]
        if (point.x() - event.pos().x()) ** 2 + (point.y() - event.pos().y()) ** 2 <= 55 ** 2:
            self.node_clicked.emit(nearest)

    def dragEnterEvent(self, event: QDragEnterEvent):
        urls = event.mimeData().urls()
        if urls and os.path.splitext(urls[0].toLocalFile())[1].lower() in (".png", ".jpg", ".jpeg", ".bmp"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        path = event.mimeData().urls()[0].toLocalFile()
        if os.path.isfile(path):
            self.image_dropped.emit(os.path.abspath(path))
            event.acceptProposedAction()


def _spin(minimum, maximum, value, step=1):
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setSingleStep(step)
    return widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("倒计时最大化模拟器 — 纯 MC 当前状态控制")
        self.resize(1500, 940)
        self.setMinimumSize(1180, 760)

        self.map_paths = list(default_map_paths())
        self.prepared = self.controller = self.session = self.recommendation = None
        self.campaign = None
        self.frame_recommendations = []
        self.view_index = 0
        self.map_thread = self.rec_thread = self.dp_thread = None
        self.generation = self.request_id = 0
        self.dp_request_id = 0
        self.dp_context = self.dp_result = None
        self.dp_cache = {}
        self.pending_dp = False
        self.pending_load = None
        self.pending_recommendation = False
        self.auto_pending = False
        self.cancel_requested = False

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)
        self.canvas = MapCanvas()
        self.canvas.image_dropped.connect(self._image_dropped)
        self.canvas.node_clicked.connect(self._node_clicked)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self._build_side_panel())
        splitter.setSizes([1050, 400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_operation_panel())

        self._set_path_lines()
        if os.path.isfile(self.map_paths[0]):
            self.canvas.set_image(self.map_paths[0])
        self._refresh_view()
        QTimer.singleShot(0, self.restart_simulation)

    def _build_toolbar(self):
        row = QHBoxLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("单图推演", "single")
        self.scope_combo.addItem("三位面完整仿真", "campaign")
        self.scope_combo.currentIndexChanged.connect(
            lambda _index: self.restart_simulation())
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("自主点选", "manual")
        self.mode_combo.addItem("MC 决策", "mc")
        self.mode_combo.addItem("纯随机（同时显示 MC 推荐）", "random")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.btn_load = QPushButton("选择当前地图")
        self.btn_load.clicked.connect(self._browse_current_map)
        self.btn_restart = QPushButton("重新识别 / 重置")
        self.btn_restart.clicked.connect(self.restart_simulation)
        self.btn_cancel = QPushButton("取消计算")
        self.btn_cancel.clicked.connect(self.cancel_work)
        self.btn_cancel.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(240)
        self.lbl_stage = QLabel("等待启动")
        row.addWidget(QLabel("范围")); row.addWidget(self.scope_combo)
        row.addWidget(QLabel("决策")); row.addWidget(self.mode_combo)
        row.addWidget(self.btn_load); row.addWidget(self.btn_restart)
        row.addWidget(self.btn_cancel)
        row.addStretch(1)
        row.addWidget(self.lbl_stage); row.addWidget(self.progress)
        return row

    def _build_side_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(370)
        scroll.setMaximumWidth(470)
        body = QWidget()
        layout = QVBoxLayout(body)

        status_box = QGroupBox("当前事实与 MC 建议")
        grid = QGridLayout(status_box)
        self.lbl_node_crop = QLabel()
        self.lbl_node_crop.setFixedSize(82, 82)
        self.lbl_node_crop.setAlignment(Qt.AlignCenter)
        self.lbl_node_crop.setStyleSheet("border:1px solid #536078; background:#111624;")
        self.lbl_phase = QLabel("--")
        self.lbl_effect = QLabel("--")
        self.lbl_effect.setWordWrap(True)
        self.lbl_score = QLabel("--")
        self.lbl_resource = QLabel("--")
        self.lbl_target = QLabel("--")
        self.lbl_recommend = QLabel("--")
        self.lbl_recommend.setWordWrap(True)
        self.lbl_recommend.setStyleSheet("color:#73f59a; font-weight:600;")
        self.lbl_win_leader = QLabel("")
        self.lbl_win_leader.setWordWrap(True)
        self.lbl_win_leader.setStyleSheet("color:#ffd54f;")
        grid.addWidget(self.lbl_node_crop, 0, 0, 3, 1)
        grid.addWidget(QLabel("阶段"), 0, 1); grid.addWidget(self.lbl_phase, 0, 2)
        grid.addWidget(QLabel("实际效果"), 1, 1); grid.addWidget(self.lbl_effect, 1, 2)
        grid.addWidget(QLabel("当前 CD"), 2, 1); grid.addWidget(self.lbl_score, 2, 2)
        grid.addWidget(QLabel("资源"), 3, 0); grid.addWidget(self.lbl_resource, 3, 1, 1, 2)
        grid.addWidget(QLabel("目标"), 4, 0); grid.addWidget(self.lbl_target, 4, 1, 1, 2)
        grid.addWidget(QLabel("MC 推荐"), 5, 0); grid.addWidget(self.lbl_recommend, 5, 1, 1, 2)
        grid.addWidget(self.lbl_win_leader, 6, 0, 1, 3)
        layout.addWidget(status_box)

        dp_box = QGroupBox("DP 理论上限（最有利随机结果）")
        dp_form = QFormLayout(dp_box)
        dp_note = QLabel("独立旁路分析，仅展示当前状态理论上限，不参与 MC 推荐。")
        dp_note.setWordWrap(True)
        dp_note.setStyleSheet("color:#9aa6bd;")
        self.lbl_dp_max = QLabel("--")
        self.lbl_dp_path = QLabel("--")
        self.lbl_dp_path.setWordWrap(True)
        self.lbl_dp_infections = QLabel("--")
        self.lbl_dp_infections.setWordWrap(True)
        self.lbl_dp_states = QLabel("--")
        self.lbl_dp_steps = QPlainTextEdit("--")
        self.lbl_dp_steps.setReadOnly(True)
        self.lbl_dp_steps.setMinimumHeight(300)
        self.lbl_dp_steps.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.lbl_dp_steps.setFont(QFont("Consolas", 9))
        self.lbl_dp_steps.setStyleSheet("background:#111624; padding:6px; border:1px solid #30394d;")
        dp_form.addRow(dp_note)
        dp_form.addRow("最大最终 CD", self.lbl_dp_max)
        dp_form.addRow("最佳路径", self.lbl_dp_path)
        dp_form.addRow("感染点", self.lbl_dp_infections)
        dp_form.addRow("DP 状态数", self.lbl_dp_states)
        dp_steps_title = QLabel("逐步动作与状态")
        dp_steps_title.setStyleSheet("font-weight:600;")
        dp_form.addRow(dp_steps_title)
        dp_form.addRow(self.lbl_dp_steps)
        layout.addWidget(dp_box)

        candidate_box = QGroupBox("当前所有候选（冻结贪心下游独立评价）")
        candidate_layout = QVBoxLayout(candidate_box)
        self.candidate_table = QTableWidget(0, 4)
        self.candidate_table.setHorizontalHeaderLabels(["动作", "平均最终CD", "胜率", "n"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.candidate_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.candidate_table.setSelectionMode(QTableWidget.NoSelection)
        candidate_layout.addWidget(self.candidate_table)
        layout.addWidget(candidate_box)

        params_box = QGroupBox("参数")
        form = QFormLayout(params_box)
        note = QLabel("资源、位面、初始CD和模板在重置后生效；目标与MC样本参数即时重采。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa6bd;")
        form.addRow(note)
        self.spin_plane = _spin(1, 3, 1)
        self.spin_cheat = _spin(0, 99, 2)
        self.spin_reroll = _spin(0, 999, 3)
        self.spin_countdown = _spin(-999, 9999, 15)
        self.spin_target = _spin(-999, 9999, int(CAMPAIGN_DEFAULT_TARGETS[0]))
        self.spin_control = _spin(100, 1_000_000, 10_000, 100)
        self.spin_evaluation = _spin(100, 1_000_000, 10_000, 100)
        self.spin_min_visits = _spin(1, 100_000, 200, 10)
        self.spin_seed = _spin(0, 2_147_483_647, 20260802)
        self.combo_match = QComboBox()
        self.combo_match.addItem("自动（旧模板优先）", 1)
        self.combo_match.addItem("新版节点模板", 2)
        for widget in (self.spin_target, self.spin_control, self.spin_evaluation,
                       self.spin_min_visits, self.spin_seed):
            widget.valueChanged.connect(self._recommendation_settings_changed)
        for label, widget in (
            ("位面", self.spin_plane), ("Cheat", self.spin_cheat),
            ("Reroll", self.spin_reroll), ("初始 CD", self.spin_countdown),
            ("目标 CD（仅评估胜率）", self.spin_target),
            ("当前状态控制样本", self.spin_control),
            ("候选独立评价总样本", self.spin_evaluation),
            ("每根动作最低访问", self.spin_min_visits),
            ("随机种子", self.spin_seed), ("识图模板", self.combo_match),
        ):
            form.addRow(label, widget)
        layout.addWidget(params_box)

        maps_box = QGroupBox("三个位面地图（当前位面支持拖拽替换）")
        maps_layout = QGridLayout(maps_box)
        self.path_lines = []
        for index in range(3):
            line = QLineEdit()
            line.setReadOnly(True)
            button = QPushButton("…")
            button.setFixedWidth(34)
            button.clicked.connect(lambda _checked=False, i=index: self._browse_map(i))
            self.path_lines.append(line)
            maps_layout.addWidget(QLabel(f"位面{index + 1}"), index, 0)
            maps_layout.addWidget(line, index, 1)
            maps_layout.addWidget(button, index, 2)
        layout.addWidget(maps_box)

        log_box = QGroupBox("诊断日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(800)
        self.log_view.setMinimumHeight(130)
        self.log_view.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_box)
        layout.addStretch(1)
        scroll.setWidget(body)
        return scroll

    def _build_operation_panel(self):
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        top = QHBoxLayout()
        self.lbl_operation = QLabel("当前操作：--")
        self.lbl_operation.setStyleSheet("font-weight:600; color:#8fd3ff;")
        self.combo_observed = QComboBox()
        for effect in ALL_EFFECTS:
            self.combo_observed.addItem(f"{EFFECT_NAMES[effect]} ({effect})", effect)
        self.btn_observed = QPushButton("同步实际效果")
        self.btn_observed.clicked.connect(self._sync_observed)
        self.btn_keep = QPushButton("keep")
        self.btn_keep.clicked.connect(lambda: self._manual_action("keep"))
        self.btn_reroll = QPushButton("reroll")
        self.btn_reroll.clicked.connect(lambda: self._manual_action("reroll"))
        self.combo_cheat = QComboBox()
        for effect in ALL_EFFECTS:
            self.combo_cheat.addItem(EFFECT_NAMES[effect], effect)
        self.btn_cheat = QPushButton("cheat →")
        self.btn_cheat.clicked.connect(self._manual_cheat)
        self.btn_apply_rec = QPushButton("采用 MC 推荐")
        self.btn_apply_rec.clicked.connect(self._apply_recommended)
        top.addWidget(self.lbl_operation)
        top.addStretch(1)
        top.addWidget(QLabel("实际随机结果")); top.addWidget(self.combo_observed)
        top.addWidget(self.btn_observed)
        top.addWidget(self.btn_keep); top.addWidget(self.btn_reroll)
        top.addWidget(self.btn_cheat); top.addWidget(self.combo_cheat)
        top.addWidget(self.btn_apply_rec)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        self.btn_prev = QPushButton("上一步")
        self.btn_prev.clicked.connect(lambda: self._move_history(-1))
        self.btn_next = QPushButton("下一步")
        self.btn_next.clicked.connect(lambda: self._move_history(1))
        self.btn_alternative = QPushButton("另一种可能性")
        self.btn_alternative.clicked.connect(self._another_possibility)
        self.btn_execute = QPushButton("执行当前一步")
        self.btn_execute.clicked.connect(self._execute_auto_step)
        self.lbl_frames = QLabel("1/1")
        bottom.addStretch(1)
        bottom.addWidget(self.btn_prev); bottom.addWidget(self.btn_next)
        bottom.addWidget(self.btn_alternative); bottom.addWidget(self.btn_execute)
        bottom.addWidget(self.lbl_frames)
        bottom.addStretch(1)
        layout.addLayout(bottom)
        return panel

    def _log(self, text):
        self.log_view.appendPlainText(str(text).rstrip())

    def _set_path_lines(self):
        for line, path in zip(self.path_lines, self.map_paths):
            line.setText(os.path.basename(path))
            line.setToolTip(path)

    def _browse_map(self, index):
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择位面{index + 1}地图", self.map_paths[index],
            "地图图片 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            path = os.path.abspath(path)
            if QPixmap(path).isNull():
                QMessageBox.warning(self, "地图无效", f"无法读取图片: {path}")
                return
            if index == self._current_plane() - 1:
                self._image_dropped(path)
            else:
                self.map_paths[index] = path
                self._set_path_lines()

    def _browse_current_map(self):
        self._browse_map(self._current_plane() - 1)

    def _image_dropped(self, path):
        path = os.path.abspath(path)
        if QPixmap(path).isNull():
            QMessageBox.warning(self, "地图无效", f"无法读取图片: {path}")
            return
        index = self._current_plane() - 1
        self._log(f"[地图] 正在验证位面{index + 1}候选图 {os.path.basename(path)}")
        self._start_map_load(path, index + 1, preserve_session=True)

    def _current_plane(self):
        return self.campaign.plane_index + 1 if self.campaign and not self.campaign.finished else self.spin_plane.value()

    def _mc_config(self):
        return MCConfig(
            control_rollouts=self.spin_control.value(),
            evaluation_rollouts=self.spin_evaluation.value(),
            min_visits=self.spin_min_visits.value(),
            seed=self.spin_seed.value(),
        ).normalized()

    def restart_simulation(self):
        self.cancel_work()
        self.campaign = None
        self.spin_plane.setEnabled(self.scope_combo.currentData() != "campaign")
        if self.scope_combo.currentData() == "campaign":
            self.campaign = CampaignProgress(
                CAMPAIGN_DEFAULT_TARGETS, self.spin_cheat.value(),
                self.spin_reroll.value(), self.spin_countdown.value())
            config = self.campaign.current_config()
            self.spin_plane.setValue(config["plane"])
            self._set_target(config["target_countdown"])
        self.frame_recommendations.clear()
        self.log_view.clear()
        self._log("[启动] GUI 已显示；开始在后台识别当前地图。")
        self._start_map_load()

    def _start_map_load(self, path=None, plane=None, preserve_session=False):
        self._cancel_dp_analysis()
        self.cancel_requested = False
        self.pending_recommendation = False
        self.generation += 1
        self.request_id += 1
        self.auto_pending = False
        generation = self.generation
        plane = int(plane or self._current_plane())
        path = os.path.abspath(path or self.map_paths[plane - 1])
        if not preserve_session:
            self.recommendation = self.prepared = self.controller = self.session = None
            self.frame_recommendations.clear()
            self.view_index = 0
        if self.rec_thread and self.rec_thread.isRunning():
            self.rec_thread.requestInterruption()
            self.pending_recommendation = bool(preserve_session)
        if self.map_thread and self.map_thread.isRunning():
            self.pending_load = (path, plane, preserve_session)
            self.map_thread.requestInterruption()
            self._update_controls()
            return
        self.pending_load = None
        if not os.path.isfile(path):
            self._map_failed(f"地图文件不存在: {path}", generation)
            return
        self._set_busy(True, "识别地图")
        thread = MapLoadThread(path, plane, self.combo_match.currentData(), generation)
        self.map_thread = thread
        thread.progress_signal.connect(self._map_progress_changed)
        thread.loaded_signal.connect(self._map_loaded)
        thread.failed_signal.connect(self._map_failed)
        thread.finished.connect(lambda current=thread: self._map_thread_finished(current))
        thread.start()

    def _map_thread_finished(self, thread):
        if self.map_thread is thread:
            self.map_thread = None
        thread.deleteLater()
        if self.pending_load:
            request = self.pending_load
            self.pending_load = None
            self.cancel_requested = False
            QTimer.singleShot(0, lambda args=request: self._start_map_load(*args))
        elif self.cancel_requested and not (self.rec_thread and self.rec_thread.isRunning()):
            self.cancel_requested = False
            self._set_busy(False, "已取消")
        elif (self.pending_recommendation and self.session
              and self.session.context.phase != PHASE_TERMINAL
              and not (self.rec_thread and self.rec_thread.isRunning())):
            self.pending_recommendation = False
            QTimer.singleShot(0, self._request_recommendation)
        else:
            self._update_controls()

    def _map_loaded(self, prepared, generation, plane):
        if generation != self.generation:
            return
        self.cancel_requested = False
        self.map_paths[plane - 1] = prepared.image_path
        self._set_path_lines()
        self.prepared = prepared
        self.recommendation = None
        self.canvas.set_model(prepared)
        self.frame_recommendations.clear()
        if self.campaign:
            config = self.campaign.current_config()
            cheat, reroll, countdown = config["cheat"], config["reroll"], config["entry_countdown"]
            self.spin_plane.setValue(config["plane"])
            self._set_target(config["target_countdown"])
        else:
            cheat, reroll, countdown = (
                self.spin_cheat.value(), self.spin_reroll.value(), self.spin_countdown.value())
        self.controller = MonteCarloController(prepared.model, self._mc_config())
        self.session = CountdownSession(
            prepared.model, cheat, reroll, countdown,
            self.spin_seed.value() + (plane - 1) * 1_000_003)
        self.view_index = 0
        self._log(f"[识图] 完成：{len(prepared.model.nodes)}个节点，"
                  f"起点#{prepared.model.start_idx}（{'检测' if prepared.start_detected else '最左回退'}），"
                  f"最长{prepared.model.longest_steps_from(prepared.model.start_idx)}步。")
        self._set_busy(False, "地图就绪")
        self._refresh_view()
        self._request_recommendation()

    def _map_failed(self, error, generation):
        if generation != self.generation:
            return
        self._set_busy(False, "识图失败")
        self._log(error)
        QMessageBox.critical(self, "地图识别失败", error.splitlines()[-1])

    def _request_recommendation(self):
        if not self.session or self.session.context.phase == PHASE_TERMINAL:
            self.pending_recommendation = False
            self._refresh_view()
            return
        if self.rec_thread and self.rec_thread.isRunning():
            self.pending_recommendation = True
            return
        self.pending_recommendation = False
        if self.dp_thread and self.dp_thread.isRunning():
            self.pending_dp = True
            self.dp_thread.requestInterruption()
        self.controller.config = self._mc_config()
        self.request_id += 1
        request_id = self.request_id
        self.recommendation = None
        self._set_busy(True, "当前状态采样")
        thread = RecommendationThread(
            self.controller, self.session.context, float(self.spin_target.value()), request_id)
        self.rec_thread = thread
        thread.progress_signal.connect(self._rec_progress_changed)
        thread.done_signal.connect(self._recommendation_done)
        thread.failed_signal.connect(self._recommendation_failed)
        thread.finished.connect(lambda current=thread: self._rec_thread_finished(current))
        thread.start()

    def _rec_thread_finished(self, thread):
        if self.rec_thread is thread:
            self.rec_thread = None
        thread.deleteLater()
        if self.cancel_requested and not (self.map_thread and self.map_thread.isRunning()):
            self.cancel_requested = False
            self._set_busy(False, "已取消")
        elif (self.pending_recommendation and self.session
              and self.session.context.phase != PHASE_TERMINAL
              and not (self.map_thread and self.map_thread.isRunning())):
            self.pending_recommendation = False
            QTimer.singleShot(0, self._request_recommendation)
        else:
            self._update_controls()
        if self.pending_dp and not self._is_busy():
            QTimer.singleShot(0, self._start_dp_analysis)
        if self.auto_pending and self.recommendation:
            QTimer.singleShot(0, self._continue_auto_step)

    def _recommendation_done(self, recommendation, request_id):
        if request_id != self.request_id or not self.session or recommendation.context != self.session.context:
            return
        self.cancel_requested = False
        self.recommendation = recommendation
        self._set_busy(False, "建议已更新")
        self._log(
            f"[MC] {PHASE_LABELS[recommendation.context.phase]} 推荐 "
            f"{format_action(recommendation.context.phase, recommendation.recommended_action)}；"
            f"控制{recommendation.control_rollouts:,}，独立评价{recommendation.evaluation_rollouts:,}。")
        self._refresh_view()
        if self.auto_pending:
            QTimer.singleShot(0, self._continue_auto_step)

    def _recommendation_failed(self, error, request_id):
        if request_id != self.request_id:
            return
        self.auto_pending = False
        self._set_busy(False, "采样失败")
        self._log(error)
        QMessageBox.critical(self, "MC 采样失败", error.splitlines()[-1])

    def _cancel_dp_analysis(self):
        self.dp_request_id += 1
        self.pending_dp = False
        self.dp_context = self.dp_result = None
        self.dp_cache.clear()
        if self.dp_thread and self.dp_thread.isRunning():
            self.dp_thread.requestInterruption()
        if hasattr(self, "lbl_dp_max"):
            self._render_dp_result()

    def _request_dp_analysis(self, context):
        if not self.prepared or context is None:
            self._cancel_dp_analysis()
            self._render_dp_result()
            return
        if context in self.dp_cache:
            self.dp_context, self.dp_result = context, self.dp_cache[context]
            self._render_dp_result()
            return
        if context == self.dp_context and (
                self.dp_result is not None
                or self.dp_thread and self.dp_thread.isRunning()):
            return
        self.dp_request_id += 1
        self.dp_context, self.dp_result = context, None
        self._render_dp_result()
        if self.dp_thread and self.dp_thread.isRunning():
            self.pending_dp = True
            self.dp_thread.requestInterruption()
            return
        self._start_dp_analysis()

    def _start_dp_analysis(self):
        if not self.prepared or self.dp_context is None:
            return
        if self._is_busy():
            self.pending_dp = True
            return
        self.pending_dp = False
        thread = DPAnalysisThread(
            self.prepared.model, self.dp_context, self.dp_request_id)
        self.dp_thread = thread
        thread.done_signal.connect(self._dp_analysis_done)
        thread.failed_signal.connect(self._dp_analysis_failed)
        thread.finished.connect(lambda current=thread: self._dp_thread_finished(current))
        thread.start()

    def _dp_analysis_done(self, result, request_id):
        if request_id != self.dp_request_id:
            return
        self.dp_result = result
        self.dp_cache[self.dp_context] = result
        self._render_dp_result()

    def _dp_analysis_failed(self, error, request_id):
        if request_id != self.dp_request_id:
            return
        self.dp_result = None
        self.lbl_dp_max.setText("计算失败")
        self.lbl_dp_path.setText(error.splitlines()[-1])
        self.lbl_dp_infections.setText("--")
        self.lbl_dp_states.setText("--")
        self.lbl_dp_steps.setPlainText("--")
        self._log(f"[DP] {error.splitlines()[-1]}")

    def _dp_thread_finished(self, thread):
        if self.dp_thread is thread:
            self.dp_thread = None
        thread.deleteLater()
        if self.pending_dp:
            QTimer.singleShot(0, self._start_dp_analysis)

    def _node_text(self, node_idx):
        if not self.prepared:
            return f"#{node_idx}"
        name = self.prepared.model.node_map.get(node_idx, {}).get("name", "")
        return f"{name}#{node_idx}" if name else f"#{node_idx}"

    def _dp_nodes_text(self, mask):
        nodes = [self._node_text(idx) for idx in self.prepared.model.node_map
                 if (mask >> idx) & 1]
        return "、".join(nodes) or "无"

    def _dp_step_text(self, number, step):
        effect = EFFECT_NAMES[step.effect]
        action = step.effect_action
        if isinstance(action, tuple) and action[0] == "cheat":
            action_text = f"cheat→{effect}"
        elif action == "reroll":
            action_text = f"reroll→最有利结果 {effect}"
        elif action == "keep":
            action_text = f"keep 当前效果 {effect}"
        elif action == "选择感染点":
            action_text = f"选择 {effect} 的感染点"
        else:
            action_text = f"效果已结算，仅选路（{effect}）"
        added = "、".join(map(self._node_text, step.infected_added)) or "无"
        return "\n".join((
            f"第{number}步  {self._node_text(step.node_idx)} → {self._node_text(step.next_node)}",
            f"  前：CD={step.countdown_before}  c={step.cheat_before} r={step.reroll_before}  "
            f"感染={self._dp_nodes_text(step.infected_before)}",
            f"  动作：{action_text}",
            f"  CD：{step.countdown_before} {step.countdown_delta:+d} → {step.countdown_after}"
            f"（效果 {step.effect_countdown_delta:+d}，移动 {step.move_countdown_delta:+d}）",
            f"  本步感染：{added}",
            f"  后：CD={step.countdown_after}  c={step.cheat_after} r={step.reroll_after}  "
            f"存活感染={self._dp_nodes_text(step.infected_after)}",
        ))

    def _render_dp_result(self):
        if not self.dp_context:
            values = ("--", "--", "--", "--", "--")
        elif not self.dp_result:
            values = ("计算中…", "--", "--", "--", "--")
        else:
            result = self.dp_result
            values = (
                str(result.max_countdown),
                " → ".join(map(self._node_text, result.path)),
                "、".join(map(self._node_text, result.infection_nodes)) or "无",
                f"{result.states_evaluated:,}",
                "\n\n".join(self._dp_step_text(index, step)
                              for index, step in enumerate(result.steps, 1)) or "已到终点",
            )
        for label, value in zip((self.lbl_dp_max, self.lbl_dp_path,
                                 self.lbl_dp_infections, self.lbl_dp_states), values):
            label.setText(value)
        self.lbl_dp_steps.setPlainText(values[-1])

    def _map_progress_changed(self, value, total, text, generation):
        if generation != self.generation:
            return
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(value)
        self.lbl_stage.setText(f"{text} {value:,}/{total:,}")

    def _rec_progress_changed(self, value, total, text, request_id):
        if request_id != self.request_id:
            return
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(value)
        self.lbl_stage.setText(f"{text} {value:,}/{total:,}")

    def _set_busy(self, busy, label):
        self.btn_cancel.setEnabled(busy)
        self.btn_restart.setEnabled(not busy)
        self.btn_load.setEnabled(not busy)
        self.lbl_stage.setText(label)
        if not busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if self.session else 0)
        self._update_controls()

    def cancel_work(self):
        self.pending_load = None
        self.pending_recommendation = False
        self.cancel_requested = bool(
            (self.map_thread and self.map_thread.isRunning())
            or (self.rec_thread and self.rec_thread.isRunning()))
        self.generation += int(bool(self.map_thread and self.map_thread.isRunning()))
        self.request_id += int(bool(self.rec_thread and self.rec_thread.isRunning()))
        if self.map_thread and self.map_thread.isRunning():
            self.map_thread.requestInterruption()
        if self.rec_thread and self.rec_thread.isRunning():
            self.rec_thread.requestInterruption()
        self.auto_pending = False
        self.btn_cancel.setEnabled(False)
        self.lbl_stage.setText("正在取消…" if self.cancel_requested else "已取消")
        if not self.cancel_requested:
            self.btn_restart.setEnabled(True)
            self.btn_load.setEnabled(True)
        self._update_controls()

    def _manual_action(self, action):
        if self.mode_combo.currentData() == "manual":
            self._apply_action(action)

    def _manual_cheat(self):
        self._manual_action(("cheat", self.combo_cheat.currentData()))

    def _sync_observed(self):
        if not self.session or self.session.context.phase != PHASE_EFFECT:
            return
        try:
            self.session.set_observed_effect(self.combo_observed.currentData())
            self.recommendation = None
            self._refresh_view()
            self._request_recommendation()
        except Exception as error:
            QMessageBox.warning(self, "无法同步效果", str(error))

    def _set_target(self, value):
        blocked = self.spin_target.blockSignals(True)
        self.spin_target.setValue(int(value))
        self.spin_target.blockSignals(blocked)

    def _recommendation_settings_changed(self):
        self.request_id += 1
        self.recommendation = None
        if not self.session or self.session.context.phase == PHASE_TERMINAL:
            self._refresh_view()
            return
        if self.rec_thread and self.rec_thread.isRunning():
            self.pending_recommendation = True
            self.rec_thread.requestInterruption()
        elif self.map_thread and self.map_thread.isRunning():
            self.pending_recommendation = True
        else:
            self._request_recommendation()
        self._refresh_view()

    def _node_clicked(self, node_idx):
        if (self.mode_combo.currentData() != "manual" or not self.session
                or self._is_busy() or self.view_index != len(self.session.frames)):
            return
        if self.session.context.phase not in (PHASE_TARGET, PHASE_PATH):
            self.lbl_stage.setText("当前应先选择 keep / cheat / reroll")
            return
        actions = self.controller.legal_actions(self.session.context)
        if node_idx not in actions:
            self.lbl_stage.setText(f"节点#{node_idx}不是当前{PHASE_LABELS[self.session.context.phase]}候选")
            return
        self._apply_action(node_idx)

    def _apply_recommended(self):
        if self.recommendation:
            self._apply_action(self.recommendation.recommended_action)

    def _apply_action(self, action):
        if not self.session or self._is_busy() or self.session.context.phase == PHASE_TERMINAL:
            return
        phase = self.session.context.phase
        path_recommendation = self.recommendation if phase == PHASE_PATH else None
        try:
            result = self.session.choose(action)
        except Exception as error:
            QMessageBox.warning(self, "动作不可执行", str(error))
            return
        self._log(f"[实际] {format_action(phase, action)}")
        self.recommendation = None
        if phase == PHASE_PATH:
            frame = result
            self.frame_recommendations.append(path_recommendation)
            self.view_index = len(self.session.frames)
            self._log(f"[帧{len(self.session.frames)}] #{frame['display_node']}→#{frame['path']}，"
                      f"CD={frame['state_after'].countdown}，"
                      f"c={frame['state_after'].cheat_rem} r={frame['state_after'].reroll_rem}")
        self._refresh_view()
        if self.session.context.phase == PHASE_TERMINAL:
            self.auto_pending = False
            self._finish_map()
        else:
            self._request_recommendation()

    def _execute_auto_step(self):
        if self.mode_combo.currentData() == "manual" or not self.session:
            return
        self.auto_pending = True
        if self.recommendation and not self._is_busy():
            self._continue_auto_step()
        elif not self._is_busy():
            self._request_recommendation()

    def _continue_auto_step(self):
        if self.mode_combo.currentData() == "manual":
            self.auto_pending = False
            return
        if not self.auto_pending or not self.recommendation or self._is_busy():
            return
        phase = self.session.context.phase
        action = (self.session.random_action() if self.mode_combo.currentData() == "random"
                  else self.recommendation.recommended_action)
        if phase == PHASE_PATH:
            self.auto_pending = False
        self._apply_action(action)

    def _finish_map(self):
        state = self.session.state
        self._log(f"[本图结束] CD={state.countdown}，目标={self.spin_target.value()}，"
                  f"{'达标' if state.countdown >= self.spin_target.value() else '未达标'}。")
        if not self.campaign:
            self._set_busy(False, "单图推演结束")
            self._refresh_view()
            return
        result = self.campaign.settle_current(state, self.spin_target.value())
        self._log(f"[位面{result['plane']}结算] 实际继承 CD={result['final_countdown']}，"
                  f"c={result['cheat']} r={result['reroll']}。")
        if self.campaign.finished:
            self._set_busy(False, "三位面仿真结束")
            self._refresh_view()
            return
        config = self.campaign.current_config()
        self.spin_plane.setValue(config["plane"])
        self._set_target(config["target_countdown"])
        self.frame_recommendations.clear()
        QTimer.singleShot(0, self._start_map_load)

    def _move_history(self, delta):
        if not self.session:
            return
        self.view_index = max(0, min(len(self.session.frames), self.view_index + delta))
        self._refresh_view()

    def _another_possibility(self):
        if (not self.session or self._is_busy()
                or self.view_index >= len(self.session.frames)):
            return
        try:
            self.session.another_possibility(self.view_index)
        except Exception as error:
            QMessageBox.warning(self, "无法反悔", str(error))
            return
        self.frame_recommendations = self.frame_recommendations[:self.view_index]
        self.view_index = len(self.session.frames)
        self.recommendation = None
        self._log("[另一种可能性] 已舍弃所选帧及其后续，恢复到该步路径选择。")
        self._refresh_view()
        self._request_recommendation()

    def _refresh_view(self):
        frame = recommendation = None
        if self.session and self.view_index < len(self.session.frames):
            frame = self.session.frames[self.view_index]
            recommendation = self.frame_recommendations[self.view_index]
        if frame:
            state, context = frame["state_after_effect"], frame["path_context"]
            display_node = frame["display_node"]
            effect_text = _effect_summary(
                frame["observations"], frame["effect_actions"],
                frame["locked_effect"], frame["effect_target"])
        elif self.session:
            state, context = self.session.state, self.session.context
            recommendation = self.recommendation
            display_node = state.node_idx
            facts = self.session.step_facts
            effect_text = _effect_summary(
                facts["observations"], facts["effect_actions"],
                facts["locked_effect"], facts["effect_target"])
        else:
            state = context = recommendation = None
            display_node, effect_text = None, "--"
        self.canvas.set_view(state, context, recommendation, frame)
        self.lbl_phase.setText(PHASE_LABELS.get(context.phase, "--") if context else "--")
        operation = PHASE_LABELS.get(context.phase, "--") if context else "--"
        self.lbl_operation.setText(
            f"当前操作：{operation}"
            + ("（点击图中节点）" if context and context.phase in (PHASE_TARGET, PHASE_PATH) else ""))
        self.lbl_effect.setText(effect_text)
        self.lbl_score.setText(str(state.countdown) if state else "--")
        self.lbl_resource.setText(
            f"Cheat {state.cheat_rem}  /  Reroll {state.reroll_rem}" if state else "--")
        self.lbl_target.setText(str(self.spin_target.value()))
        if context and context.phase == PHASE_EFFECT and context.observed_effect in ALL_EFFECTS:
            self.combo_observed.setCurrentIndex(self.combo_observed.findData(context.observed_effect))
        self._set_node_crop(display_node)
        self._fill_recommendation(context, recommendation)
        self._request_dp_analysis(context)
        total = len(self.session.frames) + 1 if self.session else 1
        self.lbl_frames.setText(f"{self.view_index + 1}/{total}")
        self._update_controls()

    def _fill_recommendation(self, context, recommendation):
        self.candidate_table.setRowCount(0)
        self.lbl_win_leader.clear()
        if not context or not recommendation:
            self.lbl_recommend.setText("正在采样…" if self._is_busy() else "--")
            return
        action = recommendation.recommended_action
        report = recommendation.reports[action]
        text = f"{format_action(context.phase, action)}\n平均最终 CD {report.mean:.2f}"
        if report.win_rate is not None:
            text += f"，胜率 {report.win_rate * 100:.4f}%"
        text += f"（n={report.count}）"
        self.lbl_recommend.setText(text)
        if recommendation.highest_win_action != action:
            winner = recommendation.highest_win_action
            win_report = recommendation.reports[winner]
            self.lbl_win_leader.setText(
                f"金圈：最高胜率 {format_action(context.phase, winner)} "
                f"{(win_report.win_rate or 0) * 100:.4f}% / 均分 {win_report.mean:.2f}")
        ranked = sorted(recommendation.reports, key=lambda item: (
            -recommendation.reports[item].mean, str(item)))
        self.candidate_table.setRowCount(len(ranked))
        for row, candidate in enumerate(ranked):
            stats = recommendation.reports[candidate]
            values = [
                format_action(context.phase, candidate), f"{stats.mean:.2f}",
                "--" if stats.win_rate is None else f"{stats.win_rate * 100:.4f}%",
                f"{stats.count:,}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if candidate == action:
                    item.setForeground(QColor("#65ef8b"))
                elif candidate == recommendation.highest_win_action:
                    item.setForeground(QColor("#ffd54f"))
                self.candidate_table.setItem(row, column, item)
        self.candidate_table.resizeRowsToContents()

    def _set_node_crop(self, node_idx):
        self.lbl_node_crop.clear()
        if self.prepared is None or node_idx is None:
            return
        source = QPixmap(self.prepared.image_path)
        rect = None
        if node_idx == self.prepared.model.start_idx and self.prepared.start_detected:
            rect = self.prepared.start_crop_rect
        if rect is None:
            node = self.prepared.model.node_map.get(node_idx, {})
            original = node.get("orig")
            if original:
                x, y = original["location"]
                width, height = original["size"]
                padding = max(8, int(max(width, height) * 0.18))
                rect = (x - padding, y - padding, x + width + padding, y + height + padding)
        if rect:
            x1, y1, x2, y2 = map(int, rect)
            crop = source.copy(max(0, x1), max(0, y1), max(1, x2 - x1), max(1, y2 - y1))
            self.lbl_node_crop.setPixmap(crop.scaled(
                76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_node_crop.setText(f"#{node_idx}")

    def _is_busy(self):
        return bool((self.map_thread and self.map_thread.isRunning())
                    or (self.rec_thread and self.rec_thread.isRunning()))

    def _mode_changed(self):
        if self.mode_combo.currentData() == "manual":
            self.auto_pending = False
        self._update_controls()

    def _update_controls(self):
        busy = self._is_busy()
        context = self.session.context if self.session else None
        active_view = bool(self.session and self.view_index == len(self.session.frames))
        manual = self.mode_combo.currentData() == "manual"
        effect = bool(context and context.phase == PHASE_EFFECT and active_view and not busy and manual)
        self.btn_keep.setEnabled(effect)
        self.btn_reroll.setEnabled(effect and context.state.reroll_rem > 0)
        self.btn_cheat.setEnabled(effect and context.state.cheat_rem > 0)
        self.combo_cheat.setEnabled(self.btn_cheat.isEnabled())
        self.combo_observed.setEnabled(effect)
        self.btn_observed.setEnabled(effect)
        self.btn_apply_rec.setEnabled(bool(manual and active_view and not busy and self.recommendation))
        self.btn_execute.setEnabled(bool(not manual and not self.auto_pending
                                         and active_view and not busy and context
                                         and context.phase != PHASE_TERMINAL))
        count = len(self.session.frames) if self.session else 0
        self.btn_prev.setEnabled(self.view_index > 0)
        self.btn_next.setEnabled(self.view_index < count)
        self.btn_alternative.setEnabled(bool(self.session and not busy and self.view_index < count))

    def closeEvent(self, event):
        self.pending_load = None
        self.pending_recommendation = False
        self.generation += 1
        self.request_id += 1
        self.auto_pending = False
        self.dp_request_id += 1
        self.pending_dp = False
        for thread in (self.map_thread, self.rec_thread, self.dp_thread):
            if thread and thread.isRunning():
                thread.requestInterruption()
        if any(thread and thread.isRunning()
               for thread in (self.map_thread, self.rec_thread, self.dp_thread)):
            self.setEnabled(False)
            self.lbl_stage.setText("正在安全退出…")
            event.ignore()
            QTimer.singleShot(100, self.close)
        else:
            event.accept()


def run_app():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow, QWidget { background:#171b27; color:#e1e5f2; }
        QGroupBox { border:1px solid #3e475d; border-radius:6px; margin-top:10px;
                    padding-top:8px; font-weight:600; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        QPushButton { background:#2c3549; border:1px solid #526079; border-radius:5px;
                      padding:6px 10px; min-height:22px; }
        QPushButton:hover:!disabled { background:#3a4762; }
        QPushButton:disabled { color:#697184; background:#222734; border-color:#343b4c; }
        QComboBox, QSpinBox, QLineEdit { background:#222838; border:1px solid #46516a;
                                        border-radius:4px; padding:4px; }
        QPlainTextEdit, QTableWidget { background:#10141f; border:1px solid #343d52; }
        QHeaderView::section { background:#252d3e; padding:4px; border:0; }
        QProgressBar { border:1px solid #46516a; border-radius:4px; text-align:center; }
        QProgressBar::chunk { background:#4caf78; }
        QScrollArea { border:0; }
    """)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(run_app())
