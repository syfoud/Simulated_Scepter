from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from tool.GLOBAL import factor
from tool.log import CUS_LOGGER
from tool.utils.image_tool import find_image_in_folder
from tool.utils.minimap_util import subtract_blur

# 物品瞄准标记（开发中，尚未实机验证）是白色十字 + 中心小圆环，外圈青色光晕。
ITEM_WHITE_MIN = 140
ITEM_CYAN_GLOW_MIN = 25           # 青色光晕：min(B, G) - R 的下限
ITEM_CENTER_RADIUS = (5, 16)      # 中心小圆环的半径范围
ITEM_GLOW_COVERAGE_MIN = 0.20     # 标记中心附近青色光晕覆盖率下限
ITEM_WHITE_ARM_MIN = 3            # 十字的四个方向至少要有几个方向存在白色臂

# 敌人准星由白色圆环、四个向内箭头和中心白点组成，外圈带红色光晕，
# 同一时刻屏幕上最多只有一个（角色一次只能锁定一个敌人）。
# 准星刚出现时直径很大，随后快速收缩到固定直径（约 28~30 像素半径），
# 因此用霍夫圆在 [24, 64] 像素半径内取候选，再按白色圆环覆盖率与中心红色光晕校验。
# 半径下限 24 用于排除黄色墙面格纹等小圆形误检。
AIM_ENEMY_WHITE_MIN = 140         # 白色准星像素三通道最小值的下限
AIM_ENEMY_RED_GLOW_MIN = 50       # 红色光晕：R - G 的下限，排除黄/金色光晕
AIM_ENEMY_RING_BAND = 2           # 圆环半径容差，单位像素
AIM_ENEMY_RING_COVERAGE_MIN = 0.75
AIM_ENEMY_CENTER_RED_MIN = 60
AIM_ENEMY_RED_RING_MIN = 0.80     # 红色圆环的角度覆盖率下限，排除只有白/黄图案的候选
AIM_ENEMY_HOUGH_DP = 1.0
AIM_ENEMY_HOUGH_PARAM1 = 80
AIM_ENEMY_HOUGH_PARAM2 = 16
AIM_ENEMY_HOUGH_MIN_DIST = 20
AIM_ENEMY_MIN_RADIUS = 24
AIM_ENEMY_MAX_RADIUS = 64
AIM_ENEMY_RED_CONTOUR_MIN = 60      # 红色连通块的 R-G 下限；低于此值的红晕不参与初筛
AIM_ENEMY_CONTOUR_AREA_MIN = 300    # 过小的红色连通块（文字/粒子）直接丢弃
AIM_ENEMY_CONTOUR_TOPK = 6          # 只对最大的几个红色连通块做裁剪霍夫，控制耗时
AIM_ENEMY_CROP_HALF = 110           # 裁剪霍夫的半边长；220×220 覆盖半径 64 的准星并留出余量
AIM_ENEMY_RIGHT_STRIP_LEFT = 1600   # 右侧窄条左边界；主 ROI 右边界 1635，重叠 35 px 避免漏接
AIM_ENEMY_RIGHT_COVERAGE_MIN = 0.70  # 右侧准星叠在 HUD 上，白环会被吃掉一部分，阈值比主检测略松
AIM_ENEMY_RIGHT_CENTER_RED_MIN = 60
AIM_ENEMY_ROI_TOP = 95
AIM_ENEMY_ROI_BOTTOM = 125
AIM_ENEMY_ROI_LEFT = 255
AIM_ENEMY_ROI_RIGHT = 285
AIM_ENEMY_SIGN_HALF_SPAN = 200
AIM_ENEMY_SIGN_HALF_WIDTH = 5
AIM_ENEMY_SIGN_HORIZONTAL_MIN = 0.45
AIM_ENEMY_SIGN_VERTICAL_MAX = 0.20

mask_interact = find_image_in_folder('gray_image/', 'MASK_MAP_INTERACT')
mask_interact_roi = mask_interact[
    AIM_ENEMY_ROI_TOP:-AIM_ENEMY_ROI_BOTTOM, AIM_ENEMY_ROI_LEFT:-AIM_ENEMY_ROI_RIGHT
]
event_mask = (find_image_in_folder("gray_image/",'MASK_MAP_INTERACT_BLACK') > 70)[:497]

_ANGLES = np.deg2rad(np.arange(72) * 5.0)
_RING_OFFSETS = range(-AIM_ENEMY_RING_BAND, AIM_ENEMY_RING_BAND + 1)


def _is_horizontal_red_scenery(red_pixels, center):
    """判断候选点是否落在大面积横向红色招牌上，用于排除红色背景误检。"""
    if center is None:
        return False
    x, y = center
    height, width = red_pixels.shape
    half_span = AIM_ENEMY_SIGN_HALF_SPAN
    half_width = AIM_ENEMY_SIGN_HALF_WIDTH
    horizontal = red_pixels[
        max(0, y - half_width):min(height, y + half_width + 1),
        max(0, x - half_span):min(width, x + half_span + 1),
    ]
    vertical = red_pixels[
        max(0, y - half_span):min(height, y + half_span + 1),
        max(0, x - half_width):min(width, x + half_width + 1),
    ]
    horizontal_ratio = np.any(horizontal, axis=0).mean()
    vertical_ratio = np.any(vertical, axis=1).mean()
    return (
        horizontal_ratio > AIM_ENEMY_SIGN_HORIZONTAL_MIN and
        vertical_ratio < AIM_ENEMY_SIGN_VERTICAL_MAX
    )


def _enemy_masks(image):
    """构造准星检测区域内的白色准星掩膜、红色光晕掩膜与红色色度图。

    Args:
        image: BGR 截图（1920x1080）。

    Returns:
        (white, glow, redness)：三者都是准星 ROI 裁剪后的图像（坐标相对 ROI 左上角），
        white 为白色准星像素（三通道都亮且是局部亮线），glow 为膨胀后的红色光晕，
        redness 为红色色度（R 与 G 之差），用于校验准星中心是否在红光里；
        用 R-G 而不是 R-(G+B)/2 可以排除黄/金色光晕与黄色墙面图案。
    """
    roi = image[
        AIM_ENEMY_ROI_TOP:-AIM_ENEMY_ROI_BOTTOM,
        AIM_ENEMY_ROI_LEFT:-AIM_ENEMY_ROI_RIGHT,
    ]
    b, g, r = cv2.split(roi)
    b = b.astype(np.int16)
    g = g.astype(np.int16)
    r = r.astype(np.int16)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    min_channel = np.minimum(np.minimum(b, g), r)
    white = cv2.bitwise_and(
        (min_channel > AIM_ENEMY_WHITE_MIN).astype(np.uint8) * 255,
        subtract_blur(gray, 3, negative=False),
    )
    white = cv2.bitwise_and(white, mask_interact_roi)

    redness = r - g
    glow = cv2.dilate(
        (redness > AIM_ENEMY_RED_GLOW_MIN).astype(np.uint8) * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    return white, glow, redness


def _ring_coverage(white, center, radius, threshold=0):
    """返回白色准星像素沿候选圆环的角度覆盖率（0~1）。"""
    x, y = center
    height, width = white.shape
    covered = np.zeros(len(_ANGLES), dtype=bool)
    for offset in _RING_OFFSETS:
        sample_x = np.rint(x + (radius + offset) * np.cos(_ANGLES)).astype(np.int32)
        sample_y = np.rint(y + (radius + offset) * np.sin(_ANGLES)).astype(np.int32)
        inside = (
            (sample_x >= 0) & (sample_x < width) &
            (sample_y >= 0) & (sample_y < height)
        )
        hits = np.zeros(len(_ANGLES), dtype=bool)
        hits[inside] = white[sample_y[inside], sample_x[inside]] > threshold
        covered |= hits
    return float(covered.mean())


def _center_redness(redness, center, radius):
    """返回候选准星中心小圆内 R-G 的均值。"""
    x, y = center
    inner = max(3, int(radius * 0.25))
    height, width = redness.shape
    y0, y1 = max(0, y - inner), min(height, y + inner + 1)
    x0, x1 = max(0, x - inner), min(width, x + inner + 1)
    return float(redness[y0:y1, x0:x1].mean())


def _hough_in_crop(white, center, half=AIM_ENEMY_CROP_HALF):
    """只在候选中心附近 220×220 的原分辨率白环上跑霍夫，避免全帧霍夫的开销。"""
    height, width = white.shape
    x0 = max(0, min(width - 2 * half, int(round(center[0])) - half))
    y0 = max(0, min(height - 2 * half, int(round(center[1])) - half))
    crop = white[y0:y0 + 2 * half, x0:x0 + 2 * half]
    if crop.shape[0] != 2 * half or crop.shape[1] != 2 * half:
        return []
    circles = cv2.HoughCircles(
        crop, cv2.HOUGH_GRADIENT,
        dp=AIM_ENEMY_HOUGH_DP,
        minDist=AIM_ENEMY_HOUGH_MIN_DIST,
        param1=AIM_ENEMY_HOUGH_PARAM1,
        param2=AIM_ENEMY_HOUGH_PARAM2,
        minRadius=AIM_ENEMY_MIN_RADIUS,
        maxRadius=AIM_ENEMY_MAX_RADIUS,
    )
    if circles is None:
        return []
    return [
        (int(round(raw_x)) + x0, int(round(raw_y)) + y0, int(round(raw_radius)))
        for raw_x, raw_y, raw_radius in circles[0]
    ]


def _contour_candidates(redness, glow, white, coverage_min, center_red_min, offset):
    """连通块初筛：红色连通块 -> 粗中心 -> 220×220 裁剪霍夫 -> 白环/红环/中心红校验。"""
    red_mask = (redness > AIM_ENEMY_RED_CONTOUR_MIN).astype(np.uint8) * 255
    red_mask = cv2.morphologyEx(
        red_mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:AIM_ENEMY_CONTOUR_TOPK]

    candidates = []
    for contour in contours:
        if cv2.contourArea(contour) < AIM_ENEMY_CONTOUR_AREA_MIN:
            continue
        (rough_x, rough_y), rough_radius = cv2.minEnclosingCircle(contour)
        if rough_radius < AIM_ENEMY_MIN_RADIUS:
            continue
        circles = _hough_in_crop(white, (rough_x, rough_y))
        # 红晕块可能由多个特效合并而成，中心未必落在准星上；交给后面的白环/红环校验判断，
        # 这里只按“离粗中心近”排序，并放宽到 100 px，避免漏掉被红饰拉偏的准星。
        circles.sort(key=lambda c: (c[0] - rough_x) ** 2 + (c[1] - rough_y) ** 2)
        for x, y, radius in circles[:5]:
            if (x - rough_x) ** 2 + (y - rough_y) ** 2 > 100 ** 2:
                continue
            if not (AIM_ENEMY_MIN_RADIUS <= radius <= AIM_ENEMY_MAX_RADIUS):
                continue
            if _is_horizontal_red_scenery(glow, (x, y)):
                continue
            coverage = 0.0
            best_radius = radius
            for candidate_radius in range(
                max(AIM_ENEMY_MIN_RADIUS, radius - 2),
                min(AIM_ENEMY_MAX_RADIUS, radius + 2) + 1,
            ):
                current = _ring_coverage(white, (x, y), candidate_radius)
                if current > coverage:
                    coverage, best_radius = current, candidate_radius
            if coverage < coverage_min:
                continue
            red_coverage = 0.0
            for candidate_radius in range(
                max(AIM_ENEMY_MIN_RADIUS, best_radius - 2),
                min(AIM_ENEMY_MAX_RADIUS, best_radius + 2) + 1,
            ):
                red_coverage = max(
                    red_coverage,
                    _ring_coverage(redness, (x, y), candidate_radius, 40),
                )
            if red_coverage < AIM_ENEMY_RED_RING_MIN:
                continue
            center_red = _center_redness(redness, (x, y), best_radius)
            if center_red < center_red_min:
                continue
            candidates.append({
                "center": (x + offset[0], y + offset[1]),
                "radius": best_radius,
                "coverage": coverage,
                "center_red": center_red,
            })
    candidates.sort(key=lambda candidate: -candidate["coverage"])
    deduped = []
    for candidate in candidates:
        cx, cy = candidate["center"]
        if all(
            (cx - ox) ** 2 + (cy - oy) ** 2 > 20 ** 2
            for ox, oy in (item["center"] for item in deduped)
        ):
            deduped.append(candidate)
    return deduped


def _right_masks(image):
    """右侧窄条（x≥1600）的白环/红晕掩膜。

    右侧准星会叠在队伍 HUD 上，不能套 mask_interact：该掩膜不覆盖队伍 HUD，
    套上会把准星白环整片抹掉。
    """
    roi = image[
        AIM_ENEMY_ROI_TOP:-AIM_ENEMY_ROI_BOTTOM,
        AIM_ENEMY_RIGHT_STRIP_LEFT:,
    ]
    b, g, r = cv2.split(roi)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    min_channel = np.minimum(np.minimum(b, g), r)
    white = cv2.bitwise_and(
        (min_channel > AIM_ENEMY_WHITE_MIN).astype(np.uint8) * 255,
        subtract_blur(gray, 3, negative=False),
    )
    redness = r.astype(np.int16) - g.astype(np.int16)
    glow = cv2.dilate(
        (redness > AIM_ENEMY_RED_GLOW_MIN).astype(np.uint8) * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    return white, glow, redness


def enemy_candidates(image):
    """返回敌人准星候选点：红色连通块初筛 + 220×220 裁剪霍夫 + 白环/中心红校验。"""
    white, glow, redness = _enemy_masks(image)
    return _contour_candidates(
        redness, glow, white,
        AIM_ENEMY_RING_COVERAGE_MIN,
        AIM_ENEMY_CENTER_RED_MIN,
        (AIM_ENEMY_ROI_LEFT, AIM_ENEMY_ROI_TOP),
    )


def predict_right(image):
    """检测右侧 HUD 区域的准星，返回全屏坐标；没有则 None。"""
    white, glow, redness = _right_masks(image)
    candidates = _contour_candidates(
        redness, glow, white,
        AIM_ENEMY_RIGHT_COVERAGE_MIN,
        AIM_ENEMY_RIGHT_CENTER_RED_MIN,
        (AIM_ENEMY_RIGHT_STRIP_LEFT, AIM_ENEMY_ROI_TOP),
    )
    if not candidates:
        return None
    x, y = candidates[0]["center"]
    return int(x), int(y)


def predict_enemy(image):
    """检测敌人瞄准准星。

    Args:
        image: BGR 截图（1920x1080）。

    Returns:
        (draw, points)：draw 是只画出选中圆环的示意图；points 是选中中心组成的数组，
        没有检测到时为空数组。
    """
    candidates = enemy_candidates(image)
    draw = np.zeros(image.shape[:2], dtype=np.uint8)
    if not candidates:
        return draw, np.array([])
    best = candidates[0]
    cv2.circle(draw, best["center"], best["radius"], 255, 2)
    return draw, np.array([best["center"]])


def predict_item(image):
    """检测物品瞄准标记（开发中，尚未实机验证）。

    物品瞄准标记是白色十字 + 中心小圆环，外圈青色光晕；与敌人红晕准星区分开。
    返回 (draw, points)：draw 是只画出检测结果的白图，points 是标记中心数组（可能为空）。

    Args:
        image: BGR 截图（1920x1080）。
    """
    height, width = image.shape[:2]
    b, g, r = cv2.split(image)
    b = b.astype(np.int16)
    g = g.astype(np.int16)
    r = r.astype(np.int16)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    min_channel = np.minimum(np.minimum(b, g), r)
    white = cv2.bitwise_and(
        (min_channel > ITEM_WHITE_MIN).astype(np.uint8) * 255,
        subtract_blur(gray, 9, negative=False),
    )
    white = cv2.bitwise_and(white, mask_interact)

    cyanness = np.minimum(b, g) - r
    glow = cv2.dilate(
        (cyanness > ITEM_CYAN_GLOW_MIN).astype(np.uint8) * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    feature = cv2.bitwise_and(white, glow)

    circles = cv2.HoughCircles(
        feature,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=30,
        param1=80,
        param2=10,
        minRadius=ITEM_CENTER_RADIUS[0],
        maxRadius=ITEM_CENTER_RADIUS[1],
    )
    candidates = []
    if circles is not None:
        for raw_x, raw_y, _raw_radius in circles[0]:
            x, y = int(round(raw_x)), int(round(raw_y))
            y0, y1 = max(0, y - 40), min(height, y + 41)
            x0, x1 = max(0, x - 40), min(width, x + 41)
            glow_coverage = float((glow[y0:y1, x0:x1] > 0).mean())
            if glow_coverage < ITEM_GLOW_COVERAGE_MIN:
                continue
            arms = 0
            for angle in (0, 90, 180, 270):
                radians = np.deg2rad(angle)
                for distance in range(12, 42, 2):
                    sample_x = int(round(x + distance * np.cos(radians)))
                    sample_y = int(round(y + distance * np.sin(radians)))
                    if (0 <= sample_y < height and 0 <= sample_x < width
                            and white[sample_y, sample_x] > 0):
                        arms += 1
                        break
            if arms < ITEM_WHITE_ARM_MIN:
                continue
            candidates.append((glow_coverage, x, y))
    candidates.sort(key=lambda candidate: -candidate[0])
    points = np.array([(x, y) for _coverage, x, y in candidates])
    draw = np.zeros((height, width), dtype=np.uint8)
    for _coverage, x, y in candidates:
        cv2.circle(draw, (x, y), 40, 255, 2)
    return draw, points


def aimed_enemy(points_enemy) -> tuple[int, int] | None:
    if points_enemy is None:
        return None

    count = len(points_enemy)
    if count >= 2:
        CUS_LOGGER.debug(f"发现多个瞄准的敌人: {points_enemy}")
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
        CUS_LOGGER.debug(f"发现多个瞄准的物品，使用第一个点 {points_item}")
    except IndexError:
        pass
    try:
        point = points_item[0]
        return tuple(point)
    except IndexError:
        return None

_AIM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aim")


def _predict_main(image, item):
    """主 ROI 检测（敌人准星 + 可选的物品标记），不负责右侧窄条与调试显示。"""
    draw_item = None
    draw_enemy = None
    points_item = None
    points_enemy = None
    draw_enemy, points_enemy = predict_enemy(image)
    if item:
        draw_item, points_item = predict_item(image)
    kv = {'enemy': aimed_enemy(points_enemy), 'item': aimed_item(points_item)}
    if kv['enemy'] is not None or kv['item'] is not None:
        CUS_LOGGER.info(f'{factor}恍惚间看见了宇宙的「毁灭」: {kv}')
    return kv, draw_enemy, draw_item


def predict(image, enemy=True, item=True, debug=False):
    """预测敌人准星（主 ROI + 右侧窄条并行）与可选物品标记。

    主检测和右侧检测各占一个线程：右侧准星可能落在主 ROI 之外，但串行 fallback
    会让 95% 的负样本帧多等一次右侧检测；并行时墙钟只取两者较大值。
    主检测命中优先，主检测漏检时才等待并使用右侧结果。
    """
    if not enemy:
        kv, draw_enemy, draw_item = _predict_main(image, item)
        if debug:
            show_aim(draw_enemy, draw_item)
        return kv

    main_future = _AIM_EXECUTOR.submit(_predict_main, image, item)
    right_future = _AIM_EXECUTOR.submit(predict_right, image)
    kv, draw_enemy, draw_item = main_future.result()
    if kv['enemy'] is not None:
        if debug:
            show_aim(draw_enemy, draw_item)
        return kv

    try:
        right_point = right_future.result()
    except Exception as exc:  # 右侧检测失败不能影响主检测结果
        CUS_LOGGER.warning(f"右侧准星检测失败：{exc}")
        right_point = None
    if right_point is not None:
        kv['enemy'] = right_point
        CUS_LOGGER.info(f'{factor}恍惚间看见了宇宙的「毁灭」: {kv}')
        if debug and draw_enemy is not None:
            cv2.circle(draw_enemy, right_point, 40, 255, 2)
    if debug:
        show_aim(draw_enemy, draw_item)
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
