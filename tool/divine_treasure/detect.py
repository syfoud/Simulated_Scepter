"""战斗区域画面判据：全部取自实机样本与仓库既有实现。"""

import cv2
import numpy as np

from route import PATHS

# 顶部敌标记模板（主 checkout 未跟踪资源；缺失时返回 None）
ENEMY_TEMPLATE = PATHS["image"] + "/wanderland/enemy.png"
ENEMY_BAR_HEIGHT = 0.12
ENEMY_TEMPLATE_THRESHOLD = 0.7

# 战斗判定：沿用 wanderland.py: _battle_hud_visible 的 OCR 标签，再以底部橙色占比兜底
BATTLE_LABELS = ("行动中", "自动战斗", "战斗中")
BATTLE_LABEL_BOX = (0, 1920, 0, 220)
BATTLE_HUD_BAND = (0.10, 0.90, 0.90, 1.00)
BATTLE_HUD_ORANGE_MIN = 0.05   # 低于此为菜单/卡牌页（实测祝福页 0.0006）
BATTLE_HUD_ORANGE_MAX = 0.80   # 大世界 0.80+（土黄地面），战斗界面约 0.27
ORANGE_LOW, ORANGE_HIGH = (0, 80, 80), (25, 255, 255)

# 粉色随意门：门框为大块粉红，填充度高（窗帘等碎片填充度低）
DOOR_LOW, DOOR_HIGH = (150, 60, 110), (178, 255, 255)
DOOR_SCAN_X = (0.15, 0.80)
DOOR_SCAN_Y = (0.20, 0.95)


def _components(mask, min_area, max_area=None):
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area or (max_area is not None and area > max_area):
            continue
        yield (
            int(stats[index, cv2.CC_STAT_WIDTH]),
            int(stats[index, cv2.CC_STAT_HEIGHT]),
            area,
            (float(centers[index][0]), float(centers[index][1])),
        )


def enemy_marker(image, template_path=None):
    """顶部敌标记中心 (x, y)；标记存在表示该区域仍有敌人。无模板返回 None。

    注意：模型在远处不渲染该标记（样本实测初始帧只有 0.508），
    因此它只适合"贴近后确认"，搜索阶段要靠前进把距离拉近。
    """
    path = template_path or ENEMY_TEMPLATE
    data = np.fromfile(path, dtype=np.uint8)
    template = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if template is None:
        return None
    bar = image[0:int(image.shape[0] * ENEMY_BAR_HEIGHT), :]
    if bar.shape[0] < template.shape[0] or bar.shape[1] < template.shape[1]:
        return None
    result = cv2.matchTemplate(bar, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, location = cv2.minMaxLoc(result)
    if best < ENEMY_TEMPLATE_THRESHOLD:
        return None
    return (location[0] + template.shape[1] // 2, location[1] + template.shape[0] // 2)


def battle_labels_in(text):
    """战斗界面顶部标签判定；纯文本，便于离线测试。"""
    return any(label in text for label in BATTLE_LABELS)


def battle_hud_visible(image, ocr=None):
    """是否处于战斗界面。

    优先用 OCR 读顶部标签（wanderland.py: _battle_hud_visible 同款，实机已验证）；
    没有 OCR 时退回底部橙色占比：大世界 0.80+，战斗约 0.27，菜单/卡牌页 0.0006。
    """
    if ocr is not None:
        text = ocr(image, BATTLE_LABEL_BOX)
        if battle_labels_in(text):
            return True
    height, width = image.shape[:2]
    x0, x1 = int(width * BATTLE_HUD_BAND[0]), int(width * BATTLE_HUD_BAND[1])
    y0, y1 = int(height * BATTLE_HUD_BAND[2]), int(height * BATTLE_HUD_BAND[3])
    band = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(ORANGE_LOW), np.array(ORANGE_HIGH))
    ratio = float(mask.mean()) / 255.0
    return BATTLE_HUD_ORANGE_MIN <= ratio < BATTLE_HUD_ORANGE_MAX


def detect_door(image):
    """粉色随意门中心 (x, y)；门未入画返回 None。交互文字只在门口出现，故必须靠颜色找门。"""
    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (7, 7), 0), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(DOOR_LOW), np.array(DOOR_HIGH))
    height, width = image.shape[:2]
    region = np.zeros_like(mask)
    x0, x1 = int(width * DOOR_SCAN_X[0]), int(width * DOOR_SCAN_X[1])
    y0, y1 = int(height * DOOR_SCAN_Y[0]), int(height * DOOR_SCAN_Y[1])
    region[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    best = None
    for w, h, area, (cx, cy) in _components(region, 4000):
        if area / float(w * h) < 0.30:
            continue
        if best is None or area > best[0]:
            best = (area, (int(cx), int(cy)))
    return None if best is None else best[1]


def detect_enemy_circle(image, band=(0.15, 0.45)):
    """怪物红圈中心 (x, y)。实测与角色红发连成同一连通域，仅作参考，不作寻路判据。"""
    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 200, 45)), np.array((15, 255, 110)))
    height = image.shape[0]
    y0, y1 = int(height * band[0]), int(height * band[1])
    region = np.zeros_like(mask)
    region[y0:y1, :] = mask[y0:y1, :]
    best = None
    for w, h, area, (cx, cy) in _components(region, 60):
        if not 0.5 <= w / max(h, 1) <= 2.0:
            continue
        if best is None or area > best[0]:
            best = (area, (int(cx), int(cy)))
    return None if best is None else best[1]
