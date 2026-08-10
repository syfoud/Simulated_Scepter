from PyQt5 import QtCore, QtGui


def create_qt_icon(q_color, mode):
    """
    绘制图表
    :param q_color: Q color
    :param mode: "-" "x" "<-" "->" "magnifier"
    :return:
    """
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    match mode:
        case "x":
            painter.setPen(QtGui.QPen(q_color, 2))
            painter.drawLine(3, 3, 13, 13)
            painter.drawLine(3, 13, 13, 3)
        case "-":
            painter.setPen(QtGui.QPen(q_color, 2))
            painter.drawLine(3, 8, 13, 8)
        case "<-":
            painter.setPen(QtGui.QPen(q_color, 2))
            painter.drawLine(2, 8, 14, 8)  # 主线
            painter.drawLine(2, 8, 6, 4)  # 左上角
            painter.drawLine(2, 8, 6, 12)  # 左下角
        case "->":
            painter.setPen(QtGui.QPen(q_color, 2))
            painter.drawLine(2, 8, 14, 8)  # 主线
            painter.drawLine(14, 8, 10, 4)  # 右上角
            painter.drawLine(14, 8, 10, 12)  # 右下角
        case "magnifier":
            painter.setPen(QtGui.QPen(q_color, 1))
            painter.drawEllipse(3, 3, 10, 10)  # 外圆
            painter.drawLine(11, 11, 13, 13)  # 放大镜的把手
            painter.drawLine(11, 12, 13, 14)  # 放大镜的把手
            painter.drawLine(12, 11, 14, 13)  # 放大镜的把手
            painter.drawLine(12, 12, 14, 14)  # 放大镜的把手
        case "v":
            painter.setPen(QtGui.QPen(q_color, 2))
            painter.drawLine(3, 4, 13, 4)  # 顶部横线
            painter.drawLine(3, 1, 13, 1)  # 顶部横线
            painter.drawLine(3, 4, 8, 12)  # 左边线
            painter.drawLine(13, 4, 8, 12)  # 右边线
        case _:
            pass

    painter.end()

    return QtGui.QIcon(pixmap)
