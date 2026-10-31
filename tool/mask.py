"""各类识别用到的画面区域。

原先 `resource/imgs` 下的 `mask_*.jpg` 只是用来规定识别区域的宽高，图片内容从不参与匹配，
因此改为纯像素区域常量。

坐标基准是 1920×1080（运行时窗口固定为该尺寸，见 `tool/utils/game_window.py`），
格式与 `box` 一致：`[x1, y1, x2, y2]`，即 `[左, 上, 右, 下]`。
区域就是改动前实际裁剪出来的那块画面：模板匹配用的区域含四周各 30 px 余量，
OCR 用的区域是贴合识别对象的内边，所以换成常量后裁剪结果与原先完全一致。
"""

# 识别区域，键名为区域名
MASK = {
    # 祝福界面的命途图标行：识别每条祝福对应的命途
    "bless_path": (343, 706, 1561, 762),
    # 祝福界面的名称行：识别每条祝福的名字
    "bless_name": (372, 466, 1530, 508),
    # 奇物界面的名称列：识别奇物的名字
    "strange_name": (286, 252, 1634, 326),
    # 开局「请选择想要踏上的命途」界面：识别指定命途所在的卡片位置
    "fate": (6, 654, 1920, 696),
    # 交互按钮出现时，按钮内文字左侧的图标列：图标不随游戏内按键设置变化，用有无该图标判断有无交互按钮。
    # 同一目标有多个选项时按钮自下往上排列，每行间隔约 82 px，纵向须覆盖最上一行（约 y=428）
    "interact_icon": (1135, 400, 1215, 690),
    # 交互按钮上的文字行（OCR 识别交互目标），三处交互按钮位置略有差异，各留一个区域
    "interact_text": (1212, 596, 1408, 632),
    "interact_text_2": (1176, 606, 1372, 642),
    "interact_text_3": (1180, 604, 1376, 640),
    # 事件/秘闻界面对话框中下部金色 ▼ 对话标志
    "dialog": (1519, 669, 1639, 789),
    # 事件/秘闻界面对话框左侧的选项图标列（※ 星号、命途图标等）
    "event_icon": (1280, 60, 1460, 1020),
    # 关底选关界面：整体画面判断
    "end": (231, 153, 1689, 927),
    # 屏幕上方居中的怪物信息条：前方有怪物时才会出现
    "monster_info": (602, 1, 972, 101),
    # 差分宇宙里怪物信息条的旧位置，与 monster_info 相差约 25 px
    "monster_info_divergent": (627, 0, 997, 100),
}


def crop_region(screen, region):
    """按区域裁剪截图。"""
    left, top, right, bottom = region
    return screen[top:bottom, left:right, :]


def region_center_point(region):
    """区域中心的 1920x1080 像素坐标（原点在客户区左上角）。"""
    left, top, right, bottom = region
    return (left + right) / 2, (top + bottom) / 2


def quad_box(points):
    """把四点文本多边形压成 [x1, y1, x2, y2] 框。

    OCR 的 find_text 返回的是四个角点，日志里要能和区域框一样直接读，所以统一压成
    [左, 上, 右, 下]；坐标取整，避免日志里出现 np.int64(...) 这种表示。
    """
    xs = [int(point[0]) for point in points]
    ys = [int(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]
