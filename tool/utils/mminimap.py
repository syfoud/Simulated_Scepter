import time

import cv2
import numpy as np
from scipy import signal

from tool.GLOBAL import factor
from tool.log import CUS_LOGGER
from tool.utils.image_tool import find_image_in_folder
from tool.utils.minimap_util import (
    DIRECTION_ARROW_COLOR,
    DIRECTION_RADIUS,
    DIRECTION_ROTATION_SCALE,
    DIRECTION_SEARCH_SCALE,
    MINIMAP_RADIUS,
    POSITION_FEATURE_PAD,
    POSITION_MOVE_PATCH,
    POSITION_SEARCH_RADIUS,
    POSITION_SEARCH_SCALE,
    ArrowRotateMap,
    ArrowRotateMapAll,
    ImageNotSupported,
    PositionPredictState,
    RotationRemapData,
    area_limit,
    area_offset,
    area_pad,
    color_similarity_2d,
    convolve,
    crop,
    cubic_find_maximum,
    deal_minimap,
    get_bbox,
    get_minimap,
    get_minimap_center,
    image_center_crop,
    image_size,
    peak_confidence,
    re_get_position,
    rgb2yuv,
    subtract_blur,
)


# 低于已有地图匹配下限时不更新搜索原点。
POSITION_MIN_SIMILARITY = 0.01
# 合成噪声与真实 4K 裁剪回归支持的箭头相关系数下限。
DIRECTION_MIN_SIMILARITY = 0.35


def update_rotation(or_image=None, minimap=None, *, with_confidence=False):
    """识别小地图视角角度。

    Args:
        or_image: 原始截图；传入 minimap 时不使用。
        minimap: 已裁剪的小地图。
        with_confidence: 同时返回角度峰值相对次峰的显著性。

    Returns:
        默认返回角度；请求置信度时返回 (角度, 0～1 的峰值显著性)。
    """
    d = MINIMAP_RADIUS * 2
    scale = 1
    if minimap is None:
        minimap = get_minimap(or_image, radius=MINIMAP_RADIUS)
    image = rgb2yuv(minimap)[:, :, 1].copy()
    cv2.subtract(src1=184, src2=image, dst=image)
    cv2.GaussianBlur(image, (3, 3), 0, dst=image)
    remap = cv2.remap(image, *RotationRemapData(), cv2.INTER_LINEAR)[d * 1 // 10:d * 6 // 10].astype(np.float32)

    remap = cv2.resize(remap, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    gradx = cv2.Scharr(remap, cv2.CV_32F, 1, 0)
    para = {
        'height': 35,
        'wlen': d * scale,
    }
    hist_l = np.bincount(signal.find_peaks(gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    r = np.bincount(signal.find_peaks(-gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    hist_l, r = np.maximum(hist_l - r, 0), np.maximum(r - hist_l, 0)

    conv0 = []
    kernel = 2 * scale
    r_expanded = np.concatenate([r, r, r])
    r_length = len(r)
    def roll_r(shift):
        return r_expanded[r_length - shift:r_length * 2 - shift]

    def convolve_r(ker, shift):
        return sum(roll_r(shift + i) * (ker - abs(i)) // ker for i in range(-ker + 1, ker))

    for offset in range(-kernel + 1, kernel):
        result = hist_l * convolve_r(ker=3 * kernel, shift=-d * scale // 4 + offset)
        conv0 += [result]

    conv0 = np.maximum(conv0, 1)
    maximum = np.max(conv0, axis=0)
    rotation_confidence = round(peak_confidence(maximum), 3)
    if rotation_confidence > 0.3:
        # 匹配良好
        result = maximum
    else:
        # 再次卷积以减少噪声
        average = np.mean(conv0, axis=0)
        minimum = np.min(conv0, axis=0)
        result = convolve(maximum * average * minimum, 2 * scale)
        rotation_confidence = round(peak_confidence(result), 3)

    # 将匹配点转换为角度
    degree = np.argmax(result) / (d * scale) * 360 + 135
    degree = int(degree % 360)

    if with_confidence:
        return degree, rotation_confidence
    return degree


def update_direction(or_image=None, minimap=None, *, with_confidence=False, diagnostics=None):
    """识别角色箭头方向，无法可靠识别时返回 None。

    Args:
        or_image: 原始截图；传入 minimap 时不使用。
        minimap: 已裁剪的箭头区域。
        with_confidence: 同时返回原始归一化模板相关系数。
        diagnostics: 可选输出字典，记录同一次识别的门控原因与分数。

    Returns:
        默认返回方向；请求置信度时返回 (方向或 None, 相似度)。
    """
    if diagnostics is None:
        diagnostics = {}
    diagnostics["reason"] = "arrow_missing"
    if minimap is None:
        minimap = get_minimap(or_image, DIRECTION_RADIUS)

    image = color_similarity_2d(minimap, color=DIRECTION_ARROW_COLOR)
    arrow_mask = np.uint8(image > 128)
    pixels = cv2.countNonZero(arrow_mask)
    diagnostics["arrow_pixels"] = pixels
    if pixels < 8:
        if with_confidence:
            return None, 0.0
        return None
    count, _, stats, _ = cv2.connectedComponentsWithStats(arrow_mask, connectivity=8)
    largest_component = int(np.max(stats[1:, cv2.CC_STAT_AREA])) if count > 1 else 0
    diagnostics["largest_component"] = largest_component
    # 箭头应形成连续色块；随机同色噪点无法主导整块前景。
    if largest_component < pixels * 0.2:
        diagnostics["reason"] = "arrow_fragmented"
        if with_confidence:
            return None, 0.0
        return None

    try:
        area = area_pad(get_bbox(image, threshold=128), pad=-1)
        area = area_limit(area, (0, 0, *image_size(image)))
    except ImageNotSupported:
        diagnostics["reason"] = "arrow_bounds"
        if with_confidence:
            return None, 0.0
        return None

    diagnostics["arrow_bounds"] = tuple(int(value) for value in area)
    image = crop(image, area=area, copy=False)
    scale = DIRECTION_ROTATION_SCALE * DIRECTION_SEARCH_SCALE
    mapping = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    if mapping.size < 16 or not np.ptp(mapping):
        diagnostics["reason"] = "arrow_flat"
        if with_confidence:
            return None, 0.0
        return None

    raw_result = cv2.matchTemplate(ArrowRotateMap, mapping, cv2.TM_CCOEFF_NORMED)
    _, coarse_sim, _, _ = cv2.minMaxLoc(raw_result)
    diagnostics["coarse_score"] = float(coarse_sim) if np.isfinite(coarse_sim) else None
    if not np.isfinite(coarse_sim) or coarse_sim < DIRECTION_MIN_SIMILARITY:
        diagnostics["reason"] = "arrow_coarse"
        if with_confidence:
            return None, float(coarse_sim) if np.isfinite(coarse_sim) else 0.0
        return None
    result = subtract_blur(raw_result, 5)
    _, _, _, loca = cv2.minMaxLoc(result)
    loca = np.array(loca) / DIRECTION_SEARCH_SCALE // (DIRECTION_RADIUS * 2)

    degree = int((loca[0] + loca[1] * 8) * 5)

    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * 0.5)

    row = int(degree // 8) + 45
    row = (row - 2, row + 3)
    row = (to_map(row[0]) - 5, to_map(row[1]) + 5)
    precise_map = ArrowRotateMapAll[row[0]:row[1], :].copy()

    raw_result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(raw_result, 5)

    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2) * 0.5)

    # 定角只使用前三行、每行八个候选；裁剪余量产生的边缘峰不属于
    # 这些角度。置信度必须取同一候选区，不能被区域外的高通峰替代。
    _, _, _, precise_loc = cv2.minMaxLoc(result[:to_map(3), :to_map(8)])

    def get_precise_sim(d):
        y, x = divmod(d, 8)
        im = result[to_map(y):to_map(y + 1), to_map(x):to_map(x + 1)]
        _, sim, _, _ = cv2.minMaxLoc(im)
        return sim

    precise = np.array([[get_precise_sim(_) for _ in range(24)]])
    _, precise_loca = cubic_find_maximum(precise, precision=0.1)
    precise_loca = degree // 8 * 8 - 16 + precise_loca[0]

    # 高通滤波后的峰值用于定角，原始归一化相关系数才可解释为模板相似度。
    direction_similarity = float(raw_result[precise_loc[1], precise_loc[0]])
    diagnostics["precise_score"] = direction_similarity if np.isfinite(direction_similarity) else None
    direction = round(precise_loca % 360, 1)
    if not np.isfinite(direction_similarity) or direction_similarity < DIRECTION_MIN_SIMILARITY:
        diagnostics["reason"] = "arrow_precise"
        if with_confidence:
            return None, round(direction_similarity, 3) if np.isfinite(direction_similarity) else 0.0
        return None
    diagnostics["reason"] = "ok"
    if with_confidence:
        return direction, round(direction_similarity, 3)
    return direction


def show_minimap(image, rotation, direction=0):
    CUS_LOGGER.debug(f"视角: {rotation}, 角色朝向: {direction}")
    position = np.array((93, 93)).astype(int)

    def vector(degree):
        degree = np.deg2rad(degree - 90)
        point = np.array(position) + np.array((np.cos(degree), np.sin(degree))) * 30
        return point.astype(int)

    image = cv2.circle(image, position, radius=2, color=(0, 0, 255), thickness=-1)
    image = cv2.line(image, position, vector(direction), color=(0, 255, 0), thickness=1)  # 绿线
    image = cv2.line(image, position, vector(rotation), color=(255, 0, 0), thickness=1)  # 蓝线
    cv2.imshow('MinimapTracking', image)
    cv2.waitKey(0)
def _predict_precise_position(state):
    """
    Args:
        result (PositionPredictState): 结果状态

    Returns:
        PositionPredictState
    """
    size = state.size
    scale = state.scale
    search_area = state.search_area
    result = state.result
    loca = state.loca
    local_loca = state.local_loca

    precise = crop(result, area=area_offset((-4, -4, 4, 4), offset=loca), copy=False)
    precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.05)
    precise_loca -= 5

    state.precise_sim = precise_sim
    state.precise_loca = precise_loca

    # 在search_image上的位置
    lookup_loca = precise_loca + local_loca + size * scale / 2
    # 在GIMAP上的位置
    global_loca = (lookup_loca + search_area[:2]) / POSITION_SEARCH_SCALE
    # 不知道为什么，但result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
    global_loca += POSITION_MOVE_PATCH
    # 移动到地图的原点
    global_loca -= POSITION_FEATURE_PAD

    state.global_loca = global_loca

    return state

class PositionPredict:
    def __init__(self, position: tuple[float, float]= (0, 0)):
        self.position = position
        self.set_now_map(1)
        self.rotation=None
        self.direction=None
        self.rotation_confidence = 0.0
        self.direction_similarity = 0.0
        self._last_direction_warning = float("-inf")
        self.scale=1.00
    def _predict_position(self,image, scale=1.0):
        """
        Args:
            image: 图像
            scale: 缩放比例

        Returns:
            PositionPredictState:
        """
        scale *= POSITION_SEARCH_SCALE
        local = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        size = np.array(image_size(image))
        if sum(self.position) > 0:
            search_position = np.array(self.position, dtype=np.int64)
            search_position += POSITION_FEATURE_PAD
            search_size = np.array(image_size(local)) * POSITION_SEARCH_RADIUS
            search_half = (search_size // 2).astype(np.int64)
            search_area = area_offset((0, 0, *(search_half * 2)), offset=-search_half)
            search_area = area_offset(search_area, offset=np.multiply(search_position, POSITION_SEARCH_SCALE))
            search_area = np.array(search_area).astype(np.int64)
            search_image = crop(self.assets_floor_feat, search_area, copy=False)
            result_mask = crop(self.assets_floor_outside_mask, search_area, copy=False)
        else:
            search_area = (0, 0, *image_size(self.assets_floor_feat))
            search_image = self.assets_floor_feat
            result_mask = self.assets_floor_outside_mask

        result = cv2.matchTemplate(search_image, local, cv2.TM_CCOEFF_NORMED)

        result_mask = ~image_center_crop(result_mask, size=image_size(result)).astype(bool)
        result[result_mask] = 0
        _, sim, _, loca = cv2.minMaxLoc(result)

        # 高斯滤波获取局部最大值
        local_maximum = subtract_blur(result, radius=5)
        # 相乘以去除次级峰值
        cv2.multiply(local_maximum, result, dst=local_maximum)
        cv2.multiply(local_maximum, 10, dst=local_maximum)
        _, local_sim, _, local_loca = cv2.minMaxLoc(local_maximum)
        precise_loca = np.array((0, 0))
        precise_sim = result[local_loca[1], local_loca[0]]
        state = PositionPredictState(
            size=size, scale=scale,
            search_area=search_area, search_image=search_image, result_mask=result_mask, result=result,
            sim=sim, loca=loca, local_sim=local_sim, local_loca=local_loca,
            precise_sim=precise_sim, precise_loca=precise_loca,
        )

        # 在search_image上的位置
        lookup_loca = precise_loca + local_loca + size * scale / 2
        # 在GIMAP上的位置
        global_loca = (lookup_loca + search_area[:2]) / POSITION_SEARCH_SCALE
        # 不知道为什么，但result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
        global_loca += POSITION_MOVE_PATCH
        # 移动到地图的原点
        global_loca -= POSITION_FEATURE_PAD

        state.global_loca = global_loca

        return state
    def update_position(self,image,scale_list=[1.00, 1.05, 1.10, 1.15, 1.20, 1.25],update=True):
        """
        获取GIMAP上的位置，耗时约6.57ms。

        将设置以下属性：
        - position_similarity
        - position
        - position_scene
        """
        image = deal_minimap(image)
        best_sim = -1.0
        best_scale = 1.0
        best_state = None
        # 步行时缩放为1.20
        # 跑步时缩放为1.25
        for scale in scale_list:
            state = self._predict_position(image, scale)
            # print([np.round(i, 3) for i in [scale, state.sim, state.local_sim, state.global_loca]])
            if state.sim > best_sim:
                best_sim = state.sim
                best_scale = scale
                best_state = state

        best_state = _predict_precise_position(best_state)

        position_similarity = round(best_state.precise_sim, 3)
        if update and position_similarity > POSITION_MIN_SIMILARITY:
            self.position = tuple(np.round(best_state.global_loca, 1))
            self.scale=round(best_scale, 3)
            position=self.position
            CUS_LOGGER.debug(f"更新位置: {position}最佳缩放{self.scale}")
        else:
            position = tuple(np.round(best_state.global_loca, 1))
        return position, position_similarity

    def draw_position_on_map(self, raidus=90.0,show=True):
        """
        在assets_floor_feat上绘制当前位置对应的点和小地图范围

        Args:
            radius (int): 小地图半径范围

        Returns:
            None
        """
        # 创建assets_floor_feat的副本用于绘制
        CUS_LOGGER.debug(f"绘制位置: {self.position}")
        map_with_position = self.assets_floor_feat.copy()

        # 将全局坐标转换为地图坐标反向执行坐标变换
        map_position=re_get_position(self.position)

        # 将灰度图转换为BGR彩色图以便使用红色
        map_color = cv2.cvtColor(map_with_position, cv2.COLOR_GRAY2BGR)

        # 绘制红色小圆点标记位置中心
        cv2.circle(map_color,
                   tuple(map_position),
                   radius=3,  # 更小的圆点半径
                   color=(0, 0, 255),  # 红色 (BGR格式)
                   thickness=-1)  # 填充圆点

        # 绘制红色圆形标记小地图范围
        cv2.circle(map_color,
                   tuple(map_position),
                   radius=int(raidus * POSITION_SEARCH_SCALE),  # 根据实际小地图半径绘制
                   color=(0, 0, 255),  # 红色
                   thickness=2)  # 圆形边框

        # 显示结果
        if show:
            cv2.imshow("Position on Map", map_color)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return map_color
    def set_now_map(self,map_num):
        CUS_LOGGER.info(f"{factor}设置当前地图为{map_num}号大地图")
        self.map_num=map_num
        feat_name = f'map_{map_num}f.png'
        mask_img_name = f'map_{map_num}a.png'
        self.assets_floor_feat = find_image_in_folder('gray_image/', feat_name, search_subfolders=True)
        self.assets_floor_outside_mask = find_image_in_folder('gray_image/', mask_img_name, search_subfolders=True)
    def match_multiple_maps(self,image,show_result= False):
        """
        在多个地图中匹配最佳位置
        使用image_tool的缓存机制加载图像

        Args:
            image: 输入图像

        Returns:
            dict: 包含最佳匹配信息的字典
        """

        CUS_LOGGER.info(f"{factor}正在回忆相似的命运抉择...")
        best_match = {
            'similarity': 0.0,
            'position': None,
            'map_name': None
        }
        for i in range(1, 43):
            CUS_LOGGER.debug(f"  正在匹配地图{i}")
            self.set_now_map(i)
            pos, sim = self.update_position(image.copy(),[1.00],update=False)
            CUS_LOGGER.debug(f"地图{i}的相似度: {sim:.3f}")
            if sim > best_match['similarity']:
                best_match.update({
                    'similarity': sim,
                    'position': pos,
                    'map_name': i
                })
                CUS_LOGGER.debug(f"更新最佳匹配: {sim:.3f}")

        if best_match['similarity'] > 0.01:
            CUS_LOGGER.debug(f"最佳匹配地图: {best_match['map_name']} ,相似度: {best_match['similarity']:.3f} ,位置坐标: {best_match['position']}")
            self.set_now_map(best_match['map_name'])
            self.position = best_match['position']
            if show_result:
                self.draw_position_on_map()
        else:
            CUS_LOGGER.warning(f"{factor}未想起任何相似的命运抉择...（未找到匹配的大地图）")

        return best_match
    def update_minimap_data(self, image=None, rotation_minimap=None, direction_minimap=None):
        """同帧识别视角与角色方向；低可信结果以方向 None 表示。"""
        diagnostics = {}
        try:
            center = None
            if image is not None and (rotation_minimap is None or direction_minimap is None):
                center = get_minimap_center(image)
            if rotation_minimap is None:
                rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS, center=center)
            if direction_minimap is None:
                direction_minimap = get_minimap(image, radius=DIRECTION_RADIUS, center=center)
            self.direction, self.direction_similarity = update_direction(
                minimap=direction_minimap, with_confidence=True, diagnostics=diagnostics,
            )
            self.rotation_confidence = 0.0
            if self.direction is not None:
                self.rotation, self.rotation_confidence = update_rotation(
                    minimap=rotation_minimap, with_confidence=True,
                )
                if self.rotation_confidence <= 0:
                    self.direction = None
                    diagnostics["reason"] = "rotation_flat"
        except Exception:
            CUS_LOGGER.exception("无法更新当前方向，本次停止导航")
            self.direction = None
            self.direction_similarity = 0.0
            self.rotation_confidence = 0.0
        if self.direction is None and time.monotonic() - self._last_direction_warning >= 5:
            CUS_LOGGER.warning(
                "小地图方向不可靠，本次停止导航：reason=%s arrow=%.3f view=%.3f",
                diagnostics.get("reason", "direction_exception"),
                self.direction_similarity, self.rotation_confidence,
            )
            self._last_direction_warning = time.monotonic()
        return self.rotation, self.direction

if __name__ == "__main__":
    pass
    # pth = "../temp/20251019_154916.png"
    # image = cv2.imread(pth)
    # rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    # rotation, direct = update_minimap_data(image)
    # show_minimap(rotation_minimap, rotation, direct)
