"""日常内核：JSON 动作编排，以及日常遗器本所需的识别原语。"""

import re
import time

import numpy as np

from core.common.runtime import ScriptKernel
from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import clean_text
from tool.storage import load_module_settings
from tool.utils.minimap_util import MINIMAP_RADIUS, get_minimap

# 生存索引左侧菜单的固定顺序，从上到下。
MENU_ITEMS = (
    "培养目标",
    "饰品提取",
    "拟造花萼",
    "凝滞虚影",
    "侵蚀隧洞",
    "历战余响",
)
# 运行模式 → 左侧菜单里要点击的分类名。
MODULE_CATEGORY = {"inner": "饰品提取", "outer": "侵蚀隧洞"}
# 小地图红点进入该像素距离内即视为可以攻击。
ENEMY_ATTACK_RANGE = 18


class DailyKernel(ScriptKernel):
    """日常任务内核。

    继承通用内核的窗口、截图与 OCR 能力；本类提供日常遗器本 JSON 脚本
    调用的原语，流程本身见 core/daily/actions/daily_relic.json。
    """

    def __init__(self):
        super().__init__()
        self.daily_config = load_module_settings(__file__)
        self.relic_config = self.daily_config["daily_relic"]

    def esc_end(self):
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.stop()

    def select_relic_category(self):
        """在生存索引左侧菜单滚动查找并点击配置的副本分类。"""
        module = self._relic_module()
        target = MODULE_CATEGORY[module]
        target_idx = MENU_ITEMS.index(target)
        if self._stop or get_global_stop_flag():
            return
        items = self._scan_menu_texts()
        target_box = self._find_menu_item(items, target)
        if target_box is not None:
            CUS_LOGGER.debug("找到分类：%s", target)
            self.click_box(target_box)
            key_mouse_manager.wait()
            return
        direction = self._scroll_direction(items, target_idx)
        # 鼠标悬停在左侧菜单上滚动，每次滚 3 格。
        key_mouse_manager.scroll_point(470, 580, direction * 3)
        key_mouse_manager.wait()

    def enter_relic_dungeon(self, timeout=60.0):
        """在副本列表中滚动定位配置的副本，并点击同一行的「进入」。"""
        module = self._relic_module()
        target = self._relic_target(module)
        if not target:
            raise RuntimeError(f"未在配置中指定 {module} 副本名")
        deadline = time.monotonic() + timeout
        # 最多识别 16 次，每次没找到就向下滚一屏。
        for _ in range(16):
            if self._stop or get_global_stop_flag():
                return
            if time.monotonic() > deadline:
                break
            enter_pos = self._find_enter_right(target)
            if enter_pos is not None:
                CUS_LOGGER.debug("找到副本 %s，点击进入 %s", target, enter_pos)
                key_mouse_manager.click_point(*enter_pos)
                key_mouse_manager.wait()
                return
            key_mouse_manager.scroll_point(1358, 698, -5)
            key_mouse_manager.wait()
        raise RuntimeError(f"未在列表中找到目标副本：{target}")

    def release_secret_skills(self):
        """按配置的槽位顺序与延迟释放秘技。"""
        order = self._parse_skill_order()
        if not order:
            CUS_LOGGER.debug("秘技顺序为空，跳过释放")
            return
        delay = float(self.relic_config["inner_skill_delay"])
        switch_delay = float(self.relic_config["inner_skill_switch_delay"])
        for index, slot in enumerate(order):
            if self._stop or get_global_stop_flag():
                return
            CUS_LOGGER.debug("释放秘技：%s 号位", slot)
            key_mouse_manager.press(slot)
            key_mouse_manager.wait()
            key_mouse_manager.sleep(switch_delay)
            key_mouse_manager.wait()
            key_mouse_manager.press("e")
            key_mouse_manager.wait()
            if index < len(order) - 1:
                key_mouse_manager.sleep(delay)
                key_mouse_manager.wait()

    def approach_enemy(self, timeout=180.0):
        """内圈：按小地图红点接近敌人并左键攻击，进入战斗后返回。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop or get_global_stop_flag():
                return
            self.get_screen()
            if self._battle_active():
                CUS_LOGGER.debug("已进入战斗，停止接近")
                return
            distance = self._enemy_distance()
            if distance is None:
                CUS_LOGGER.debug("未检测到小地图红点，等待下一轮")
                continue
            CUS_LOGGER.debug("敌人距离 %.1f，攻击阈值 %s",
                             distance, ENEMY_ATTACK_RANGE)
            if distance <= ENEMY_ATTACK_RANGE:
                # 进入攻击范围后左键点画面中心出手。
                key_mouse_manager.click_point(self.xx // 2, self.yy // 2)
                key_mouse_manager.wait()
                return
            # 每轮按 W 0.3 秒向红点靠近。
            key_mouse_manager.press("w", 0.3)
            key_mouse_manager.wait()
        raise RuntimeError("接近敌人超时")

    def apply_support(self):
        """按配置选择支援替换位置；未开启支援时直接返回。"""
        module = self._relic_module()
        if not self.relic_config[f"{module}_support"]:
            return
        # 支援入口：内圈在画面右下，外圈在「挑战」按钮旁边。
        entry_box = ([688, 880, 739, 910] if module == "inner"
                     else [1053, 969, 1104, 999])
        # 支援列表标题：内圈为「支援列表」，外圈为「支援角色」。
        anchor, anchor_box = (("支援列表", [248, 74, 348, 103]) if module == "inner"
                              else ("支援角色", [384, 76, 472, 103]))
        slot = int(self.relic_config[f"{module}_support_slot"])
        if not self._wait_click("支援", entry_box, timeout=5):
            return
        if not self._wait_text(anchor, anchor_box, timeout=5):
            return
        # 替换位置 1~4 号位在内圈、外圈界面上的坐标。
        slot_boxes = (
            (
                [631, 805, 684, 831],
                [720, 803, 777, 832],
                [821, 805, 873, 834],
                [908, 802, 959, 833],
            )
            if module == "inner"
            else (
                [745, 497, 791, 522],
                [1056, 529, 1108, 559],
                [1357, 496, 1439, 537],
                [1671, 524, 1740, 570],
            )
        )
        self.click_box(slot_boxes[slot - 1])
        self.click_box([165, 204, 270, 236])
        self._wait_click("确认", [1654, 970, 1714, 1009], timeout=5)
        key_mouse_manager.wait()

    # ---------- 识别与读取 ----------

    def _relic_module(self):
        module = self.relic_config["module"]
        if module not in MODULE_CATEGORY:
            raise ValueError(f"未知的日常遗器本模式：{module}")
        return module

    def _relic_target(self, module):
        return str(self.relic_config[module])

    def _wait_text(self, anchor, box, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop or get_global_stop_flag():
                return False
            self.ts.forward(self.get_screen())
            items = self.ts.find_with_box(box=box, redundancy=20)
            if any(anchor in clean_text(item["raw_text"]) for item in items):
                return True
        return False

    def _wait_click(self, anchor, box, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop or get_global_stop_flag():
                return False
            self.ts.forward(self.get_screen())
            items = self.ts.find_with_box(box=box, redundancy=20)
            if any(anchor in clean_text(item["raw_text"]) for item in items):
                self.click_box(box)
                key_mouse_manager.wait()
                return True
        return False

    def _scan_menu_texts(self):
        """扫描生存索引左侧菜单区域，返回识别到的文字项。"""
        self.ts.forward(self.get_screen())
        items = self.ts.find_with_box(box=[240, 270, 700, 890], redundancy=20)
        CUS_LOGGER.debug(
            "菜单识别：%s", [clean_text(item["raw_text"]) for item in items])
        return items

    @staticmethod
    def _find_menu_item(items, target):
        for item in items:
            if target in clean_text(item["raw_text"]):
                return item["box"]
        return None

    @staticmethod
    def _scroll_direction(items, target_idx):
        nearest = None
        for item in items:
            text = clean_text(item["raw_text"])
            for idx, name in enumerate(MENU_ITEMS):
                if idx == target_idx or name not in text:
                    continue
                if nearest is None or abs(idx - target_idx) < abs(nearest - target_idx):
                    nearest = idx
        if nearest is None:
            return 0
        return -1 if nearest < target_idx else 1

    def _find_enter_right(self, target_name):
        """返回目标副本同一行右侧「进入」按钮的中心坐标。"""
        match_name = target_name.split("-", 1)[0]
        self.ts.forward(self.get_screen())
        named = [item for item in self.ts.find_with_box(
                     box=[660, 260, 1700, 990], redundancy=20)
                 if match_name in clean_text(item["raw_text"])]
        if not named:
            return None
        name_box = named[0]["box"]
        name_y = (name_box[1] + name_box[3]) / 2
        name_x2 = name_box[2]
        best = None
        best_dy = float("inf")
        for item in self.ts.res:
            box = item["box"]
            if "进入" not in clean_text(item["raw_text"]):
                continue
            if box[0] <= name_x2:
                continue
            dy = abs((box[1] + box[3]) / 2 - name_y)
            # 「进入」必须与副本名同一行，允许 40px 内的纵向偏差。
            if dy <= 40.0 and dy < best_dy:
                best_dy = dy
                best = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        return best

    def _read_int_in_box(self, box, image=None):
        img = self.get_screen() if image is None else image
        text = self.ts.ocr_one_row(img, box)
        if not text:
            return None
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None

    def _parse_skill_order(self):
        raw = str(self.relic_config["inner_skill_order"]).strip()
        if not raw:
            return []
        if not all(c in "1234" for c in raw):
            CUS_LOGGER.warning("秘技顺序只能包含 1/2/3/4，已跳过释放")
            return []
        if len(set(raw)) != len(raw):
            CUS_LOGGER.warning("秘技顺序不能有重复数字，已跳过释放")
            return []
        return list(raw)

    def _battle_active(self):
        """自动战斗图标或战斗状态图标任一命中，即视为战斗中。"""
        return (self.check("auto_2", 112, 83)
                or self.check("battle", 1842, 1056))

    def _enemy_distance(self):
        """返回小地图红点距中心的最小像素距离；未检测到红点时返回 None。"""
        local = get_minimap(self.screen, radius=MINIMAP_RADIUS,
                            copy=True, rotation=True)
        # 红点的 BGR 颜色；容差用于吸收渲染差异。
        mask = np.sum((local - np.array((47, 47, 232))) ** 2, axis=-1) <= 5000
        ys, xs = np.where(mask)
        if len(ys) == 0:
            return None
        distances = np.sqrt(
            (xs - MINIMAP_RADIUS) ** 2 + (ys - MINIMAP_RADIUS) ** 2)
        return float(distances.min())


def create_engine(*, script=False):
    return DailyKernel()
