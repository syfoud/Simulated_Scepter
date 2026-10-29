"""统一桌面界面的玻璃背景、按钮反馈与应用配色。"""

from pathlib import Path

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    pyqtProperty,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QWidget,
)

from route import PATHS


def apply_appearance(theme="dark"):
    """统一主窗口和弹窗；白色模式使用 Qt 原生控件与不透明背景。"""
    app = QApplication.instance()
    if app.style().objectName() != "fusion":
        app.setStyle("Fusion")
    palette = app.style().standardPalette()
    colors = (
        (QPalette.Window, "#131c2b"),
        (QPalette.WindowText, "#e4ebf5"),
        (QPalette.Base, "#111a29"),
        (QPalette.AlternateBase, "#1a2638"),
        (QPalette.Text, "#dce5f2"),
        (QPalette.Button, "#24334a"),
        (QPalette.ButtonText, "#e4ebf5"),
        (QPalette.Highlight, "#759cda"),
        (QPalette.HighlightedText, "#0d1726"),
        (QPalette.ToolTipBase, "#223149"),
        (QPalette.ToolTipText, "#eef3fb"),
        (QPalette.Link, "#9fc1f6"),
    ) if theme == "dark" else (
        (QPalette.Window, "#ffffff"),
        (QPalette.WindowText, "#202734"),
        (QPalette.Base, "#ffffff"),
        (QPalette.Text, "#202734"),
        (QPalette.ButtonText, "#202734"),
        (QPalette.Highlight, "#3977b7"),
        (QPalette.HighlightedText, "#ffffff"),
        (QPalette.Link, "#2869ac"),
    )
    for role, color in colors:
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#718096"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#718096"))
    app.setPalette(palette)
    family = app.property("scepter_font")
    if family is None:
        font_id = QFontDatabase.addApplicationFont(str(
            Path(PATHS["font"]) / "ChironGoRoundTC-350N.ttf"
        ))
        families = QFontDatabase.applicationFontFamilies(font_id)
        family = families[0] if families else "Microsoft YaHei UI"
        app.setProperty("scepter_font", family)
    app.setFont(QFont(family, 10))
    ui_path = Path(PATHS["ui"])
    stylesheet = "application.qss" if theme == "dark" else "native.qss"
    app.setStyleSheet((ui_path / stylesheet).read_text(encoding="utf-8").replace("@ui", ui_path.as_posix()))


class GlassBackground(QWidget):
    """保留原图，并缓存低分辨率模糊图供所有玻璃面板对齐取样。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QPixmap()
        self.blurred = QPixmap()

    def set_image(self, path):
        self.image = QPixmap(str(path))
        if self.image.isNull():
            self.blurred = QPixmap()
            self.update()
            return
        # 模糊只在背景载入时计算；窗口缩放和日志追加直接复用缓存。
        source = self.image.scaledToWidth(480, Qt.SmoothTransformation)
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(source)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(18)
        item.setGraphicsEffect(blur)
        scene.addItem(item)
        self.blurred = QPixmap(source.size())
        self.blurred.fill(Qt.transparent)
        painter = QPainter(self.blurred)
        scene.render(painter, QRectF(self.blurred.rect()), QRectF(source.rect()))
        painter.end()
        self.update()

    def paint_image(self, painter, blurred=False):
        image = self.blurred if blurred else self.image
        if image.isNull():
            painter.fillRect(self.rect(), QColor("#182438"))
            return
        scale = max(self.width() / image.width(), self.height() / image.height())
        target = QRectF(0, 0, image.width() * scale, image.height() * scale)
        target.moveCenter(QRectF(self.rect()).center())
        painter.drawPixmap(target, image, QRectF(image.rect()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)
        painter.setClipPath(path)
        if QApplication.palette().color(QPalette.Window).lightness() >= 128:
            painter.fillRect(self.rect(), Qt.white)
            painter.setPen(QColor("#d1d7df"))
            painter.drawPath(path)
            return
        self.paint_image(painter)
        tint = QLinearGradient(0, 0, self.width(), self.height())
        tint.setColorAt(0, QColor(10, 19, 34, 234))
        tint.setColorAt(0.65, QColor(14, 24, 42, 205))
        tint.setColorAt(1, QColor(27, 37, 59, 170))
        painter.fillRect(self.rect(), tint)
        painter.setPen(QColor(176, 200, 237, 45))
        painter.drawPath(path)


class GlassPanel(QWidget):
    """只模糊面板背后的图片，保留文字与控件的清晰边缘。"""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        painter.setClipPath(path)
        if QApplication.palette().color(QPalette.Window).lightness() >= 128:
            painter.fillRect(self.rect(), Qt.white)
            painter.setPen(QColor("#dde2e8"))
            painter.drawPath(path)
            return
        backdrop = self.parentWidget()
        while backdrop is not None and not isinstance(backdrop, GlassBackground):
            backdrop = backdrop.parentWidget()
        if backdrop is not None:
            offset = self.mapTo(backdrop, QPoint())
            painter.save()
            painter.translate(-offset)
            backdrop.paint_image(painter, blurred=True)
            painter.restore()
        opacity = 242 if self.objectName() == "log_panel" else 225
        painter.fillRect(self.rect(), QColor(15, 25, 42, opacity))
        painter.setPen(QColor(180, 204, 243, 32))
        painter.drawPath(path)


class AnimatedButton(QPushButton):
    """按需播放短暂的悬停过渡，静止时不占用动画计时器。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hover_value = 0.0
        self.hover_animation = QPropertyAnimation(self, b"hover", self)
        self.hover_animation.setDuration(130)
        self.hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)

    @pyqtProperty(float)
    def hover(self):
        return self.hover_value

    @hover.setter
    def hover(self, value):
        self.hover_value = value
        self.update()

    def enterEvent(self, event):
        self.hover_animation.stop()
        self.hover_animation.setStartValue(self.hover_value)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_animation.stop()
        self.hover_animation.setStartValue(self.hover_value)
        self.hover_animation.setEndValue(0.0)
        self.hover_animation.start()
        super().leaveEvent(event)

    def sizeHint(self):
        hint = super().sizeHint()
        if self.property("variant") != "window":
            hint.setHeight(max(hint.height(), self.fontMetrics().height() + 16))
        if self.property("wrap"):
            hint.setHeight(self.heightForWidth(self.width()))
        return hint

    def heightForWidth(self, width):
        if not self.property("wrap"):
            return super().heightForWidth(width)
        bounds = self.fontMetrics().boundingRect(
            QRect(0, 0, max(1, width - 20), 1000), Qt.TextWordWrap, self.label_text(width)
        )
        return max(38, bounds.height() + 16)

    def label_text(self, width):
        """长任务名优先在副标题前换行，避免把括号内的词拆散。"""
        text = self.text()
        if self.property("wrap") and self.fontMetrics().horizontalAdvance(text) > width - 20:
            return text.replace("（", "\n（", 1)
        return text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.property("wrap"):
            self.setMinimumHeight(self.heightForWidth(self.width()))

    def draw_label(self, painter, option):
        if self.property("wrap"):
            option.text = ""
            self.style().drawControl(QStyle.CE_PushButtonLabel, option, painter, self)
            group = QPalette.Active if self.isEnabled() else QPalette.Disabled
            painter.setPen(self.palette().color(group, QPalette.ButtonText))
            painter.drawText(self.rect().adjusted(10, 8, -10, -8), Qt.AlignCenter | Qt.TextWordWrap, self.label_text(self.width()))
        else:
            option.text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, self.width() - 20))
            self.style().drawControl(QStyle.CE_PushButtonLabel, option, painter, self)

    def paintEvent(self, event):
        light = QApplication.palette().color(QPalette.Window).lightness() >= 128
        variant = self.property("variant")
        if light and variant != "window":
            painter = QPainter(self)
            option = QStyleOptionButton()
            self.initStyleOption(option)
            option.text = ""
            self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
            self.draw_label(painter, option)
            return
        if variant == "primary":
            base, active = QColor("#345984"), QColor("#4776aa")
        elif variant == "danger":
            base, active = QColor("#422c3b"), QColor("#684052")
        elif variant == "window":
            base = QColor(28, 41, 62, 0)
            active = QColor(30, 40, 55, 18) if light else QColor(103, 128, 167, 65)
        else:
            base, active = QColor(71, 92, 124, 65), QColor(104, 133, 175, 100)
        progress = self.hover_value if self.isEnabled() else 0.0
        if self.isDown():
            progress = 1.0
        color = QColor.fromRgbF(
            base.redF() + (active.redF() - base.redF()) * progress,
            base.greenF() + (active.greenF() - base.greenF()) * progress,
            base.blueF() + (active.blueF() - base.blueF()) * progress,
            base.alphaF() + (active.alphaF() - base.alphaF()) * progress,
        )
        if not self.isEnabled():
            color.setAlpha(30)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        border = QColor(168, 198, 240, 120 if self.hasFocus() else 30)
        if variant == "window":
            border = Qt.transparent
        painter.setPen(border)
        radius = 0 if light and variant == "window" else 7
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        self.draw_label(painter, option)
        painter.end()
