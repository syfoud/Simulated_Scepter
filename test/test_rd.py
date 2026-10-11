import numpy as np
import cv2 as cv
from importing import load_img
load_img()
from core.simulated.utils import get_dis
from tool.utils.minimap_util import get_minimap, re_get_position, MINIMAP_RADIUS, POSITION_SEARCH_SCALE

red = [47, 47, 232]
now_loc=(800.3,317.9)
screen=cv.imread("20260320_173147.png")
img1=get_minimap(screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
cv.imshow("i",img1)
cv.imwrite("1.png",img1)
cv.waitKey(0)
rd = np.where(np.sum(( img1- red) ** 2,
                     axis=-1) <= 5000)
if rd[0].shape[0] > 0:
    print(rd)
    # self.target.remove((recent_loc, 1))
    new_loc = re_get_position(now_loc)
    print(f"图片全局坐标{new_loc}")
    # 创建所有检测到的敌人坐标的列表
    enemy_coords = []
    for i in range(len(rd[0])):
        enemy_x, enemy_y = rd[1][i], rd[0][i]
        world_x = new_loc[0] + (enemy_x - 93)*POSITION_SEARCH_SCALE
        world_y = new_loc[1] + (enemy_y - 93)*POSITION_SEARCH_SCALE
        new_loc = re_get_position((world_x, world_y), re=True)
        enemy_coords.append((new_loc, (enemy_x, enemy_y)))

    # 按距离self.real_loc排序，最近的在前面
    enemy_coords.sort(key=lambda coord: get_dis(coord[0], now_loc))
    # 选择最近的敌人作为目标
    nearest_world_coord, nearest_local_coord = enemy_coords[0]
    recent_loc = tuple(nearest_world_coord)
    # self.target.add((recent_loc, 1))
    print(
        f"找到新的敌对目标点：{recent_loc}，本地图像坐标{nearest_local_coord}共检测到{len(enemy_coords)}个敌人，按距离排序,最近距离(浮点）{get_dis(recent_loc, now_loc)}")
