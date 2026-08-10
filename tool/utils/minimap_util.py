import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image
from scipy import signal

from tool.utils.image_tool import find_image_by_name, find_image_in_folder

MINIMAP_RADIUS = 93
# MINIMAP_CENTER = (45 + MINIMAP_RADIUS, 56 + MINIMAP_RADIUS)#(138,149)
DIRECTION_RADIUS = 17
DIRECTION_ARROW_COLOR = (255, 199, 2)
DIRECTION_ROTATION_SCALE = 1.0
DIRECTION_SEARCH_SCALE = 0.5
POSITION_SEARCH_SCALE = 0.425
POSITION_MINIMAP_SCALE= 0.27625
POSITION_RADIUS = 90
POSITION_MOVE_PATCH = (0.5, 0.5)
POSITION_FEATURE_PAD = 155
POSITION_SEARCH_RADIUS = 1.666
dict_circle_mask = {}
@dataclass
class PositionPredictState:
    size: Any = None
    scale: Any = None

    search_area: Any = None
    search_image: Any = None
    result_mask: Any = None
    result: Any = None

    sim: Any = None
    loca: Any = None
    local_sim: Any = None
    local_loca: Any = None
    precise_sim: Any = None
    precise_loca: Any = None

    global_loca: Any = None
def create_circular_mask(h, w, center=None, radius=None):
    # https://stackoverflow.com/questions/44865023/how-can-i-create-a-circular-mask-for-a-numpy-array
    if center is None:  # 使用图像的中心
        center = (int(w / 2), int(h / 2))
    if radius is None:  # 使用中心点到图像边缘的最短距离
        radius = min(center[0], center[1], w - center[0], h - center[1])

    y, x = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)

    mask = dist_from_center <= radius
    return mask
def get_circle_mask(image):
    """
    Create a circle mask with the shape of given image,
    Masks will be cached once created.
    """
    w, h = image_size(image)
    try:
        return dict_circle_mask[(w, h)]
    except KeyError:
        mask = create_circular_mask(w=w, h=h,radius=80)
        mask = (mask * 255).astype(np.uint8)
        dict_circle_mask[(w, h)] = mask
        return mask
def map_image_preprocess(image):
    """
    在ResourceGenerate和_predict_position()中使用的共享预处理方法

    Args:
        image (np.ndarray): RGB格式的屏幕截图

    Returns:
        np.ndarray:
    """
    # image = rgb2luma(image)
    image = cv2.GaussianBlur(image, (5, 5), 0)
    image = cv2.Canny(image, 15, 50)
    return image

def image_center_crop(image, size):
    """
    居中裁剪给定图像。

    Args:
        image (np.ndarray):
        size: 输出图像形状，(width, height)

    Returns:
        np.ndarray:
    """
    diff = image_size(image) - np.array(size)
    left, top = int(diff[0] / 2), int(diff[1] / 2)
    right, bottom = diff[0] - left, diff[1] - top
    image = image[top:-bottom, left:-right]
    return image
def load_image(file, area=None):
    """
    Load an image like pillow and drop alpha channel.

    Args:
        file (str):
        area (tuple):

    Returns:
        np.ndarray:
    """
    # always remember to close Image object
    with Image.open(file) as f:
        if area is not None:
            f = f.crop(area)

        image = np.array(f)

    channel = image_channel(image)
    if channel == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

    return image

class ImageNotSupported(Exception):
    """
    Raised if we can't perform image calculation on this image
    """
    pass
def cubic_find_maximum(image, precision=0.05):
    """
    使用CUBIC调整算法拟合曲面，找到最大值和位置。

    Args:
        image (np.ndarray):
        precision (int, float):

    Returns:
        float: 曲面上的最大值
        np.ndarray[float, float]: 最大值的位置
    """
    image = cv2.resize(image, None, fx=1 / precision, fy=1 / precision, interpolation=cv2.INTER_CUBIC)
    _, sim, _, loca = cv2.minMaxLoc(image)
    loca = np.array(loca, dtype=float) * precision
    return sim, loca
def subtract_blur(image, radius=3, negative=False):
    """
    If you care performance more than quality:
    - radius=3, use medianBlur
    - radius=5,7,9,11, use GaussianBlur
    - radius>11, use stackBlur (requires opencv >= 4.7.0)

    Args:
        image:
        radius:
        negative:

    Returns:
        np.ndarray:
    """
    if radius <= 3:
        blur = cv2.medianBlur(image, radius)
    elif radius <= 11:
        blur = cv2.GaussianBlur(image, (radius, radius), 0)
    else:
        blur = cv2.stackBlur(image, (radius, radius), 0)

    if negative:
        cv2.subtract(blur, image, dst=blur)
    else:
        cv2.subtract(image, blur, dst=blur)
    return blur
def image_size(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int, int: width, height
    """
    shape = image.shape
    return shape[1], shape[0]
def limit_in(x, lower, upper):
    """
    Limit x within range (lower, upper)

    Args:
        x:
        lower:
        upper:

    Returns:
        int, float:
    """
    return max(min(x, upper), lower)
def area_limit(area1, area2):
    """
    Limit an area in another area.

    Args:
        area1: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        area2: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    x_lower, y_lower, x_upper, y_upper = area2
    return (
        limit_in(area1[0], x_lower, x_upper),
        limit_in(area1[1], y_lower, y_upper),
        limit_in(area1[2], x_lower, x_upper),
        limit_in(area1[3], y_lower, y_upper),
    )
def image_channel(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int: 0 for grayscale, 3 for RGB.
    """
    return image.shape[2] if len(image.shape) == 3 else 0
def get_bbox(image, threshold=0):
    """
    获取图像中内容的边界框
    这是pillow中getbbox()函数的opencv实现

    参数:
        image (np.ndarray): 输入图像
        threshold (int):
            颜色值 > threshold 的像素将被视为内容
            颜色值 <= threshold 的像素将被视为背景

    返回:
        tuple[int, int, int, int]: 边界框坐标 (左, 上, 右, 下)

    异常:
        ImageNotSupported: 如果无法获取边界框则抛出此异常
    """
    channel = image_channel(image)
    # convert to grayscale
    if channel == 3:
        # RGB
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        # grayscale
        _, mask = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    elif channel == 4:
        # RGBA
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    else:
        raise ImageNotSupported(f'shape={image.shape}')

    # find bbox
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    # all black
    if not contours:
        raise ImageNotSupported('Cannot get bbox from a pure black image')
    for contour in contours:
        # x, y, w, h
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        if x1 < min_x:
            min_x = x1
        if y1 < min_y:
            min_y = y1
        if x2 > max_x:
            max_x = x2
        if y2 > max_y:
            max_y = y2
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    else:
        # This shouldn't happen
        raise ImageNotSupported(f'Empty bbox {(min_x, min_y, max_x, max_y)}')
def area_pad(area, pad=10):
    """
    Inner offset an area.

    Args:
        area: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        pad (int):

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    return upper_left_x + pad, upper_left_y + pad, bottom_right_x - pad, bottom_right_y - pad
def color_similarity_2d(image, color):
    """
    Args:
        image: 2D array.
        color: (r, g, b)

    Returns:
        np.ndarray: uint8
    """
    # r, g, b = cv2.split(cv2.subtract(image, (*color, 0)))
    # positive = cv2.max(cv2.max(r, g), b)
    # r, g, b = cv2.split(cv2.subtract((*color, 0), image))
    # negative = cv2.max(cv2.max(r, g), b)
    # return cv2.subtract(255, cv2.add(positive, negative))
    diff = cv2.subtract(image, (*color, 0))
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract((*color, 0), image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    cv2.subtract(255, positive, dst=positive)
    return positive
def RotationRemapData():
    d = MINIMAP_RADIUS * 2
    half_d = d / 2.0

    # Precompute cos/sin for each angle (d values, outside the hot loop).
    # Each call result is stored immediately — never embedded in arithmetic.
    _cos = math.cos
    _sin = math.sin
    _pi = math.pi
    cos_vals = np.empty(d, dtype=np.float32)
    sin_vals = np.empty(d, dtype=np.float32)
    for j in range(d):
        angle = (2.0 * _pi * j) / d
        cos_vals[j] = _cos(angle)
        sin_vals[j] = _sin(angle)

    # Build remap tables: only float arithmetic, no function calls inside the loop.
    mx = np.empty((d, d), dtype=np.float32)
    my = np.empty((d, d), dtype=np.float32)
    for i in range(d):
        radius = i / 2.0
        mx[i, :] = half_d + radius * cos_vals
        my[i, :] = half_d + radius * sin_vals
    return mx, my
def copy_image(src):
    """
    Equivalent to image.copy() but a little bit faster

    Time cost to copy a 1280*720*3 image:
        image.copy()      0.743ms
        copy_image(image) 0.639ms
    """
    dst = np.empty_like(src)
    cv2.copyTo(src, None, dst)
    return dst
def crop(image, area, copy=True):
    """
    Crop image like pillow, when using opencv / numpy.
    Provides a black background if cropping outside of image.

    Args:
        image (np.ndarray):
        area:
        copy (bool):

    Returns:
        np.ndarray:
    """
    # map(round, area)
    x1, y1, x2, y2 = area
    x1 = round(x1)
    y1 = round(y1)
    x2 = round(x2)
    y2 = round(y2)
    # h, w = image.shape[:2]
    shape = image.shape
    h = shape[0]
    w = shape[1]
    # top, bottom, left, right
    # border = np.maximum((0 - y1, y2 - h, 0 - x1, x2 - w), 0)
    overflow = False
    if y1 >= 0:
        top = 0
        if y1 >= h:
            overflow = True
    else:
        top = -y1
    if y2 > h:
        bottom = y2 - h
    else:
        bottom = 0
        if y2 <= 0:
            overflow = True
    if x1 >= 0:
        left = 0
        if x1 >= w:
            overflow = True
    else:
        left = -x1
    if x2 > w:
        right = x2 - w
    else:
        right = 0
        if x2 <= 0:
            overflow = True
    # If overflowed, return empty image
    if overflow:
        if len(shape) == 2:
            size = (y2 - y1, x2 - x1)
        else:
            size = (y2 - y1, x2 - x1, shape[2])
        return np.zeros(size, dtype=image.dtype)
    # x1, y1, x2, y2 = np.maximum((x1, y1, x2, y2), 0)
    if x1 < 0:
        x1 = 0
    if y1 < 0:
        y1 = 0
    if x2 < 0:
        x2 = 0
    if y2 < 0:
        y2 = 0
    # crop image
    image = image[y1:y2, x1:x2]
    # if border
    if top or bottom or left or right:
        if len(shape) == 2:
            value = 0
        else:
            value = tuple(0 for _ in range(image.shape[2]))
        return cv2.copyMakeBorder(image, top, bottom, left, right, borderType=cv2.BORDER_CONSTANT, value=value)
    elif copy:
        return copy_image(image)
    else:
        return image
def area_offset(area, offset):
    """
    Move an area.

    Args:
        area: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        offset: (x, y).

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    x, y = offset
    return upper_left_x + x, upper_left_y + y, bottom_right_x + x, bottom_right_y + y


def rotate_minimap(minimap, angle):
    """
    以(93,93)为中心旋转小地图

    Args:
        minimap: 小地图图像数组
        angle: 旋转角度（度），正数为顺时针

    Returns:
        旋转后的小地图图像
    """
    height, width = minimap.shape[:2]
    center = (MINIMAP_RADIUS, MINIMAP_RADIUS)
    # 计算旋转矩阵
    rotation_matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)  # 负号是因为OpenCV中正角度是逆时针
    rotated_minimap = cv2.warpAffine(minimap, rotation_matrix, (width, height),
                                     flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                     borderValue=(0, 0, 0))  # 使用黑色填充边界

    return rotated_minimap


def mask_minimap_center(minimap, center_radius=80):
    """
    保留小地图圆心区域，其余部分用黑色遮蔽

    Args:
        minimap: 小地图图像数组
        center_radius: 圆心区域的半径，默认为40

    Returns:
        处理后的小地图图像，仅保留中心圆形区域
    """
    height, width = minimap.shape[:2]
    center = (93, 93)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, center_radius, (255), -1)
    masked_minimap = cv2.bitwise_and(minimap, minimap, mask=mask)

    return masked_minimap


def mask_minimap_outside(minimap, center_radius=40, outer_radius=None):
    """
    保留小地图圆环区域（环形区域），圆心和外围部分用黑色遮蔽

    Args:
        minimap: 小地图图像数组
        center_radius: 圆心区域的半径，默认为 40
        outer_radius: 外圆半径，默认为 None（使用图像最大半径减 5）

    Returns:
        处理后的小地图图像，仅保留圆环区域
    """
    # 获取图像尺寸
    height, width = minimap.shape[:2]
    center = (93, 93)
    max_radius = min(width, height) // 2
    if outer_radius is None:
        outer_radius = max_radius - 5
    else:
        outer_radius = min(outer_radius, max_radius)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, outer_radius, (255), -1)
    cv2.circle(mask, center, min(center_radius, outer_radius - 5), (0), -1)
    masked_minimap = cv2.bitwise_and(minimap, minimap, mask=mask)

    return masked_minimap
def detect_minimap_center(image):
    """
    通过白色圆形边缘模板匹配检测小地图中心
    """
    # 创建白色圆形边缘模板
    template = np.zeros((2 * MINIMAP_RADIUS, 2 * MINIMAP_RADIUS), dtype=np.uint8)
    cv2.circle(template, (MINIMAP_RADIUS, MINIMAP_RADIUS), MINIMAP_RADIUS, 255, 3)
    gray_template = template

    result = cv2.matchTemplate(image, gray_template, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)
    # 计算实际中心坐标
    center_x = max_loc[0] + MINIMAP_RADIUS
    center_y = max_loc[1] + MINIMAP_RADIUS
    return (center_x, center_y)
def get_minimap(image, radius, copy=False, rotation=False, center_radius=80):
    """
    裁剪图像中的小地图区域

    Args:
        image (np.ndarray): 输入图像
        radius (int): 裁剪半径
        copy (bool): 是否复制图像
        rotation (bool): 是否进行旋转校正
        center_radius (int): 中心掩膜半径

    Returns:
        np.ndarray: 处理后的小地图图像
    """
    # 通过模板匹配获取准确的MINIMAP_CENTER（很奇怪，小地图相对坐标会变化）
    area = [0,0,245,255]
    MINIMAP_CENTER = detect_minimap_center(map_image_preprocess(crop(image, area, copy=copy)))
    area = area_offset((-radius, -radius, radius, radius), offset=MINIMAP_CENTER)
    image = crop(image, area, copy=copy)
    if rotation:
        from tool.utils.mminimap import update_rotation
        # 获取输入图片的视角角度
        input_rotation = update_rotation(minimap=image)
        # 读取0度视角纹理图
        zero_texture = find_image_by_name("only_rotated.png")

        # 根据输入图片的视角旋转0度视角纹理图
        rotated_texture = rotate_minimap(zero_texture, input_rotation)
        # 从纹理中心裁剪以匹配目标图像尺寸
        if rotated_texture.shape != image.shape:
            tex_h, tex_w = rotated_texture.shape[:2]
            target_h, target_w = image.shape[:2]
            center_y, center_x = tex_h // 2, tex_w // 2
            half_target_h, half_target_w = target_h // 2, target_w // 2

            # 计算裁剪边界
            y1 = max(0, center_y - half_target_h)
            y2 = min(tex_h, center_y + half_target_h + (target_h % 2))
            x1 = max(0, center_x - half_target_w)
            x2 = min(tex_w, center_x + half_target_w + (target_w % 2))

            rotated_texture = rotated_texture[y1:y2, x1:x2]
        image = cv2.subtract(image, rotated_texture)

        # 掩膜掩盖非中心区域避免遇敌红色圈干扰敌人追踪
        image = mask_minimap_center(image, center_radius=center_radius)
    return image
def convolve(arr, kernel=3):
    """
    Args:
        arr (np.ndarray): 形状 (N,)
        kernel (int):

    Returns:
        np.ndarray:
    """
    return sum(np.roll(arr, i) * (kernel - abs(i)) // kernel for i in range(-kernel + 1, kernel))
def peak_confidence(arr, **kwargs):
    """
    评估最高峰值的显著性

    Args:
        arr (np.ndarray): 形状 (N,)
        **kwargs: signal.find_peaks的额外参数

    Returns:
        float: 0-1
    """
    para = {
        'height': 0,
        'prominence': 10,
    }
    para.update(kwargs)
    length = len(arr)
    peaks, properties = signal.find_peaks(np.concatenate((arr, arr, arr)), **para)
    peaks = [h for p, h in zip(peaks, properties['peak_heights']) if length <= p < length * 2]
    peaks = sorted(peaks, reverse=True)

    count = len(peaks)
    if count > 1:
        highest, second = peaks[0], peaks[1]
    elif count == 1:
        highest, second = 1, 0
    else:
        highest, second = 1, 0
    confidence = (highest - second) / highest
    return confidence
def rgb2yuv(image):
    """
    Convert RGB to YUV color space.

    Args:
        image (np.ndarray): Shape (height, width, channel)

    Returns:
        np.ndarray: Shape (height, width)
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    return image
def group_points(points, threshold=3):
    """
    对点集进行分组，依据点之间的曼哈顿距离是否小于阈值 threshold。

    参数:
        points (np.ndarray): 形状为 (N, 2) 的点集，例如 [[x1, y1], [x2, y2], ...]
        threshold (int): 分组的距离阈值

    返回:
        np.ndarray: 每组点的平均坐标，形状为 (M, 2)
    """
    if points is None or len(points) == 0:
        return np.array([])

    groups = []
    points = np.array(points)  # 确保输入为 NumPy 数组
    if len(points) == 1:
        return np.array([points[0]])

    while len(points):
        p0, p1 = points[0], points[1:]
        # 计算当前点与其他点的曼哈顿距离
        distance = np.sum(np.abs(p1 - p0), axis=1)
        # 找出距离小于阈值的点，组成新组
        new_group = np.append(p1[distance <= threshold], [p0], axis=0)
        # 计算该组的平均坐标并加入结果列表
        groups.append(np.round(np.mean(new_group, axis=0)).astype(int))
        # 移除已处理的点
        points = p1[distance > threshold]

    return np.array(groups)
def inrange(image, lower=0, upper=255):
    """
    获取范围内像素的坐标。
    等效于 `np.array(np.where(lower <= image <= upper))` 但更快。
    注意此方法会改变 `image`。

    `cv2.findNonZero()` 比 `np.where` 更快
    points = np.array(np.where(y > 24)).T[:, ::-1]
    points = np.array(cv2.findNonZero((y > 24).astype(np.uint8)))[:, 0, :]

    `cv2.inRange(y, 24)` 比 `y > 24` 更快
    cv2.inRange(y, 24, 255, dst=y)
    y = y > 24

    返回:
        np.ndarray: 形状 (N, 2)
            例如 [[x1, y1], [x2, y2], ...]
    """
    cv2.inRange(image, lower, upper, dst=image)
    try:
        return np.array(cv2.findNonZero(image))[:, 0, :]
    except IndexError:
        # Empty result
        # IndexError: too many indices for array: array is 0-dimensional, but 3 were indexed
        return np.array([])
def remove_border(image, radius):
    """
    将边缘像素涂黑。
    无返回值，更改写入到 `image`

    参数:
        image:
        radius:
    """
    width, height = image_size(image)
    image[:, :radius + 1] = 0
    image[:, width - radius:] = 0
    image[:radius + 1, :] = 0

    image[height - radius:, :] = 0
def deal_minimap(image,is_minimap=False):
    if not is_minimap:
        image = get_minimap(image, radius=POSITION_RADIUS,copy= True)
    image = map_image_preprocess(image)
    image &= get_circle_mask(image)
    return image
def re_get_position(position,need_int=True,re=False):
    """
    把计算用放缩坐标转换为游戏图像坐标
    re为true则把游戏图像坐标转换为计算用放缩坐标
    参数:
        position: (x, y)
        need_int: 是否将结果转换为整数
        re: 是否反转
    返回:
        (x, y)
    """
    if re:
        map_position = np.array(position, dtype=np.float64)
        map_position /= POSITION_SEARCH_SCALE
        map_position -= POSITION_FEATURE_PAD
    else:
        map_position = np.array(position, dtype=np.float64)
        # 添加特征填充偏移
        map_position += POSITION_FEATURE_PAD
        # 应用搜索比例缩放
        map_position *= POSITION_SEARCH_SCALE
        if need_int:
            map_position = np.round(map_position).astype(int)
    return map_position
def draw_circle(image, circle, points):
    """
    在图像上添加一个圆。
    无返回值，更改写入到 `image`

    参数:
        image:
        circle: 由 create_circle() 创建
        points: (x, y)，要绘制的圆的中心
    """
    width, height = image_size(circle)
    x1 = -int(width // 2)
    y1 = -int(height // 2)
    x2 = width + x1
    y2 = height + y1
    for point in points:
        x, y = point
        # Fancy index is faster
        index = image[y + y1:y + y2, x + x1:x + x2]
        # print(index.shape)
        cv2.add(index, circle, dst=index)
def create_circle(min_radius, max_radius):
    """
    创建一个 min_radius <= R <= max_radius 的圆。
    1 表示圆形，0 表示背景

    参数:
        min_radius:
        max_radius:

    返回:
        np.ndarray:
    """
    circle = np.ones((max_radius * 2 + 1, max_radius * 2 + 1), dtype=np.uint8)
    center = np.array((max_radius, max_radius))
    points = np.array(np.meshgrid(np.arange(circle.shape[0]), np.arange(circle.shape[1]))).T
    distance = np.linalg.norm(points - center, axis=2)
    circle[distance < min_radius] = 0
    circle[distance > max_radius] = 0
    return circle
ArrowRotateMap=find_image_in_folder('gray_image/', "ArrowRotateMap.png")
ArrowRotateMapAll=find_image_in_folder('gray_image/', "ArrowRotateMapAll.png")
