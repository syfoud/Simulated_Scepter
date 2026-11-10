import os

import numpy as np
import win32gui

from tool.utils.game_window import canonical_game_title


def get_hwnd_and_text():
    hwnd = win32gui.GetForegroundWindow()
    Text = canonical_game_title(hwnd) or win32gui.GetWindowText(hwnd)
    return hwnd,Text


def get_dis(x, y):
    """返回两点间的直线距离。x、y 为 (x, y) 形式的坐标。"""
    return ((x[0] - y[0]) ** 2 + (x[1] - y[1]) ** 2) ** 0.5


def get_center(img, i, j):
    """
    计算图像中指定位置(i,j)附近区域的加权中心坐标
    """
    rx, ry, rt = 0, 0, 0
    for x in range(-7, 7):
        for y in range(-7, 7):
            if (
                    0 <= i + x < img.shape[0]
                    and 0 <= j + y < img.shape[1]
            ):
                s = np.sum(img[i + x, j + y])
                if 30 < s < 255 * 3 - 30:
                    rt += 1
                    rx += x
                    ry += y
    return (i + rx / rt, j + ry / rt)


def find_latest_modified_file(folder_path):
    files = [
        os.path.join(folder_path, file)
        for file in os.listdir(folder_path)
    ]
    x,y,upx,upy=-1,-1,-1,-1
    target_path=None
    file = None
    for i in files:
        name = os.path.splitext(i)[0].split("/")[-1]
        if "map" in name:
            map_num=name.split("_")[1]
            coords = name.split("(")[1].split(")")[0]
            x, y = map(float, coords.split(","))  # 将坐标转换为浮点数
            file= i
        if "target" in name:
            upx=float(name.split("_")[1])
            upy=float(name.split("_")[2])
            target_path= i

    return file,x,y,map_num,upx,upy,target_path

