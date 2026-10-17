import os
from copy import deepcopy
from datetime import datetime

import cv2 as cv
import numpy as np

from importing import load_img
from route import PATHS
from tool.utils.image_tool import find_image_by_name
from tool.utils.minimap_util import rotate_minimap, mask_minimap_center, crop, area_offset, get_minimap

MINIMAP_RADIUS = 93
#(138,149)精准中心点
xx=1920
yy=1080
def get_local(x, y, size,screen, large=True):
    sx, sy = size[0] + 60 * large, size[1] + 60 * large
    bx, by = xx - int(x * xx), yy - int(y * yy)
    print(f"范围y{max(0, by - sx // 2)}到{min(yy, by + sx // 2)},x{max(0, bx - sy // 2)}到{ min(xx, bx + sy // 2)}")
    return screen[
           max(0, by - sx // 2): min(yy, by + sx // 2),#y
           max(0, bx - sy // 2): min(xx, bx + sy // 2),#x
           :,
           ]

    return image
def get_bw_map(local_screen=None,screen=None):
    """
        进一步得到小地图的黑白格式
        re_screen：是否重新截图
        大小是186*186
    """
    try:
        black = np.array([0, 0, 0])
        white = np.array([210, 210, 210])
        gray = np.array([55, 55, 55])

        # local_screen=screen[46:222,43:219]#[43,46,219,222]源范围  正确范围#[45,56,231,242]
        # local_screen=screen[56:242,45:231]#[43,46,219,222]源范围  正确范围#[45,56,231,242] 偏移[2,10,12,20]
        if local_screen is None:
            local_screen = get_minimap(screen, radius=MINIMAP_RADIUS, copy=True, rotation=True,center_radius=95)

        # local_screen[np.sum(np.abs(local_screen - blue), axis=-1) <= 50] = 0
        hsv = cv.cvtColor(local_screen, cv.COLOR_BGR2HSV)  # 转HSV
        lower = np.array([93, 90, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        upper = np.array([97, 255, 255])

        mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        loc_tp = cv.bitwise_and(local_screen, local_screen, mask=mask)
        local_screen=local_screen-loc_tp
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        # 灰块、白线：小地图中的可移动区域、可移动区域的边缘
        # b_map：当前像素点是否是灰块。只允许灰块附近（2像素）的像素被识别为白线
        grey_map = deepcopy(bw_map)
        grey_map[
            np.sum((local_screen - gray) ** 2, axis=-1) <= 4800
            ] = 255
        kernel = np.zeros((5, 5), np.uint8)  # 设置kenenel大小
        kernel += 1
        grey_map = cv.dilate(grey_map, kernel, iterations=1)
        bw_map[
            (np.sum((local_screen - white) ** 2, axis=-1) <= 9000)
            & (grey_map > 200)
            ] = 255
        # 排除半径90以外的像素点
        # for i in range(bw_map.shape[0]):
        #     for j in range(bw_map.shape[1]):
        #         if ((i - 93) ** 2 + (j - 93) ** 2) > 90 ** 2:
        #             bw_map[i, j] = 0
        # 调试图统一写入 temp/debug/，允许由自动清理按时间命名规则回收。
        debug_folder = os.path.join(PATHS["temp"], "debug")
        os.makedirs(debug_folder, exist_ok=True)
        cv.imwrite(
            os.path.join(debug_folder, f"bwmap_{datetime.now():%Y%m%d_%H%M%S_%f}.png"),
            bw_map,
        )

        # 统计非黑像素点数量
        non_black_pixels = np.count_nonzero(bw_map)
        print(f"bw_map 中非黑像素点数量：{non_black_pixels}")

        return bw_map, non_black_pixels
    except Exception as e:
        print(f"get_bw_map函数执行出错: {str(e)}")
        return None


def get_blank_state(screen=None):
    local_screen = get_minimap(screen, radius=MINIMAP_RADIUS, copy=True, rotation=True, center_radius=95)
    local_screen = local_screen - cv.bitwise_and(local_screen, local_screen, mask=cv.inRange(cv.cvtColor(local_screen, cv.COLOR_BGR2HSV), np.array([80, 0, 0]) , np.array([110, 255, 255])))
    bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
    grey_map = deepcopy(bw_map)
    grey_map[np.sum((local_screen - np.array([55, 55, 55])) ** 2, axis=-1) <= 4800] = 255
    grey_map = cv.dilate(grey_map, np.ones((5, 5), np.uint8), iterations=1)
    bw_map[(np.sum((local_screen - np.array([210, 210, 210])) ** 2, axis=-1) <= 9000)& (grey_map > 200)] = 255
    non_black_pixels = np.count_nonzero(bw_map)
    print(f"bw_map 中非黑像素点数量：{non_black_pixels}")
    return bw_map, non_black_pixels
if __name__ == "__main__":
    load_img()
    my_screen=cv.imread("20251021_224505.png")
    get_blank_state(screen=my_screen)
