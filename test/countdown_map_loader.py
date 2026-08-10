"""倒计时地图的延迟图像识别适配层。

只有工作线程真正加载图片时才导入 OpenCV 和生产环境识图模块，因此主窗口可先
显示，纯 MC 后端和单元测试也不会被图像依赖绑住。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

try:
    from .countdown_backend import CountdownMap, DEFAULT_MAP_FILES
except ImportError:
    from countdown_backend import CountdownMap, DEFAULT_MAP_FILES


_images_loaded = False


@dataclass(frozen=True)
class PreparedCountdownMap:
    image_path: str
    model: CountdownMap
    width: int
    height: int
    start_detected: bool
    start_crop_rect: Optional[tuple]


def _merge_match_groups(*groups) -> list:
    """合并两套节点模板结果，并按中心位置去掉同一节点的重复框。"""
    merged = []
    for match in sorted((item for group in groups for item in group),
                        key=lambda item: float(item.get("similarity", 0)), reverse=True):
        x, y = match["location"]
        width, height = match["size"]
        center_x, center_y = x + width / 2, y + height / 2
        duplicate = False
        for existing in merged:
            other_x, other_y = existing["location"]
            other_w, other_h = existing["size"]
            distance = ((center_x - other_x - other_w / 2) ** 2
                        + (center_y - other_y - other_h / 2) ** 2) ** 0.5
            if distance <= max(12.0, min(width, height, other_w, other_h) * 0.45):
                duplicate = True
                break
        if not duplicate:
            merged.append(dict(match))
    return merged


def default_map_paths() -> tuple[str, str, str]:
    example_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example")
    return tuple(os.path.abspath(os.path.join(example_dir, name)) for name in DEFAULT_MAP_FILES)


def load_countdown_map(image_path: str, plane: int = 1, match_mode: int = 1,
                       progress: Optional[Callable[[int, int, str], None]] = None,
                       cancelled: Optional[Callable[[], bool]] = None) -> PreparedCountdownMap:
    """复用生产环境识图逻辑，失败时才把最左节点作为起点。"""
    def checkpoint(value, text):
        if cancelled and cancelled():
            raise InterruptedError("地图识别已取消")
        if progress:
            progress(value, 6, text)

    checkpoint(0, "加载图像资源")
    import cv2
    import numpy as np
    from importing import load_img
    from tool.utils.analysis_map import (
        build_rightward_graph, compute_start_point_from_crop,
        detect_infectable_nodes, match_multiple_targets,
    )

    global _images_loaded
    if not _images_loaded:
        load_img()
        _images_loaded = True
    checkpoint(1, "读取地图")
    image_path = os.path.abspath(image_path)
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"无法读取图像: {image_path}")

    checkpoint(2, "识别地图节点")
    requested_mode = 1 if int(match_mode) == 1 else 2
    primary = match_multiple_targets(
        image, mode=requested_mode, threshold=0.5, color_image=image)
    plausible = (len(primary) >= 5
                 and any(item.get("name") in ("boss", "head") for item in primary))
    alternatives = [primary]
    if int(match_mode) == 1 or not plausible:
        secondary = match_multiple_targets(
            image, mode=2 if requested_mode == 1 else 1, threshold=0.5, color_image=image)
        alternatives.extend((secondary, _merge_match_groups(primary, secondary)))

    def quality(found):
        if not found:
            return (0, 0, 0, 0, 0.0)
        candidate_nodes, candidate_edges, candidate_start = build_rightward_graph(found, start=None)
        reachable, pending = set(), [candidate_start]
        while pending:
            node = pending.pop()
            if node not in reachable:
                reachable.add(node)
                pending.extend(candidate_edges.get(node, ()))
        has_end = any(match.get("name") in ("boss", "head") for match in found)
        edge_count = sum(len(candidate_edges.get(node, ())) for node in reachable)
        confidence = sum(float(match.get("similarity", 0)) for match in found)
        return (int(has_end), len(reachable), edge_count, len(candidate_nodes), confidence)

    matches = max(alternatives, key=quality)
    if not matches:
        raise ValueError("没有识别到任何地图节点，请检查图片或匹配模式")

    boss_x = [match["location"][0] for match in matches
              if match.get("name") in ("boss", "head")]
    if boss_x:
        matches = [match for match in matches if match["location"][0] <= max(boss_x)]
    checkpoint(3, "识别感染节点")
    infected = set(detect_infectable_nodes(image, matches))

    checkpoint(4, "识别当前起点")
    leftmost_x = min(match["location"][0] + match["size"][0] / 2 for match in matches)
    preferred_mode = 3 if int(plane) == 3 else 2
    candidates = []
    for mode in (preferred_mode, 2 if preferred_mode == 3 else 3):
        for threshold in (0.9, 0.4):
            center, details = compute_start_point_from_crop(
                image, mode=mode, th=threshold, return_details=True)
            if center is not None and center[0] <= leftmost_x + 50:
                candidates.append((float(details.get("match_score", 0)),
                                   int(mode == preferred_mode), center, details))
                break
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))

    checkpoint(5, "构建有向地图")
    selected = None
    for _score, _preferred, center, details in candidates:
        nodes, edges, start_idx = build_rightward_graph(matches, start=center)
        if edges.get(start_idx):
            selected = (nodes, edges, start_idx, details)
            break
    if selected is None:
        nodes, edges, start_idx = build_rightward_graph(matches, start=None)
        crop_rect = None
        start_detected = False
    else:
        nodes, edges, start_idx, details = selected
        crop_rect = tuple(details["crop_rect"]) if details else None
        start_detected = True

    if start_idx is None or not nodes:
        raise ValueError("地图图结构为空")
    if not any(edges.values()):
        raise ValueError("只识别到孤立节点，无法构成可推演路径；请更换原始地图截图或匹配模板")
    model = CountdownMap(nodes, edges, start_idx, infected)
    # 在这里验证 DAG，错误图片不会拖到采样阶段才失败。
    model.longest_steps_from(start_idx)
    checkpoint(6, "地图识别完成")
    height, width = image.shape[:2]
    return PreparedCountdownMap(
        image_path=image_path,
        model=model,
        width=int(width), height=int(height),
        start_detected=start_detected,
        start_crop_rect=crop_rect,
    )


__all__ = ["PreparedCountdownMap", "default_map_paths", "load_countdown_map"]
