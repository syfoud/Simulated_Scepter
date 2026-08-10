import os
import re
from datetime import datetime

import cv2
import numpy as np

from route import PATHS
from tool.log import CUS_LOGGER
from tool.utils.image_tool import find_image_in_folder

ROLL_COUNT_REGION = (1660, 707, 1700, 740)
CHEAT_COUNT_REGION = (1325, 707, 1365, 740)


def _normalize_roll_count_image(image):
    """Extract and center the light-colored roll-count glyph for matching."""
    if image is None or image.size == 0:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # A low threshold keeps the differently anti-aliased edges of the same
    # digit consistent between the cheat-count and reroll-count positions.
    _, mask = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
    points = cv2.findNonZero(mask)
    if points is None:
        return None

    x, y, width, height = cv2.boundingRect(points)
    glyph = mask[y:y + height, x:x + width]
    max_width, max_height = 32, 27
    scale = min(max_width / width, max_height / height)
    resized = cv2.resize(
        glyph,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_NEAREST,
    )
    normalized = np.zeros((33, 40), dtype=np.uint8)
    offset_x = (normalized.shape[1] - resized.shape[1]) // 2
    offset_y = (normalized.shape[0] - resized.shape[0]) // 2
    normalized[
        offset_y:offset_y + resized.shape[0],
        offset_x:offset_x + resized.shape[1],
    ] = resized
    return normalized


def _roll_count_similarity(first, second):
    first_mask = _normalize_roll_count_image(first)
    second_mask = _normalize_roll_count_image(second)
    if first_mask is None or second_mask is None:
        return -1.0
    result = cv2.matchTemplate(first_mask, second_mask, cv2.TM_CCOEFF_NORMED)
    return float(result[0, 0])


def _save_unmatched_roll_count(crop, unmatched_dir):
    """Save a new unmatched sample, while avoiding near-identical duplicates."""
    os.makedirs(unmatched_dir, exist_ok=True)
    for filename in os.listdir(unmatched_dir):
        if not filename.lower().endswith(".png"):
            continue
        sample = cv2.imread(os.path.join(unmatched_dir, filename), cv2.IMREAD_COLOR)
        if _roll_count_similarity(crop, sample) >= 0.98:
            return os.path.join(unmatched_dir, filename)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f.png")
    save_path = os.path.join(unmatched_dir, filename)
    return save_path if cv2.imwrite(save_path, crop) else None


def _action_count_template_value(filename):
    """Return the value from ``7.png`` or a variant such as ``7_dark.png``."""
    stem, extension = os.path.splitext(filename)
    if extension.lower() != ".png":
        return None
    match = re.fullmatch(r"(\d+)(?:_.+)?", stem)
    return int(match.group(1)) if match else None


def _match_action_count_in_region(or_image, region, count_name, threshold=0.9,
                                  template_dir=None, unmatched_dir=None):
    """Recognize one action count using the shared count-digit templates."""
    x1, y1, x2, y2 = region
    if or_image is None or or_image.shape[0] < y2 or or_image.shape[1] < x2:
        CUS_LOGGER.warning(f"{count_name}次数识别失败：截图尺寸不足，无法裁剪指定区域")
        return None

    crop = or_image[y1:y2, x1:x2].copy()
    template_dir = template_dir or os.path.join(PATHS["image"], "roll_count_num")
    unmatched_dir = unmatched_dir or os.path.join(template_dir, "unmatched")

    best_value = None
    best_score = -1.0
    if os.path.isdir(template_dir):
        for filename in sorted(os.listdir(template_dir)):
            template_value = _action_count_template_value(filename)
            if template_value is None:
                continue
            template = cv2.imread(os.path.join(template_dir, filename), cv2.IMREAD_COLOR)
            score = _roll_count_similarity(crop, template)
            if score > best_score:
                best_score = score
                best_value = template_value

    if best_value is not None and best_score >= threshold:
        return best_value

    save_path = _save_unmatched_roll_count(crop, unmatched_dir)
    if save_path:
        CUS_LOGGER.warning(
            f"未识别{count_name}次数（最高相似度 {best_score:.3f}），样本已保存至 {save_path}"
        )
    else:
        CUS_LOGGER.warning(f"未识别{count_name}次数，且样本保存失败")
    return None


def match_roll_count_in_region(or_image, threshold=0.9, template_dir=None,
                               unmatched_dir=None):
    """Recognize the reroll count in [1660, 707, 1700, 740]."""
    return _match_action_count_in_region(
        or_image,
        ROLL_COUNT_REGION,
        "重投",
        threshold,
        template_dir,
        unmatched_dir,
    )


def match_cheat_count_in_region(or_image, threshold=0.9, template_dir=None,
                                unmatched_dir=None):
    """Recognize the cheat count in [1325, 707, 1365, 740]."""
    return _match_action_count_in_region(
        or_image,
        CHEAT_COUNT_REGION,
        "作弊",
        threshold,
        template_dir,
        unmatched_dir,
    )


def extract_number(s):
    """从字符串中提取 + 开头、% 结尾的中间数字"""
    match = re.search(r'\+(\d+)%', s)
    return match.group(1) if match else None


def match_numbers_in_region(or_image, threshold=0.9):
    """
    在指定区域匹配数字模板

    Args:
        or_image: 输入图像数组
        threshold: 匹配阈值
    Returns:
        str: 匹配结果列表，已按从左到右排序
    """
    or_image = or_image[691:1003, 80:195].copy()
    full_folder_path = os.path.join(PATHS["image"], "nums")
    templates = []
    if os.path.exists(full_folder_path):
        for file in os.listdir(full_folder_path):
            if file.lower().endswith('.png'):
                template_name = os.path.splitext(file)[0]
                templates.append(template_name)
        templates.sort()
    all_matches = []
    for template_name in templates:
        template = find_image_in_folder("nums", template_name)
        th, tw = template.shape[:2]
        res = cv2.matchTemplate(or_image, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs, ys):
            all_matches.append(
                {'name': template_name, 'location': (x + 80, y + 691), 'similarity': round(float(res[y, x]), 3),
                 'size': (tw, th)})

    # NMS 去重
    boxes = [[m['location'][0] - 80, m['location'][1] - 691, m['size'][0], m['size'][1]] for m in all_matches]
    scores = [m['similarity'] for m in all_matches]
    indices = cv2.dnn.NMSBoxes(boxes, scores, 0.0, 0.3)
    all_matches = [all_matches[i] for i in indices]

    sorted_matches = sorted(all_matches, key=lambda x: x['location'][0] + x['size'][0] / 2)
    number_str = ''.join([m['name'] for m in sorted_matches])
    return number_str


def match_skill_numbers_in_region(or_image, threshold=0.9):
    """
    在指定区域匹配数字模板

    Args:
        or_image: 输入图像数组
        threshold: 匹配阈值
    Returns:
        str: 匹配结果列表，已按从左到右排序
    """
    or_image = or_image[823:870, 1675:1713].copy()
    gray = cv2.cvtColor(or_image, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 200, 255)
    white_region = cv2.bitwise_and(gray, gray, mask=mask)
    best_match = None
    best_score = -1

    for template_name in ["0", "1", "2", "3", "4", "5", "6", "7", "8"]:
        template = find_image_in_folder("gray_image/num", template_name)
        res = cv2.matchTemplate(white_region, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = int(template_name)

    return best_match if best_score >= threshold else None
