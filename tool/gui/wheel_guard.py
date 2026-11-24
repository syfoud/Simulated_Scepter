"""全局滚轮守卫：下拉框和数字框只接受点击或键盘修改，滚轮用于滚动页面。"""

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QComboBox

# 会把滚轮当作输入直接改值的控件；QAbstractSpinBox 同时覆盖 QSpinBox、
# QDoubleSpinBox 和 QDateTimeEdit。
_VALUE_WIDGET_TYPES = (QComboBox, QAbstractSpinBox)


def _leave_wheel_focus(widget):
    """把 WheelFocus 降为 StrongFocus，让滚轮不再顺手把焦点移到控件上。"""
    if widget.focusPolicy() == Qt.WheelFocus:
        widget.setFocusPolicy(Qt.StrongFocus)


class _WheelGuard(QObject):
    """应用级滚轮拦截器。

    滚轮事件只忽略、不接受，Qt 会把它继续传给父控件，页面因此仍能正常滚动。
    焦点策略在控件显示时调整：焦点跳动可能触发输入框提交或键盘改值，
    点击和键盘聚焦仍保持原行为。
    """

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type != QEvent.Wheel and event_type != QEvent.Show:
            return False
        if not isinstance(watched, _VALUE_WIDGET_TYPES):
            return False
        if event_type == QEvent.Show:
            _leave_wheel_focus(watched)
            return False
        event.ignore()
        return True


def install_wheel_guard(app=None):
    """为整个应用安装滚轮守卫，之后创建的界面同样生效。

    重复调用不会重复安装。安装前已经存在的控件在这里补一次焦点策略处理；
    之后创建的控件在显示时由守卫处理。
    """
    app = app if app is not None else QApplication.instance()
    if app is None:
        raise RuntimeError("安装滚轮守卫前必须先创建 QApplication")
    if getattr(app, "_wheel_guard", None) is not None:
        return
    guard = _WheelGuard(app)
    app._wheel_guard = guard
    app.installEventFilter(guard)
    for widget in app.allWidgets():
        if isinstance(widget, _VALUE_WIDGET_TYPES):
            _leave_wheel_focus(widget)
