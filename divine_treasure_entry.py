"""差分宇宙入场、单轮开局和图鉴采集入口。

入场部分不再自建状态机：界面识别与动作写在 `tool/divine_treasure/actions/divine_treasure.json`，
由 `core/common/runtime.py::ScriptKernel` 的 `match_actions` 驱动；本文件只提供两条
需要程序逻辑的动作（配队、协议校验）。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from core.common.runtime import ScriptKernel
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tool" / "divine_treasure"))  # 面具/图鉴模块已归入子包；worker 子进程的 sys.path[0] 只有仓库根
STATES = ("home", "mode", "regular", "ranked", "practice", "masks")

# 队伍槽位（「常规演算」页底部）：第一个槽位为空就说明还没配队。
# 首次使用前需要在游戏里组好队 → 保存为「预设编队」→ 收藏置顶，脚本会点第一个预设。
TEAM_SLOT_POINT = (1149, 967)     # 空槽位，点它弹出「下载角色」面板
TEAM_PRESET_TAB = (425, 132)      # 面板顶部「预设编队」标签
TEAM_PRESET_FIRST = (299, 279)    # 预设列表第一个（即收藏置顶那支）
TEAM_EMPTY_SLOT_BOX = (1112, 1186, 931, 1004)  # 空槽位图标的搜索区 [x1, x2, y1, y2]
TEAM_EMPTY_TEMPLATE = str(ROOT / "tool" / "divine_treasure" / "assets" / "team_empty_slot.png")  # 必须是绝对路径：
# find_image_by_name 对带 "/" 的相对路径会拼到 resource/imgs 下，导致永远读不到
PROTOCOL_BOX = (672, 1246, 879, 953)  # 练习模式页底部「阈值协议 ▼ N」整条（备用区域）
PROTOCOL_DIGIT_BOX = (1002, 887, 1019, 913)  # 协议数字本身，[x1, y1, x2, y2]，实机采集
PROTOCOL_MINUS = (731, 902)           # 阈值协议左侧「−」
PROTOCOL_PLUS = (1142, 902)           # 阈值协议右侧「+」
PROTOCOL_RANGE = (1, 9)               # 协议可选范围，越界时钳制
DEFAULT_PROTOCOL = 4                  # 默认目标协议，可用 --protocol 覆盖
# 默认取 4 而不是 5：协议效果逐级叠加，N5 相对 N4 只多「第一位面 1 次惊世奇迹」，代价是
# 面具愿力需求与方程祝福需求提高；而刷图鉴时战斗时间占比很低，N5 更肉的敌人几乎无感，
# 对刷事件真正有用的是区域数量（N4 起已给足）。评估见 canon/divine-treasure/_02-乐园漫记玩法.md
ACTION_SCRIPT = ROOT / "tool" / "divine_treasure" / "actions" / "divine_treasure.json"

# ── 3D 区域（战斗 / 寻路）────────────────────────────────────────────────
# 不认怪物外观（千奇百怪），只认两个信号：
#   1. 顶部出现「等级XX xxx团」信息条 = 视野内有怪（等级与名字都会变，只用结构判据）
#   2. 红圈准星 = 已锁定怪物
# 小旗子 = 已进入战斗界面，这是判断「打没打起来」最可靠的信号。
ASSET_DIR = ROOT / "tool" / "divine_treasure" / "assets"
BATTLE_FLAG = str(ASSET_DIR / "battle_flag.png")
LOCK_RING = str(ASSET_DIR / "lock_ring.png")
MONSTER_INFO_BOX = (500, 0, 1400, 100)   # 顶部怪物信息区 [x1, y1, x2, y2]
BATTLE_FLAG_POINT = (75, 25)             # 小旗子中心（战斗界面左上角）
AREA_LABEL_BOX = (0, 10, 400, 60)        # 左上角「(N/20) 第X位面-类型」[x1, y1, x2, y2]
# 自动战斗按钮（战斗界面右上角）。开/关图标形状相同、只差颜色：开启是黄色
# （色相~18、饱和~138），未开启是蓝灰（色相~117、饱和~44）。模板匹配反而分不开，
# 所以用 HSV 判色。
AUTO_BATTLE_BOX = (1744, 38, 1780, 56)   # [x1, y1, x2, y2]
AUTO_BATTLE_POINT = (1762, 47)
# 选择祝福：推荐图标是绿色圆形，卡片数量 1/2/3 时排列都不同，所以不猜坐标，
# 直接按颜色找图标（实测三卡时命中 x=649/1126/1603，与实机采集一致）。
BLESS_ICON_ROI = (200, 380)      # 只扫这个纵向区间，避开顶部 UI 和底部按钮
BLESS_CARD_Y = 450               # 点在图标正下方的卡片内
BLESS_TITLE_BOX = (90, 55, 220, 105)  # 左上角「选择祝福」标题 [x1, y1, x2, y2]
TURN_PIXELS = 300        # 每转一次视角的鼠标位移；太小找不到怪，太大容易漏
WALK_SECONDS = 1.5       # 每次前进时长（实机调过：0.35 太短走不到怪）


# ── 对局面板（左上角，可展开/收起）──────────────────────────────────────
# 展开后才看得到面具等级与进度。识别方式是「读 Lv N/20」而不是给 14 张面具各写一套
# 愿力算法——等级和进度条是游戏自己算好的，直接读出来就行。
PANEL_TOGGLE = (417, 81)                  # 展开/收起箭头
PANEL_LEVEL_BOX = (125, 148, 220, 188)    # 「Lv N/20」文字区 [x1, y1, x2, y2]
PANEL_PROGRESS_BOX = (134, 182, 435, 194)  # 经验条 [x1, y1, x2, y2]
PANEL_BAR_BRIGHT = 50                     # 经验条填充判定阈值（实测亮 86 / 暗 2）
# 进度条满的判定：条上的 +N 是「通过本区域后结算」的值，条画满就表示结算后升级；
# 留 5% 容差是因为填充边界有 1~2 像素误差，实测满条读到 0.99
PANEL_BAR_FULL = 0.95

# ── 选择方程（随时可能出现的通用决策界面）────────────────────────────────
# 不排优先级：队伍配置因人而异，选中间那个最省事
EQUATION_MIDDLE = (960, 500)    # 中间方程的卡片中心
EQUATION_CONFIRM = (1710, 972)  # 右下角「确认」

# ── 面具选择（「欢愉假面」页）──────────────────────────────────────────────
# 优先级来自 214 题人工评分：本体分 + 专属奇迹均值×0.6 的综合排序，
# 依据见 canon/divine-treasure/_10-面具选择判据.md
MASK_PRIORITY = (
    "机铠面具", "万随面具", "雪鸮面具", "点子王面具", "镜头面具",
    "「两张」面具", "马之面具", "财猫面具", "操盘面具", "囧之面具",
    "贪吃面具", "斗士面具", "战车面具", "敷衍面具",
)
MASK_POINTS = ((331, 431), (332, 615), (338, 803))  # 三张面具卡片中心，按从上到下
# 排名小于这个值才值得直接选：前 6 名本体分都 ≥ +1，后面的是中性或有负面。
# 三张都达不到就用刷新额度重刷，刷完仍不达标才勉强选最好的那张。
GOOD_MASK_RANK = 6
MASK_REFRESH = (161, 949)   # 「刷新 N/1」
MASK_CONFIRM = (1586, 959)  # 「确定」
MASK_DETAIL_BOX = (1020, 180, 1350, 250)  # 右侧详情面板标题区 [x1, y1, x2, y2]，大字识别更稳
# 三张卡片上名字条的文字框 [x1, y1, x2, y2]，实机采集（按五个字宽度取）
MASK_NAME_BOXES = ((374, 400, 552, 432), (378, 586, 550, 617), (378, 771, 552, 805))
# OCR 常见误读，统一成正名后再比对优先级
MASK_ALIASES = {"雪鹄": "雪鸮", "雪鸡": "雪鸮", "雪号": "雪鸮", "机凯": "机铠",
                "财喵": "财猫", "冏": "囧"}
_TEAM_EMPTY_TEMPLATE = None


def read_rows(image, ocr):
    rows = []
    for box, (text, confidence) in ocr.ocr(image):
        if confidence >= 0.7:
            center = np.mean(box, axis=0)
            rows.append((re.sub(r"\s+", "", text), int(center[0]), int(center[1])))
    return rows


def click_game(hwnd, rect, target):
    import pyautogui
    import win32api
    import win32con
    import win32gui

    from tool.utils.game_window import get_client_screen_rect

    if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
        raise InterruptedError("F8 pressed")
    if win32gui.GetForegroundWindow() != hwnd or get_client_screen_rect(hwnd) != rect:
        raise RuntimeError("Game focus or geometry changed during recognition")
    x, y = target
    pyautogui.click(rect[0] + round(x * (rect[2] - rect[0]) / 1920),
                    rect[1] + round(y * (rect[3] - rect[1]) / 1080))


def team_empty_template():
    """空槽位图标模板，懒加载。

    首次使用时需要在游戏里：组一支队 → 保存为「预设编队」→ 给它点收藏置顶，
    否则脚本会把空槽位当成「队伍没配」而去点预设列表的第一个，可能点到意料外的队伍。
    """
    global _TEAM_EMPTY_TEMPLATE
    if _TEAM_EMPTY_TEMPLATE is None:
        path = ROOT / "tool" / "divine_treasure" / "assets" / "team_empty_slot.png"
        # 中文路径用 imdecode，cv2.imread 在 Windows 上会读失败
        _TEAM_EMPTY_TEMPLATE = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    return _TEAM_EMPTY_TEMPLATE


def match_in_box(image, template, box, threshold=0.8):
    """在 box=[x1, x2, y1, y2] 区域内匹配模板。

    Returns:
        命中返回 (score, (x, y))（坐标为区域内的中心点，1920×1080 基准），否则 None。
    """
    x1, x2, y1, y2 = box
    if template is None:
        return None
    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    height, width = template.shape[:2]
    return max_val, (x1 + max_loc[0] + width // 2, y1 + max_loc[1] + height // 2)


def inspect_screen(image, ocr):
    """离线识别（--samples 用）。在线流程由 JSON 触发器完成同样的判断。"""
    image = cv2.resize(image, (1920, 1080))
    rows = read_rows(image, ocr)

    def find(text, rect):
        x0, y0, x1, y1 = rect
        return next(((x, y) for value, x, y in rows
                     if text in value and x0 <= x <= x1 and y0 <= y <= y1), None)

    header = (0, 0, 400, 160)
    bottom = (650, 930, 1900, 1040)
    state, target, protocol, team_empty = "unknown", None, None, False
    if find("欢愉假面", header) and sum(
        "面具" in value and 200 < y < 850 for value, _, y in rows
    ) >= 2:
        state = "masks"
    elif find("差分宇宙", header) and find("开始游戏", bottom):
        state, target = "home", find("开始游戏", bottom)
    elif find("模式选择", header) and find("常规演算", (0, 200, 750, 480)):
        state, target = "mode", find("常规演算", (0, 200, 750, 480))
    elif find("常规演算", header) and find("进入星阶模式", bottom):
        state, target = "regular", find("进入星阶模式", bottom)
        team_empty = match_in_box(image, team_empty_template(), TEAM_EMPTY_SLOT_BOX) is not None
    elif find("星阶模式", header) and find("启动", bottom):
        target = find("练习模式", (960, 100, 1260, 180))
        # 样本4/5：练习页右侧标签为白底，且中央显示不影响星阶。
        selected = float(image[128:151, 990:1020].mean()) > 200
        if target and selected and find("不影响星阶", (650, 580, 1280, 720)):
            state, target = "practice", find("启动", bottom)
            digit_crop = image[873:930, 984:1040]
            digits = [re.sub(r"\s+", "", text) for _, (text, score) in ocr.ocr(digit_crop)
                      if score >= 0.7]
            if len(digits) == 1 and digits[0].isdigit():
                protocol = int(digits[0])
        elif target and not selected:
            state = "ranked"
    return {"state": state, "target": target, "protocol": protocol,
            "team_empty": team_empty, "rows": rows}


def save_evidence(output, name, image, result):
    output.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(output / f"{name}.png")
    (output / f"{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def capture_game():
    import win32api
    import win32con
    import win32gui
    from PIL import ImageGrab

    from tool.utils.game_window import get_client_screen_rect, is_usable_game_window

    if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
        raise InterruptedError("F8 pressed")
    hwnd = win32gui.GetForegroundWindow()
    if not is_usable_game_window(hwnd):
        raise RuntimeError("Game must remain in the foreground; stopped without clicking")
    rect = get_client_screen_rect(hwnd)
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    if abs(width / height - 16 / 9) > 0.015:
        raise RuntimeError(f"Expected a 16:9 game client, got {width}x{height}")
    image = cv2.cvtColor(np.asarray(ImageGrab.grab(bbox=rect, all_screens=True)), cv2.COLOR_RGB2BGR)
    return image, hwnd, rect


class DivineTreasureKernel(ScriptKernel):
    """入场内核：界面识别与动作由 `actions/divine_treasure.json` 驱动。

    只补两条需要程序逻辑的动作；其余「识别到某界面就点某个按钮」全部写在 JSON 里。
    """

    window_timeout = 5        # 测试用短等待；正式运行可调回 300
    require_foreground = True  # 游戏窗口切走就停
    foreground_grace = 30      # 失焦容忍帧数，约十几秒，给用户切回窗口的时间
    action_groups = None       # None = 跑 JSON 里全部组
    target_protocol = DEFAULT_PROTOCOL  # 目标阈值协议，由 --protocol 覆盖
    _foreground_misses = 0
    _miss_count = 0

    def run_static(self, json_path=None, json_file=None, action_list=None, skip_check=False):
        # 按 --stage 指定的组运行，便于只验证当次改动的那一段
        name, result = self.match_actions(json_path, json_file, action_list or self.action_groups, skip_check)
        if not name:
            # 连续认不出界面时把当前 OCR 到的文字和位置打出来，方便判断卡在哪一页
            self._miss_count += 1
            if self._miss_count % 10 == 1:
                items = [(item["raw_text"], [int(v) for v in item["box"]]) for item in self.ts.res]
                CUS_LOGGER.debug(f"未匹配到任何规则，共 {len(items)} 条：{items}", extra={"flush": True})
        else:
            self._miss_count = 0
        return name, result

    def get_screen(self):
        import win32api
        import win32con

        from tool.utils.game_window import (
            get_foreground_game_window,
            set_game_foreground,
        )

        if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
            CUS_LOGGER.error("F8 pressed, stopping")
            self.stop()
        elif self.require_foreground:
            # 从终端启动时前台是终端，游戏被抢焦点；这里给十几帧宽限并主动拉回，
            # 不要一失焦就停（用户敲完命令再切回游戏需要时间）
            if get_foreground_game_window() is None:
                self._foreground_misses += 1
                if self._foreground_misses > self.foreground_grace:
                    CUS_LOGGER.error("游戏窗口长时间不在前台，停止")
                    self.stop()
                elif self._foreground_misses % 10 == 1:
                    set_game_foreground()
            else:
                self._foreground_misses = 0
        return super().get_screen()

    def fill_team(self):
        """队伍为空时套用预设编队：空槽位 → 预设编队标签 → 预设列表第一个。"""
        if not self.check(TEAM_EMPTY_TEMPLATE, mask=TEAM_EMPTY_SLOT_BOX):
            return
        CUS_LOGGER.debug("队伍为空：空槽位 → 预设编队 → 第一个预设", extra={"flush": True})
        for point, wait in ((TEAM_SLOT_POINT, 1.2), (TEAM_PRESET_TAB, 0.8), (TEAM_PRESET_FIRST, 1.0)):
            self.click_position(point)
            key_mouse_manager.wait()
            time.sleep(wait)
        # 面板不会自动关闭，但也不遮挡「进入星阶模式」，后续动作照常点击

    def normalize_mask_name(self, name):
        """把 OCR 常见的形近字统一成正名，便于和优先级列表比对。"""
        for alias, real in MASK_ALIASES.items():
            if alias in name:
                name = name.replace(alias, real)
        return name

    def read_mask_detail(self):
        """读右侧详情面板的面具名。

        卡片名字条上的小字 OCR 不稳（「囧」会被认成「周/同」），详情面板的标题是大字，
        识别明显更可靠，所以按「点开卡片 → 读详情」来认面具。
        """
        x1, y1, x2, y2 = MASK_DETAIL_BOX
        crop = self.get_screen()[y1:y2, x1:x2]
        if crop.size == 0:
            return ""
        text = self.ts.ocr_one_row(crop) or ""
        return self.normalize_mask_name("".join(ch for ch in text if not ch.isspace()))

    def mask_rank(self, name):
        """返回面具在优先级里的排名，越小越好；不在列表返回 len(MASK_PRIORITY)。"""
        for rank, want in enumerate(MASK_PRIORITY):
            if want in name:
                return rank
        return len(MASK_PRIORITY)

    def read_mask_names(self):
        """一次裁三条名字条、放大 3 倍后识别，返回 [(归一化名字, 卡片序号)]。

        比逐张点开快得多（点开会把卡片选中、白条位置跟着变）；但选中态那张卡的框会
        失效，所以调用方要对缺失项降级处理。
        """
        screen = self.get_screen()
        names = []
        for index, (x1, y1, x2, y2) in enumerate(MASK_NAME_BOXES):
            crop = screen[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            text = self.ts.ocr_one_row(crop) or ""
            text = self.normalize_mask_name("".join(ch for ch in text if not ch.isspace()))
            if "面具" in text and len(text) >= 3:
                names.append((text, index))
        return names

    def read_masks(self):
        """批量识别三张面具名，缺失的再逐张点开补，返回 {卡片序号: 名字}。"""
        found = dict((index, text) for text, index in self.read_mask_names())
        CUS_LOGGER.debug(f"批量识别：{found}", extra={"flush": True})
        for index in range(len(MASK_POINTS)):
            if index in found:
                continue
            self.click_position(MASK_POINTS[index])
            key_mouse_manager.wait()
            time.sleep(0.45)
            name = self.read_mask_detail()
            if "面具" in name:
                found[index] = name
                CUS_LOGGER.debug(f"第 {index + 1} 张补读：{name}", extra={"flush": True})
        return found

    def try_refresh(self, before):
        """点一次刷新，返回新的 {序号: 名字}；没刷出变化（多半没额度）返回 None。

        不读「刷新 N/1」的数字：那个小字 OCR 不稳（实测读成「价」），直接点完比对
        三张面具名是否变了更可靠。
        """
        self.click_position(MASK_REFRESH)
        key_mouse_manager.wait()
        time.sleep(1.2)
        fresh = dict((index, text) for text, index in self.read_mask_names())
        if not fresh:
            return None
        if set(fresh.values()) == set(before.values()):
            return None
        CUS_LOGGER.debug(f"刷新后：{fresh}", extra={"flush": True})
        return fresh

    def select_mask(self):
        """先按优先级挑；三张都不够好就刷一次再挑，实在不行才勉强选最好的。

        批量识别在正常情况下不点击（2 次点击：选 + 确定）；只有被选中导致的框失效、
        或识别不清时才降级点开读详情。
        """
        found = self.read_masks()
        if found:
            best = min(found.items(), key=lambda item: (self.mask_rank(item[1]), item[0]))
            if self.mask_rank(best[1]) >= GOOD_MASK_RANK:
                CUS_LOGGER.debug(f"三张都不理想（最好的是 {best[1]}，排名 {self.mask_rank(best[1]) + 1}），"
                                 f"尝试刷新", extra={"flush": True})
                fresh = self.try_refresh(found)
                if fresh:
                    found = fresh
                else:
                    CUS_LOGGER.debug("刷新没有变化（可能额度已用完），沿用当前三张", extra={"flush": True})
        if not found:
            CUS_LOGGER.warning("三张面具都没识别出来，直接点确定", extra={"flush": True})
            self.click_position(MASK_CONFIRM)
            key_mouse_manager.wait()
            return
        best = min(found.items(), key=lambda item: (self.mask_rank(item[1]), item[0]))
        rank = self.mask_rank(best[1])
        if rank >= len(MASK_PRIORITY):
            CUS_LOGGER.warning(f"识别到的面具都不在优先级列表，选第 {best[0] + 1} 张：{best[1]}",
                               extra={"flush": True})
        else:
            CUS_LOGGER.debug(f"按优先级选：{best[1]}（第 {best[0] + 1} 张，排名 {rank + 1}）",
                             extra={"flush": True})
        self.click_position(MASK_POINTS[best[0]])
        key_mouse_manager.wait()
        time.sleep(0.45)
        self.click_position(MASK_CONFIRM)
        key_mouse_manager.wait()
        time.sleep(0.8)

    # ── 3D 区域：找怪与进入战斗 ──────────────────────────────────────────
    def has_bless_screen(self):
        """界面上是否还有「选择祝福」标题。"""
        x1, y1, x2, y2 = BLESS_TITLE_BOX
        crop = self.get_screen()[y1:y2, x1:x2]
        if crop.size == 0:
            return False
        return "选择祝福" in (self.ts.ocr_one_row(crop) or "")

    def find_recommend_icons(self):
        """找祝福界面上的推荐图标（绿色圆形），返回按 x 排序的中心点列表。

        不按「三张卡各占多少宽度」去算——1 / 2 / 3 张卡时排列完全不同，而图标的
        颜色和形状始终不变，按颜色找最省事。
        """
        y1, y2 = BLESS_ICON_ROI
        roi = self.get_screen()[y1:y2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (40, 100, 100), (85, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers = []
        for contour in contours:
            if cv2.contourArea(contour) > 150:
                moment = cv2.moments(contour)
                if moment["m00"]:
                    centers.append((int(moment["m10"] / moment["m00"]),
                                    int(moment["m01"] / moment["m00"]) + y1))
        return sorted(centers)

    def find_bless_cards(self):
        """用轮廓找祝福卡片本体，返回按 x 排序的中心点。

        卡片名 OCR 会漏检（读成「自由」而不是「自由蛹」，后面的卡干脆读不到），
        所以没有推荐图标时改找卡片矩形。
        """
        gray = cv2.cvtColor(self.get_screen(), cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # 卡片尺寸；y>200 排除顶部 UI，y<520 只留卡片主体（内部元素会重复命中）
            if w > 300 and h > 250 and 200 < y < 520:
                raw.append((x + w // 2, y + h // 2))
        # 同一张卡会被拆成多个矩形，按 x 间距聚类去重
        cards = []
        for cx, cy in sorted(raw):
            if not cards or cx - cards[-1][0] > 100:
                cards.append((cx, cy))
        return cards

    def choose_bless(self):
        """选祝福：优先带推荐图标的（取最左一个），否则选最左边的卡片。

        不能「没有推荐就点屏幕正中」——两张卡时正中间是空隙，会点空。
        """
        icons = self.find_recommend_icons()
        if icons:
            x = icons[0][0]
            CUS_LOGGER.debug(f"推荐祝福 @ x={x}（共 {len(icons)} 个推荐）", extra={"flush": True})
            self.click_position((x, BLESS_CARD_Y))
        else:
            cards = self.find_bless_cards()
            if cards:
                CUS_LOGGER.debug(f"无推荐图标，选最左卡片 @ {cards[0]}（共 {len(cards)} 张）",
                                 extra={"flush": True})
                self.click_position(cards[0])
            else:
                CUS_LOGGER.warning("既没推荐图标也没找到卡片轮廓，点最左卡位置兜底",
                                   extra={"flush": True})
                self.click_position((480, BLESS_CARD_Y))
        key_mouse_manager.wait()
        time.sleep(0.5)
        self.click_text("确认")
        key_mouse_manager.wait()
        time.sleep(1.0)
        # 只认「本状态是否消失」：下一步可能是任意界面（通用通知、选择奇物、回大世界…），
        # 猜不得。界面上不再有「选择祝福」就说明这一批处理完了。
        if not self.has_bless_screen():
            CUS_LOGGER.debug("祝福界面已消失，本状态处理完毕", extra={"flush": True})
            self.stop()

    def in_3d_scene(self):
        """是否在 3D 场景里：左上角有「(N/20) 第X位面-类型」这行。

        这是区分战斗界面与 3D 场景最干净的判据——战斗界面这行不存在。
        """
        return bool(self.current_area_type())

    def has_dismiss_screen(self):
        """界面上是否有「点击空白处关闭」（通用通知）。"""
        x1, y1, x2, y2 = (880, 990, 1020, 1025)
        crop = self.get_screen()[y1:y2, x1:x2]
        if crop.size == 0:
            return False
        return "空白" in (self.ts.ocr_one_row(crop) or "")

    def wait_battle_end(self, timeout=180.0):
        """等战斗结束。

        不用「旗子消失 N 秒」这种时间阈值——终结技动画期间整个 UI 都会隐藏，旗子同样
        消失，靠时间去猜永远要给终结技留不确定的余量。

        改成等一个「战斗里不可能出现」的新界面：3D 区域标签 / 选择祝福 / 通用通知。
        这三样在战斗进行中都不会出现，所以终结技放多久都不会误判。超时兜底。
        """
        CUS_LOGGER.debug("等待战斗结束", extra={"flush": True})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.in_3d_scene():
                CUS_LOGGER.debug("战斗结束：已回到 3D 场景", extra={"flush": True})
                return True
            if self.has_bless_screen():
                CUS_LOGGER.debug("战斗结束：出现选择祝福", extra={"flush": True})
                return True
            if self.has_dismiss_screen():
                CUS_LOGGER.debug("战斗结束：出现通用通知", extra={"flush": True})
                return True
            time.sleep(1.0)
        CUS_LOGGER.warning(f"{timeout:.0f} 秒内没等到战斗结束", extra={"flush": True})
        return False

    def auto_battle_on(self):
        """自动战斗是否已开启：按钮呈黄色即开启，蓝灰即未开。"""
        x1, y1, x2, y2 = AUTO_BATTLE_BOX
        patch = self.get_screen()[y1:y2, x1:x2]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        return bool(hsv[:, :, 0].mean() < 40 and hsv[:, :, 1].mean() > 90)

    def ensure_auto_battle(self):
        """战斗里没开自动战斗就点一下（可选步骤，调用方自己决定要不要用）。"""
        if self.auto_battle_on():
            return True
        CUS_LOGGER.debug("自动战斗未开启，点一下按钮", extra={"flush": True})
        self.click_position(AUTO_BATTLE_POINT)
        key_mouse_manager.wait()
        time.sleep(0.8)
        return self.auto_battle_on()

    def current_area_type(self):
        """读左上角「(N/20) 第X位面-类型」，返回类型文字（战斗/事件/精英…）。

        这行是判断「当前区域要不要打怪」的唯一依据：战斗区才需要找怪进战，
        事件区直接走过去交互即可。区域序号和位面号都会变，只取「-」后面的类型。
        """
        x1, y1, x2, y2 = AREA_LABEL_BOX
        crop = self.get_screen()[y1:y2, x1:x2]
        if crop.size == 0:
            return ""
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        text = (self.ts.ocr_one_row(crop) or "").strip()
        match = re.search(r"[-—–]\s*([^\s\-(]+)", text)
        return match.group(1) if match else text

    def in_battle_area(self):
        """当前区域是不是「战斗」类型。"""
        return "战斗" in self.current_area_type()

    def has_monster_info(self):
        """顶部出现「等级XX xxx团」信息条 → 视野内有怪。

        等级数字和团名都会变（不同区域、不同怪物），所以只判「这块区域有没有文字 +
        是否含『等级』二字」，不碰具体内容。001 无怪 / 005 打完怪时这块都是空的。
        """
        x1, y1, x2, y2 = MONSTER_INFO_BOX
        for item in self.ts.res:
            box = item["box"]
            if box[0] >= x1 and box[3] <= y2 and "等级" in item["raw_text"]:
                return True
        return False

    def in_battle(self):
        """左上角小旗子出现 = 已在战斗界面（实测战斗 0.998 / 3D 场景 0.6x）。

        check() 必须给 x/y 或 mask，否则会走到 get_local(None, None) 抛 int(None)。
        """
        # fresh=True：battle 阶段不走主循环，self.screen 不会自动刷新，必须自己抓一帧
        return bool(self.check(BATTLE_FLAG, x=BATTLE_FLAG_POINT[0], y=BATTLE_FLAG_POINT[1],
                               threshold=0.85, fresh=True))

    def has_lock_on(self):
        """红圈准星出现 = 已锁定怪物。红圈不一定在屏幕内（多只怪时可能锁到视野外）。"""
        return bool(self.check(LOCK_RING, mask=(0, 0, 1920, 1080), threshold=0.75, fresh=True))

    def turn_view(self, pixels):
        """鼠标相对移动转视角。用 mouse_event 的 MOVE 而不是 SetCursorPos：
        游戏读的是相对位移，绝对定位会被当成「瞬移」而丢失视角。"""
        import win32api
        import win32con

        # dx 才是水平位移；早先误写成 dy，结果每"转一次"都在把视角往下拉
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, int(pixels), 0, 0, 0)

    def walk(self, seconds=None):
        """按住前进键走一小段。"""
        seconds = WALK_SECONDS if seconds is None else seconds
        key_mouse_manager.keyDown("move_w")
        time.sleep(seconds)
        key_mouse_manager.keyUp("move_w")

    def attack(self):
        """原地左键普攻（不移动准星，避免打空）。"""
        import win32api
        import win32con

        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.06)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def scan_for_monster(self):
        """原地转一圈找怪：没看到就转视角，看到就前进靠近，红圈出现再普攻。

        不保证一次普攻就进战斗（角色攻击范围较小时会打空），所以普攻后复查小旗子。
        """
        for _ in range(24):          # 最多转一圈（24 × TURN_PIXELS）
            if self.in_battle():
                return True
            if not self.has_monster_info():
                self.turn_view(TURN_PIXELS)
                time.sleep(0.35)
                continue
            # 视野里有怪：朝当前朝向靠近，边走边砍
            # 不靠红圈判断「能否攻击」——红圈常与怪物身体重合，模板匹配实测只有 0.5，
            # 而且不一定落在屏幕内。靠近途中反复普攻，打中就进战斗，打空继续走。
            for _ in range(12):
                if self.in_battle():
                    return True
                self.walk()
                time.sleep(0.15)
                self.attack()
                time.sleep(1.0)   # 普攻频率按实测减半
                if self.in_battle():
                    return True
        return False

    def engage_front(self):
        """从出生点正面推进：差分宇宙的出生点怪物必定在正前方，直接前进+普攻。"""
        for _ in range(14):
            if self.in_battle():
                return True
            self.walk()
            time.sleep(0.15)
            self.attack()
            time.sleep(1.0)   # 普攻频率按实测减半
            if self.in_battle():
                return True
        return False

    def wait_and_click(self, text, timeout=8.0):
        """等某段文字出现再点它，超时返回 False。

        比「固定 sleep + 点一次」可靠：界面加载快慢不定，点早了会落空。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.click_text(text):
                return True
            time.sleep(0.5)
        return False

    def reset_to_spawn(self):
        """卡住时的兜底：ESC → 暂离 → F → 开始游戏 → 继续进度，把角色重置回出生点。

        链路来自实机截图 ex1~ex4。重置后怪物必定在正前方，直接前进就能撞上。
        F 要重试：退回大世界后角色落点/加载时机不定，一次没进很常见。
        """
        CUS_LOGGER.debug("尝试重置回出生点", extra={"flush": True})
        paused = False
        for _ in range(3):                   # ESC 也可能被吞，重试三次
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            if self.wait_and_click("暂离", timeout=3):
                paused = True
                break
        if not paused:
            CUS_LOGGER.warning("三次 ESC 都没出现暂停界面", extra={"flush": True})
            return False
        time.sleep(2.5)                      # 退回大世界
        entered = False
        for _ in range(3):                   # F 最多试三次
            key_mouse_manager.press("interact")
            key_mouse_manager.wait()
            time.sleep(2.0)
            if self.click_text("开始游戏"):
                entered = True
                break
        if not entered:
            CUS_LOGGER.warning("三次按 F 都没进到差分宇宙主页", extra={"flush": True})
            return False
        if not self.wait_and_click("继续进度", timeout=6):
            CUS_LOGGER.warning("模式选择页没找到「继续进度」", extra={"flush": True})
            return False
        time.sleep(3.5)                      # 等重新加载进 3D
        return True

    def find_and_engage(self):
        """找怪并进入战斗。

        顺序按「最可能命中」排：
        1. 先正面推进——出生点/重置后的怪必定在正前方，这一步就够的情况最多
        2. 走偏了再转一圈找
        3. 还不行为重置回出生点，再正面推一次
        """
        if self.engage_front():
            return True
        CUS_LOGGER.debug("正面没撞上，转视角找一圈", extra={"flush": True})
        if self.scan_for_monster():
            return True
        CUS_LOGGER.warning("一圈也没找到，重置回出生点", extra={"flush": True})
        if not self.reset_to_spawn():
            return False
        if self.engage_front():
            return True
        CUS_LOGGER.error("重置后正面推进仍没进战斗", extra={"flush": True})
        return False

    def read_mask_progress(self):
        """读面板上的面具等级与经验进度；面板收起时返回 None。

        Returns:
            (等级, 上限, 进度 0~1) 或 None。

        做法是直接读游戏显示的数字，而不是按面具内置愿力算法表——14 张面具各一套
        需求曲线既难维护又容易过期，而 `Lv N/20` 是游戏自己算的。
        经验条用列亮度找填充边界：填充段实测亮度 ~86，空槽 ~2。
        """
        screen = self.get_screen()
        x1, y1, x2, y2 = PANEL_LEVEL_BOX
        crop = screen[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = (self.ts.ocr_one_row(crop) or "").replace(" ", "")
        match = re.search(r"(\d+)/(\d+)", text)
        if not match:          # 面板收起时这块是别的文字，读不出 N/M
            return None
        level, cap = int(match.group(1)), int(match.group(2))
        bx1, by1, bx2, by2 = PANEL_PROGRESS_BOX
        bar = screen[by1:by2, bx1:bx2]
        ratio = 0.0
        if bar.size:
            filled = int((bar.mean(axis=(0, 2)) > PANEL_BAR_BRIGHT).sum())
            ratio = filled / bar.shape[1]
        return level, cap, ratio

    def mask_level_full(self, progress):
        """本级经验条是否已满（= 通过当前区域后会升级）。"""
        return progress is not None and progress[2] >= PANEL_BAR_FULL

    def ensure_panel(self):
        """确保对局面板展开；返回 (等级, 上限, 进度) 或 None。

        3D 场景里鼠标被游戏锁定的（视角跟随），必须先按住 Alt 把光标呼出来，才能点
        左上角的展开箭头——否则点击会变成转视角/攻击。

        用 pyautogui 而不是 win32api.keybd_event：后者是旧的键事件 API，游戏收不到，
        实测按住 Alt 再点击完全没反应。项目里其余按键也都走 pyautogui（底层 SendInput）。
        """
        progress = self.read_mask_progress()
        if progress is not None:
            return progress
        import pyautogui

        CUS_LOGGER.debug("面板收起：按住 Alt 呼出光标后点展开箭头", extra={"flush": True})
        pyautogui.keyDown("alt")
        try:
            time.sleep(0.25)  # 等游戏切到「光标模式」
            self.click_position(PANEL_TOGGLE)
            key_mouse_manager.wait()
            time.sleep(0.25)
        finally:
            pyautogui.keyUp("alt")  # 放 finally：异常时也不能让 Alt 一直按着
        time.sleep(0.5)
        return self.read_mask_progress()

    def select_equation(self):
        """点中间那个方程，再点右下角确认。

        不排优先级——每个人队伍不同，选哪个方程收益差别很大；中间那张最省事，
        也避开「最左边往往是给别人配的」这类争议。
        """
        self.click_position(EQUATION_MIDDLE)
        key_mouse_manager.wait()
        time.sleep(0.6)  # 等卡片选中动画，确认按钮才会亮
        self.click_position(EQUATION_CONFIRM)
        key_mouse_manager.wait()
        time.sleep(0.8)

    def ensure_practice_mode(self):
        """确保当前在「练习模式」页。

        ranked 与 practice 两页都有「启动」按钮和「阈值协议」，只靠文字区分不开；
        但练习页中部显示「该模式不影响星阶」，拓星页显示「你已至星之尽头」。
        在拓星页误点「启动」会真的影响星阶，所以这一步不能省。
        """
        if any("不影响星阶" in item["raw_text"] for item in self.ts.res):
            return
        items = self.ts.find_with_box([960, 1260, 100, 180], redundancy=10)
        for item in items:
            if "练习模式" in item["raw_text"]:
                box = item["box"]
                CUS_LOGGER.debug("当前不在练习模式，切换标签", extra={"flush": True})
                self.click_position(((box[0] + box[1]) / 2, (box[2] + box[3]) / 2))
                key_mouse_manager.wait()
                time.sleep(0.8)
                return
        CUS_LOGGER.warning("未找到「练习模式」标签，按当前页面继续", extra={"flush": True})

    def read_protocol(self):
        """读当前阈值协议，读不到返回 None。

        整屏 OCR 认不出那个单独的大号数字（det 阶段会漏），所以单独裁数字区域放大后再认；
        用 ocr_one_row 而不是 forward，避免覆盖主循环缓存的整屏识别结果。
        """
        screen = self.get_screen()
        x1, y1, x2, y2 = PROTOCOL_DIGIT_BOX
        crop = screen[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = self.ts.ocr_one_row(crop)
        digits = "".join(ch for ch in (text or "") if ch.isdigit())
        return int(digits) if digits else None

    def check_protocol(self):
        """把阈值协议调整到 self.target_protocol（1~9）。

        每局都读一次当前值再按需点 +/− ：游戏会记住上次选择，通常第一次调整后就一直
        相等，不会再点。识别不到数字时只告警并继续，避免把整条入场卡在练习页。
        """
        target = self.target_protocol
        if target is None:
            return
        for _ in range(12):  # 1~9 最大跨度 8 次，留一点余量
            current = self.read_protocol()
            if current is None:
                CUS_LOGGER.warning("未识别到阈值协议数字，跳过调整继续启动", extra={"flush": True})
                return
            if current == target:
                return
            point = PROTOCOL_PLUS if current < target else PROTOCOL_MINUS
            CUS_LOGGER.debug(f"阈值协议 {current} → {target}，点击{'加号' if point == PROTOCOL_PLUS else '减号'}",
                             extra={"flush": True})
            self.click_position(point)
            key_mouse_manager.wait()
            time.sleep(0.35)
        CUS_LOGGER.warning(f"阈值协议未能调整到 {target}，按当前值继续启动", extra={"flush": True})


def main(default_stage="entry"):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--samples", type=Path, help="Offline recognition only, never sends input")
    mode.add_argument("--run", action="store_true", help="One bounded sequence; F8 stops input")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", choices=("entry", "team", "mask", "equation", "panel", "battle", "auto", "waitend", "bless", "masks", "opening", "gallery"), default=default_stage,
                        help="entry: 全流程到面具页；team: 只验证配队那一段；masks/opening: 开局筛选")
    parser.add_argument("--protocol", type=int, default=DEFAULT_PROTOCOL,
                        help=f"目标阈值协议（{PROTOCOL_RANGE[0]}~{PROTOCOL_RANGE[1]}），默认 {DEFAULT_PROTOCOL}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples and args.stage not in ("entry", "masks"):
        parser.error("--samples supports entry or masks only")
    output = (args.output or ROOT / "logs" / f"divine-{args.stage}-{time.time_ns()}").resolve()
    sample_dir = args.samples.resolve() if args.samples else None
    os.chdir(ROOT)
    if args.run:
        import win32api
        import win32con

        CUS_LOGGER.debug(f"Stage: {args.stage}\nOutput: {output}\nFocus the game within 5 seconds. F8 or switching away stops.", extra={"flush": True})
        worker = subprocess.Popen(
            [sys.executable, str(ROOT / "divine_treasure_entry.py"), "--worker", "--stage", args.stage,
             "--output", str(output)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            limit = 150 if args.stage == "entry" else 240
            deadline = time.monotonic() + limit
            while worker.poll() is None:
                if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
                    raise InterruptedError("F8 pressed")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{limit}-second hard limit reached")
                time.sleep(0.1)
            return worker.returncode
        except (TimeoutError, InterruptedError, KeyboardInterrupt) as error:
            CUS_LOGGER.error(f"STOPPED: {type(error).__name__}", extra={"flush": True})
            return 2
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
                win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)

    if sample_dir:
        from tool.onnxocr.onnx_paddleocr import ONNXPaddleOcr

        ocr = ONNXPaddleOcr(use_angle_cls=False, cpu=True)
        if args.stage == "masks":
            from divine_treasure_masks import SAMPLE_STATES
            from divine_treasure_masks import inspect_screen as inspect_masks

            summary = []
            for number, expected in enumerate(SAMPLE_STATES, 1):
                paths = [p for p in sample_dir.glob("*.png") if re.match(rf"^{number}\D", p.name)]
                if len(paths) != 1:
                    raise ValueError(f"Expected one sample {number}, found {len(paths)}")
                image = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
                result = inspect_masks(image, ocr)
                save_evidence(output, f"sample-{number}", image, result)
                passed = result["state"] == expected
                summary.append(passed)
                CUS_LOGGER.debug(f"Sample {number}: {result['state']}, {'PASS' if passed else 'FAIL'}", extra={"flush": True})
            return 0 if all(summary) else 1
        summary = []
        for number, expected in enumerate(STATES[:5], 1):
            paths = list(sample_dir.glob(f"{number}*.png"))
            if len(paths) != 1:
                raise ValueError(f"Expected exactly one sample numbered {number}, found {len(paths)}")
            image = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
            result = inspect_screen(image, ocr)
            save_evidence(output, f"sample-{number}", image, result)
            passed = result["state"] == expected and (number != 5 or result["protocol"] == 5)
            summary.append(passed)
            CUS_LOGGER.debug(f"Sample {number}: {result['state']}, protocol={result['protocol']}, {'PASS' if passed else 'FAIL'}", extra={"flush": True})
        CUS_LOGGER.debug(f"Offline evidence: {output}", extra={"flush": True})
        return 0 if all(summary) else 1

    from tool.action_script import run_script

    kernel = DivineTreasureKernel()
    kernel.target_protocol = max(PROTOCOL_RANGE[0], min(PROTOCOL_RANGE[1], args.protocol))
    if args.stage == "team":
        kernel.action_groups = ["team"]
    elif args.stage == "mask":
        # dismiss 放前面：选完面具会弹「点击空白处关闭」，先把它关掉才看得到下一界面
        kernel.action_groups = ["dismiss", "masks"]
    elif args.stage == "equation":
        kernel.action_groups = ["dismiss", "equation"]
    try:
        if args.stage in ("entry", "team", "mask", "equation"):
            run_script(kernel, str(ACTION_SCRIPT))
        if args.stage == "bless":
            # 走 JSON 主循环，验证「识别到选择祝福 → 选推荐 → 确认」整条链路
            kernel.action_groups = ["dismiss", "bless"]
            run_script(kernel, str(ACTION_SCRIPT))
            return 0
        if args.stage == "waitend":
            kernel.prepare_script()
            if not kernel.wait_battle_end():
                CUS_LOGGER.error("没能确认战斗结束", extra={"flush": True})
                return 2
            CUS_LOGGER.debug(f"战斗结束，当前区域类型：{kernel.current_area_type()}", extra={"flush": True})
            return 0
        if args.stage == "auto":
            # 自动战斗是可选步骤：单独跑，验证「没开就点、已开不动」
            kernel.prepare_script()
            before = kernel.auto_battle_on()
            CUS_LOGGER.debug(f"自动战斗当前：{'已开启' if before else '未开启'}", extra={"flush": True})
            ok = kernel.ensure_auto_battle()
            CUS_LOGGER.debug(f"处理后：{'已开启' if ok else '仍未开启'}", extra={"flush": True})
            return 0 if ok else 2
        if args.stage == "battle":
            kernel.prepare_script()
            if not kernel.find_and_engage():
                CUS_LOGGER.error("没能找到并进入战斗", extra={"flush": True})
                return 2
            CUS_LOGGER.debug("已进入战斗界面（小旗子）", extra={"flush": True})
            return 0
        if args.stage == "panel":
            # 不走 run_script 就没有 prepare_script，键鼠管理器线程不会启动，
            # 此时 click_position 只是入队、没人执行
            kernel.prepare_script()
            result = kernel.ensure_panel()
            if result is None:
                CUS_LOGGER.error("展不开面板或读不到等级", extra={"flush": True})
                return 2
            level, cap, ratio = result
            CUS_LOGGER.debug(f"面具等级 Lv {level}/{cap}，本级进度 {ratio:.0%}", extra={"flush": True})
            return 0
        if args.stage in ("masks", "opening"):
            from divine_treasure_masks import run

            attempt = 1
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                result = run(kernel.ts, output / f"attempt-{attempt:02d}" / "masks")
                if not result["restart"]:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Opening retry time limit reached")
                attempt += 1
                CUS_LOGGER.debug(f"Restarting opening: attempt {attempt}", extra={"flush": True})
                run_script(kernel, str(ACTION_SCRIPT))
        if args.stage == "gallery":
            from collect_snow_masks import run

            run(kernel.ts, output)
        return 0
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "error.txt").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        CUS_LOGGER.error(f"STOPPED: {error}\nEvidence: {output}", extra={"flush": True})
        return 2
    finally:
        kernel.stop()


if __name__ == "__main__":
    sys.exit(main())
