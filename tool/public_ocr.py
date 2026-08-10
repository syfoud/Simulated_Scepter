import json
from collections import defaultdict
from functools import cmp_to_key

import cv2 as cv
import numpy as np


def sort_text(text):
    def compare(item1, item2):
        x1, _, y1, _ = item1['box']
        x2, _, y2, _ = item2['box']
        if abs(y1 - y2) <= 7:
            return x1 - x2
        return y1 - y2
    text = sorted(text, key=cmp_to_key(compare))
    return text
def load_actions(json_path):
    res = defaultdict(list)
    with open(json_path, encoding="utf-8") as f:
        for i in json.load(f):
            res[i["name"]].append(i)
    return res


def clean_text(text, char=1):
    """
    清除内容中的特殊字符
    """
    symbols = r"[!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~—“”‘’«»„…·¿¡£¥€©®™°±÷×¶§‰]，。！？；：（）【】「」《》、￥ "
    if char:
        symbols += r"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    translator = str.maketrans('', '', symbols)
    return text.translate(translator)
def merge_text(text, char=1):
    return clean_text(''.join([i['raw_text'] for i in sort_text(text)]), char)
def merge(text):
    if len(text) == 0:
        return text
    text = sort_text(text)
    res = []
    merged = text[0]
    for i in range(1, len(text)):
        if abs(text[i]['box'][2] - merged['box'][2]) <= 10 and abs(text[i]['box'][3] - merged['box'][3]) <= 10 and abs(text[i]['box'][0] - merged['box'][1]) <= 35:
            merged['raw_text'] += text[i]['raw_text']
            merged['box'][1] = text[i]['box'][1]
        else:
            res.append(merged)
            merged = text[i]
    res.append(merged)
    return res


def filter_non_white(image, mode=0):
    if not mode:
        return image
    hsv_image = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    lower_white = np.array([0, 0, 160])
    upper_white = np.array([180, 40, 255])
    mask = cv.inRange(hsv_image, lower_white, upper_white)
    if mode == 1:
        filtered_image = cv.bitwise_and(image, image, mask=mask)
        return filtered_image
    elif mode == 2:
        lower_black = np.array([0, 0, 0])
        upper_black = np.array([180, 40, 50])
        mask_black = cv.inRange(hsv_image, lower_black, upper_black)
        kernel = np.ones((5, 30), np.uint8)
        mask_black = cv.dilate(mask_black, kernel, iterations=1)
        filtered_image = cv.bitwise_and(image, image, mask=mask & mask_black)
        return filtered_image


def box_contain(box_out, box_in, redundancy):
    """
    是否在目标范围与误差内包含指定的文本框
    Args:
        :param box_out: 一个指定的范围框[左上x,右下x,左上y,右下y]
        :param redundancy: 误差范围
        :param box_in:获取到的范围框

    return:
        查找获取到的范围框是否位于指定范围框内
    """
    if type(redundancy) in [tuple, list]:
        r = redundancy
    else:
        r = (redundancy, redundancy)
    return box_out[0]<=box_in[0]+r[0] and box_out[1]>=box_in[1]-r[0] and box_out[2]<=box_in[2]+r[1] and box_out[3]>=box_in[3]-r[1]
