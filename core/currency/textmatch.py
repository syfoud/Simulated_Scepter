"""文本匹配：容忍 OCR 的漏字、错认形近字。

游戏里的名字常带间隔点（「银•金•彩」），OCR 会把点吃掉成「银金彩」，
偶尔还会把形近字认错（彩→采、代→伐）。这里统一做两件事：

1. `normalize()` 去掉分隔符与空白，先消掉"漏字"；
2. `best_match()` 在已知名字表里找最像的一条，按长度允许 0~2 个字的差异。

短名字（≤2 字）要求完全一致，避免「蓝海 / 蓝钻贵族」这种被糊到一起去。
"""

import re
from difflib import SequenceMatcher

_SEPARATORS = re.compile(r"[•·・‧\s\-—_]+")


def normalize(text):
    """去掉间隔点、空白、连接符，方便比较。"""
    return _SEPARATORS.sub("", text or "")


def _allowed_edits(length):
    if length <= 2:
        return 0
    return 1 if length <= 6 else 2


def similarity(a, b):
    """归一化后的相似度（0~1），长度不同也照算。"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def similar(a, b):
    """两个名字算不算同一个（按长度允许少量错字）。"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    if a == b:
        return True
    longest = max(len(a), len(b))
    return similarity(a, b) >= 1 - _allowed_edits(longest) / longest


def best_match(text, candidates):
    """在候选表里找最像的名字；都不够像就返回 None。

    距离相同时取相似度更高、且（相似度相同）先出现的那个，保证结果稳定。
    """
    text = normalize(text)
    if not text:
        return None
    best, best_score = None, 0.0
    for candidate in candidates:
        score = similarity(text, candidate)
        if score > best_score:
            best, best_score = candidate, score
    if best is None:
        return None
    longest = max(len(text), len(normalize(best)))
    if best_score >= 1 - _allowed_edits(longest) / longest:
        return best
    return None
