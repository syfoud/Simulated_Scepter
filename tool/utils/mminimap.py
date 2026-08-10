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
    image_center_crop,
    image_size,
    peak_confidence,
    re_get_position,
    rgb2yuv,
    subtract_blur,
)


def update_rotation(or_image=None, minimap=None):
    """
    获取角色方向，耗时约0.66ms。

    将设置以下属性：
    - direction_similarity
    - direction
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
        rotation_confidence = round(peak_confidence(maximum), 3)

    # 将匹配点转换为角度
    degree = np.argmax(result) / (d * scale) * 360 + 135
    degree = int(degree % 360)

    return degree


def update_direction(or_image=None, minimap=None):
    """
    获取角色方向，耗时约0.64ms。

    将设置以下属性：
    - direction_similarity
    - direction
    """
    if minimap is None:
        minimap = get_minimap(or_image, DIRECTION_RADIUS)

    image = color_similarity_2d(minimap, color=DIRECTION_ARROW_COLOR)

    try:
        area = area_pad(get_bbox(image, threshold=128), pad=-1)
        area = area_limit(area, (0, 0, *image_size(image)))
    except IndexError:
        print('小地图上没有方向箭头')
        return None

    image = crop(image, area=area, copy=False)
    scale = DIRECTION_ROTATION_SCALE * DIRECTION_SEARCH_SCALE
    mapping = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    result = cv2.matchTemplate(ArrowRotateMap, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)
    _, sim, _, loca = cv2.minMaxLoc(result)
    loca = np.array(loca) / DIRECTION_SEARCH_SCALE // (DIRECTION_RADIUS * 2)

    degree = int((loca[0] + loca[1] * 8) * 5)

    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * 0.5)

    row = int(degree // 8) + 45
    row = (row - 2, row + 3)
    row = (to_map(row[0]) - 5, to_map(row[1]) + 5)
    precise_map = ArrowRotateMapAll[row[0]:row[1], :].copy()

    result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)

    _, _, _, precise_loc = cv2.minMaxLoc(result)


    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2) * 0.5)

    def get_precise_sim(d):
        y, x = divmod(d, 8)
        im = result[to_map(y):to_map(y + 1), to_map(x):to_map(x + 1)]
        _, sim, _, _ = cv2.minMaxLoc(im)
        return sim

    precise = np.array([[get_precise_sim(_) for _ in range(24)]])
    precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.1)
    precise_loca = degree // 8 * 8 - 16 + precise_loca[0]

    direction_similarity = round(precise_sim, 3)
    direction = round(precise_loca % 360, 1)
    print('direction:', direction, 'confidence:', direction_similarity)
    return direction


def show_minimap(image, rotation, direction=0):
    print('视角:', rotation, '角色朝向:', direction)
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
            search_area = (0, 0, *image_size(local))
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
        if update:
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
        print(f"绘制位置: {self.position}")
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
    def update_minimap_data(self,image=None,rotation_minimap=None, direction_minimap=None):
        if rotation_minimap is None:
            rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
        if direction_minimap is None:
            direction_minimap = get_minimap(image, radius=DIRECTION_RADIUS)
        try:
            self.direction = update_direction(minimap=direction_minimap)
        except Exception as e:
            CUS_LOGGER.error(f"{factor}无法更新当前方向: {e}")
            self.direction = None
            return self.rotation, self.direction
        if self.direction is None:
            return self.rotation, self.direction
        self.rotation = update_rotation(minimap=rotation_minimap)

        return self.rotation, self.direction


if __name__ == "__main__":
    pass
    # pth = "../temp/20251019_154916.png"
    # image = cv2.imread(pth)
    # rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    # rotation, direct = update_minimap_data(image)
    # show_minimap(rotation_minimap, rotation, direct)
