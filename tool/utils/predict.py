import cv2
import numpy as np

from tool.GLOBAL import factor
from tool.log import CUS_LOGGER
from tool.utils.image_tool import find_image_in_folder
from tool.utils.minimap_util import (
    create_circle,
    draw_circle,
    group_points,
    image_size,
    inrange,
    remove_border,
    subtract_blur,
)

radius_item = (5, 7)
AIM_ENEMY_LUMA_MIN = 184
AIM_ENEMY_RED_MIN = 200
AIM_ENEMY_EDGE_MIN = 18
AIM_ENEMY_PRIMARY_RADII = (29, 32)
AIM_ENEMY_EDGE_RADII = (17, 20, 23, 26)
AIM_ENEMY_PEAK_MIN = 52
AIM_ENEMY_EDGE_PEAK_MIN = 36
AIM_ENEMY_ROI_TOP = 95
AIM_ENEMY_ROI_BOTTOM = 125
AIM_ENEMY_ROI_LEFT = 255
AIM_ENEMY_ROI_RIGHT = 285
AIM_ENEMY_EDGE_CENTER_WIDTH = 40
mask_interact = find_image_in_folder('gray_image/', 'MASK_MAP_INTERACT.png')
circles_enemy = {
    radius: create_circle(radius - 1, radius)
    for radius in set(AIM_ENEMY_PRIMARY_RADII + AIM_ENEMY_EDGE_RADII)
}
circle_item = create_circle(*radius_item)
event_mask = (find_image_in_folder("gray_image/",'MASK_MAP_INTERACT_BLACK') > 70)[:497]


def _best_enemy_ring_response(feature, radii, center_x_range=None):
    width, height = image_size(feature)
    points = inrange(feature.copy(), lower=AIM_ENEMY_EDGE_MIN)
    best_score = 0
    best_center = None
    best_response = np.zeros((height, width), dtype=np.uint8)

    for radius in radii:
        safe = points
        if safe.shape[0]:
            safe = safe[
                (safe[:, 0] >= radius) & (safe[:, 0] < width - radius) &
                (safe[:, 1] >= radius) & (safe[:, 1] < height - radius)
            ]
        draw = np.zeros((height, width), dtype=np.uint8)
        draw_circle(draw, circles_enemy[radius], safe)
        response = cv2.multiply(draw, 4)
        response = subtract_blur(response, 3)

        if center_x_range is not None:
            response[:AIM_ENEMY_ROI_TOP, :] = 0
            response[-AIM_ENEMY_ROI_BOTTOM:, :] = 0
            x_min, x_max = center_x_range
            response[:, :x_min] = 0
            response[:, x_max:] = 0

        _, score, _, center = cv2.minMaxLoc(response)
        if score > best_score:
            best_score = score
            best_center = center
            best_response = response

    return best_response, best_score, best_center, points.shape[0]


def predict_enemy(h, v):
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(h, 3, negative=False)
    cv2.inRange(h, AIM_ENEMY_LUMA_MIN, 255, dst=h)
    cv2.bitwise_and(y, h, dst=y)
    # 获取红色光晕 `v`
    cv2.inRange(v, AIM_ENEMY_RED_MIN, 255, dst=v)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)
    # Keep an unmasked copy for a partially clipped ring at either screen edge.
    cv2.bitwise_and(y, v, dst=y)
    edge_feature = y.copy()
    edge_feature[:AIM_ENEMY_ROI_TOP, :] = 0
    edge_feature[-AIM_ENEMY_ROI_BOTTOM:, :] = 0

    # Match both radii observed in the manually labelled screenshots.
    primary_feature = cv2.bitwise_and(y, mask_interact)
    primary_feature[:AIM_ENEMY_ROI_TOP, :] = 0
    primary_feature[-AIM_ENEMY_ROI_BOTTOM:, :] = 0
    primary_feature[:, :AIM_ENEMY_ROI_LEFT] = 0
    primary_feature[:, -AIM_ENEMY_ROI_RIGHT:] = 0
    draw_enemy, score, center, point_count = _best_enemy_ring_response(
        primary_feature, AIM_ENEMY_PRIMARY_RADII
    )
    if point_count > 1000:
        print(f'AimDetector.predict_enemy() 绘制点过多: {point_count}')
    if score >= AIM_ENEMY_PEAK_MIN:
        return draw_enemy, np.array([center])

    # A target may be clipped beneath a side HUD. Only allow the circle center
    # in the outermost 40 px and use a separately calibrated peak threshold.
    edge_span = AIM_ENEMY_EDGE_CENTER_WIDTH + 2 * max(AIM_ENEMY_EDGE_RADII)
    left_draw, left_score, left_center, _ = _best_enemy_ring_response(
        edge_feature[:, :edge_span], AIM_ENEMY_EDGE_RADII,
        center_x_range=(0, AIM_ENEMY_EDGE_CENTER_WIDTH + 1)
    )
    right_draw, right_score, right_center, _ = _best_enemy_ring_response(
        edge_feature[:, -edge_span:], AIM_ENEMY_EDGE_RADII,
        center_x_range=(edge_span - AIM_ENEMY_EDGE_CENTER_WIDTH, edge_span)
    )
    if right_score > left_score:
        edge_draw, edge_score = right_draw, right_score
        edge_center = (right_center[0] + width - edge_span, right_center[1])
        edge_offset = width - edge_span
    else:
        edge_draw, edge_score, edge_center = left_draw, left_score, left_center
        edge_offset = 0
    if edge_score >= AIM_ENEMY_EDGE_PEAK_MIN:
        full_edge_draw = np.zeros((height, width), dtype=np.uint8)
        full_edge_draw[:, edge_offset:edge_offset + edge_span] = edge_draw
        return full_edge_draw, np.array([edge_center])
    return draw_enemy, np.array([])


def predict_item(v):
    min_radius, max_radius = radius_item
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(v, 9)
    white = cv2.inRange(v, 112, 144)
    cv2.bitwise_and(y, white, dst=y)
    # 获取青色光晕 `v`
    cv2.inRange(v, 0, 84, dst=v)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)

    # 去除噪声，只保留青色圆形
    cv2.bitwise_and(y, v, dst=y)
    # 去除游戏UI
    cv2.bitwise_and(y, mask_interact, dst=y)
    # 去除边缘上的点，否则 draw_circle() 会溢出
    remove_border(y, max_radius)

    # 获取所有像素
    points = inrange(y, lower=18)
    # print(points.shape)
    if points.shape[0] > 1000:
        CUS_LOGGER.debug(f'AimDetector.predict_item() 绘制点过多: {points.shape}')
    # 绘制圆形
    draw = np.zeros((height, width), dtype=np.uint8)
    draw_circle(draw, circle_item, points)
    draw = subtract_blur(draw, 5)
    draw_item = cv2.multiply(draw, 4)

    # 寻找峰值
    points = inrange(draw_item, lower=18)
    points=group_points(points,10)
    if points.shape[0] > 3:
        CUS_LOGGER.debug(f'AimDetector.predict_item() 峰值过多: {points.shape}')
    points_item = points
    # print(points)
    return draw_item,points_item
def aimed_enemy(points_enemy) -> tuple[int, int] | None:
    if points_enemy is None:
        return None

    count = len(points_enemy)
    if count >= 2:
        print(f'发现多个瞄准的敌人: {points_enemy}')
    try:
        point = points_enemy[0]
        return tuple(point)
    except IndexError:
        return None
def aimed_item(points_item) -> tuple[int, int] | None:
    if points_item is None:
        return None
    try:
        _ = points_item[1]
        print(f'发现多个瞄准的物品，使用第一个点 {points_item}')
    except IndexError:
        pass
    try:
        point = points_item[0]
        return tuple(point)
    except IndexError:
        return None

def predict(image, enemy=True, item=True, debug=False):
    """
    在图像上预测 `瞄准`，耗时约 10.0~10.5ms。

    参数:
        image:
        enemy: True 表示预测敌人
        item: True 表示预测物品
        show_log:
        debug: True 表示显示 AimDetector 图像
    """

    draw_item = None
    draw_enemy = None
    points_item = None
    points_enemy = None
    # 1.5~2.0ms
    yuv = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    v = yuv[:, :, 2]
    h = yuv[:, :, 0]
    # 4.0~4.5ms
    if enemy:
        draw_enemy,points_enemy =predict_enemy(h.copy(), v.copy())
    # 3.0~3.5ms
    if item:
        draw_item,points_item =predict_item(v.copy())
    kv = {'enemy': aimed_enemy(points_enemy), 'item': aimed_item(points_item)}
    if kv['enemy'] is not None or kv['item'] is not None:
        CUS_LOGGER.info(f'{factor}恍惚间看见了宇宙的「毁灭」: {kv}')
    if debug:
        show_aim(draw_enemy,draw_item)
    return kv
def show_aim(draw_enemy,draw_item):
    if draw_enemy is None:
        if draw_item is None:
            return
        else:
            r = g = b = draw_item
    else:
        if draw_item is None:
            r = g = b = draw_enemy
        else:
            r = draw_enemy
            g = b = draw_item

    image = cv2.merge([b, g, r])

    cv2.imshow('AimDetector', image)
    cv2.waitKey(0)
def get_text_position(image):
    CUS_LOGGER.info('「众人将与一人离别，惟其人将觐见奇迹」')
    scr = image[:497]
    mask = np.zeros((497, scr.shape[1]), dtype=np.uint8)
    mask_zero = np.zeros((497, scr.shape[1]), dtype=np.uint8)
    mask[((scr.max(axis=-1) - scr.min(axis=-1)) < 3) & (scr.max(axis=-1) > 247)] = 255
    mask_zero[((scr.max(axis=-1) - scr.min(axis=-1)) < 3) & (scr.max(axis=-1) < 21)] = 255
    kernel = np.ones((10, 30), np.uint8)
    mask_zero = cv2.dilate(mask_zero, kernel, iterations=1)
    mask &= mask_zero
    mask[event_mask] = 0
    kernel = np.ones((8, 55), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    kernel = np.ones((6, 40), np.uint8)
    mask = cv2.erode(mask, kernel, iterations=2)
    # cv.imshow("mask", mask)
    # cv.waitKey(0)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mx_area, mx_cnt = 0, None
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # print(w,h)
        if h > 22:
            continue
        if mx_area < w * h:
            mx_area = w * h
            mx_cnt = cnt
    res = []
    if mx_area < 4:
        return res
    xx, yy, ww, hh = cv2.boundingRect(mx_cnt)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h >= 4 and abs(y - yy) < 20:
            res.append((x + w // 2, y + h // 2))
    res = sorted(res, key=lambda x: x[0])
    if len(res) == 2 and res[1][0] - res[0][0] < 150:
        res = [((res[0][0] + res[1][0]) // 2, res[0][1])]
    return res
