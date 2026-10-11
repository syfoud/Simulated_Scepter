"""在冻结的游戏截图上选择 OCR 文字或框选图片标志。"""

import math
from pathlib import Path

import numpy as np
from PyQt5 import uic
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QMessageBox,
)

from route import PATHS
from tool.script_tools import marker_path, save_marker, text_trigger


class SampleView(QGraphicsView):
    text_selected = pyqtSignal(int)
    region_selected = pyqtSignal(object)

    def __init__(self, screen, texts, recognize, parent=None):
        super().__init__(parent)
        self.texts, self.recognize = texts, recognize
        self.origin = None
        self.image_height, self.image_width = screen.shape[:2]
        self.setMinimumSize(400, 260)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        rgb = np.ascontiguousarray(screen[:, :, ::-1])
        image = QImage(rgb.data, self.image_width, self.image_height, rgb.strides[0], QImage.Format_RGB888).copy()
        scene.addPixmap(QPixmap.fromImage(image))
        scene.setSceneRect(0, 0, self.image_width, self.image_height)
        for item in texts:
            left, right, top, bottom = item["box"]
            scene.addRect(QRectF(left, top, right - left, bottom - top), QPen(QColor("#34b87a"), 2))
        self.selection = scene.addRect(QRectF(), QPen(QColor("#ff7043"), 3))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def show_box(self, box):
        left, right, top, bottom = box
        self.selection.setRect(QRectF(left, top, right - left, bottom - top))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        point = self.mapToScene(event.pos())
        if self.recognize:
            candidates = [(index, item) for index, item in enumerate(self.texts)
                          if item["box"][0] <= point.x() <= item["box"][1]
                          and item["box"][2] <= point.y() <= item["box"][3]]
            if candidates:
                index, _ = min(candidates, key=lambda pair: (pair[1]["box"][1] - pair[1]["box"][0])
                               * (pair[1]["box"][3] - pair[1]["box"][2]))
                self.text_selected.emit(index)
        elif self.sceneRect().contains(point):
            self.origin = point
            self.selection.setRect(QRectF(point, point))

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection.setRect(QRectF(self.origin, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect()))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.origin is not None:
            rect = QRectF(self.origin, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.origin = None
            if rect.width() >= 2 and rect.height() >= 2:
                box = [max(0, math.floor(rect.left())), min(self.image_width, math.ceil(rect.right())),
                       max(0, math.floor(rect.top())), min(self.image_height, math.ceil(rect.bottom()))]
                self.show_box(box)
                self.region_selected.emit(box)
            else:
                self.selection.setRect(QRectF())
                self.region_selected.emit(None)
        else:
            super().mouseReleaseEvent(event)


class TriggerSample(QDialog):
    def __init__(self, sample, recognize, parent=None, *, event_name=""):
        super().__init__(parent)
        uic.loadUi(str(Path(PATHS["ui"]) / "TriggerSample.ui"), self)
        self.frame, self.texts = sample["screen"], sample["texts"]
        self.recognize = recognize
        self.box = self.trigger = None
        self.view = SampleView(self.frame, self.texts, recognize, self.canvas_host)
        self.canvas_layout.addWidget(self.view)
        self.text_list.setVisible(recognize)
        self.text_row.setVisible(recognize)
        self.image_row.setVisible(not recognize)
        path = marker_path(event_name)
        self.file_name.setText(path.name)
        self.save_folder.setText(str(path.parent))
        self.browse_btn.clicked.connect(self.choose_folder)
        self.instruction.setText("点击画面中的文字框或右侧识别结果，再确认匹配文字。" if recognize
                                 else "在游戏画面上拖动框选图片标志，确认后保存图片并填入触发条件。")
        self.use_btn.setEnabled(False)
        for item in self.texts:
            self.text_list.addItem(item["raw_text"])
        self.view.text_selected.connect(self.text_list.setCurrentRow)
        self.text_list.currentRowChanged.connect(self.select_text)
        self.view.region_selected.connect(self.select_region)
        self.match_text.textChanged.connect(lambda text: self.use_btn.setEnabled(self.box is not None and bool(text.strip())))
        self.use_btn.clicked.connect(self.use_sample)
        self.cancel_btn.clicked.connect(self.reject)
        if recognize and not self.texts:
            self.selection_label.setText("当前截图未识别到文字，请关闭此窗口并重新截取游戏画面。")
        # 使用所在屏幕的大部分可用空间，保留标题栏和手动调整窗口的余地。
        area = (parent.screen() if parent is not None else self.screen()).availableGeometry()
        self.resize(int(area.width() * 0.95), int(area.height() * 0.92))
        self.move(area.center() - self.rect().center())

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片标志保存目录", self.save_folder.text())
        if folder:
            self.save_folder.setText(folder)

    def select_text(self, row):
        if row < 0:
            return
        self.box = list(self.texts[row]["box"])
        self.view.show_box(self.box)
        try:
            trigger = text_trigger(self.texts[row])
            self.match_text.setText(trigger["text"])
            self.selection_label.setText(f"检测范围：{self.box}；匹配时忽略数字、英文字母和标点。")
        except ValueError as error:
            self.match_text.clear()
            self.selection_label.setText(str(error))

    def select_region(self, box):
        self.box = box
        self.use_btn.setEnabled(box is not None)
        self.selection_label.setText(f"已选择范围：{box}" if box is not None else "框选区域过小，请重新选择")

    def use_sample(self):
        try:
            if self.recognize:
                if not self.match_text.text().strip() or self.box is None:
                    raise ValueError("请选择有效文字标志")
                self.trigger = text_trigger({"raw_text": self.match_text.text().strip(), "box": self.box})
            else:
                if self.box is None:
                    raise ValueError("请先框选图片标志")
                name = self.file_name.text().strip()
                if not name or Path(name).name != name or name in (".", ".."):
                    raise ValueError("请填写有效的图片文件名，不要在名称中包含目录")
                if not Path(name).suffix:
                    name += ".png"
                if not self.save_folder.text().strip():
                    raise ValueError("请选择图片保存目录")
                path = Path(self.save_folder.text().strip()) / name
                if path.exists() and QMessageBox.question(self, "覆盖图片标志", f"图片已存在，是否覆盖？\n{path}",
                                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                    return
                self.trigger, path = save_marker(self.frame, self.box, path)
                self.selection_label.setText(f"图片标志已保存：{path}")
            self.accept()
        except (OSError, ValueError) as error:
            self.selection_label.setText(f"标志选择失败：{error}")
