import os

import cv2 as cv

from route import PATHS
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.utils.ocr_num import match_skill_numbers_in_region


class SilverWolfManager:
    """银狼秘技：在触发区域内切换到银狼并释放秘技。

    银狼所在角色位在首次进入触发区域时判断并缓存，之后复用；秘技点与
    秘技图标的识别都基于主循环的同一张截图，不重复截图。
    """

    # 银狼头像在四个角色位上的比例坐标
    _SILVER_WOLF_POS = {
        1: (0.9385, 0.2963),
        2: (0.9385, 0.3833),
        3: (0.9385, 0.4694),
        4: (0.9385, 0.5565),
    }
    # 秘技图标（bean）在四个角色位上的比例坐标
    _BEAN_POS = {
        1: (0.8464, 0.2944),
        2: (0.8464, 0.3787),
        3: (0.8464, 0.4657),
        4: (0.8464, 0.5519),
    }

    def __init__(self, parent):
        self.parent = parent
        self.silver_wolf_slot = None

    def _check_character(self, template_name, x_ratio, y_ratio, threshold=0.7, fresh=False):
        """在固定比例坐标附近进行局部模板匹配。

        Args:
            template_name: resource/imgs 下的模板文件名，不含扩展名。
            x_ratio: 匹配中心横坐标相对屏幕宽度的比例。
            y_ratio: 匹配中心纵坐标相对屏幕高度的比例。
            threshold: 相似度阈值。
            fresh: 是否重新截图；False 时复用 self.parent.screen。

        Returns:
            匹配相似度是否达到阈值；模板缺失或截图区域不足时返回 False。
        """
        if fresh:
            img = self.parent.get_screen()
        else:
            img = self.parent.screen
        h, w = img.shape[:2]
        px, py = int(x_ratio * w), int(y_ratio * h)
        template_path = os.path.join(PATHS["root"], "resource", "imgs", template_name + ".jpg")
        tpl = cv.imread(template_path, cv.IMREAD_GRAYSCALE)
        if tpl is None:
            CUS_LOGGER.error(f"模板文件不存在: {template_path}")
            return False
        th, tw = tpl.shape[:2]
        x0 = max(0, px - tw)
        y0 = max(0, py - th)
        x1 = min(w, px + tw)
        y1 = min(h, py + th)
        if x1 - x0 < tw or y1 - y0 < th:
            return False
        roi = img[y0:y1, x0:x1]
        roi_gray = cv.cvtColor(roi, cv.COLOR_BGR2GRAY)
        res = cv.matchTemplate(roi_gray, tpl, cv.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv.minMaxLoc(res)
        return max_val >= threshold

    def is_silver_wolf_at(self, slot):
        """判断指定角色位是否处于银狼。

        Args:
            slot: 角色位序号（1~4）。

        Returns:
            该位置是否为银狼。
        """
        x_ratio, y_ratio = self._SILVER_WOLF_POS[slot]
        return self._check_character("silverwolf", x_ratio, y_ratio, threshold=0.85)

    def find_silver_wolf_slot(self):
        """在当前主循环截图中找出银狼所在角色位。

        Returns:
            银狼所在角色位序号（1~4）；未找到返回 None。
        """
        for slot in self._SILVER_WOLF_POS:
            if self.is_silver_wolf_at(slot):
                return slot
        return None

    def has_bean_icon(self, slot):
        """判断指定角色位是否已显示秘技图标。

        Args:
            slot: 角色位序号（1~4）。

        Returns:
            该位置是否显示秘技图标。
        """
        x_ratio, y_ratio = self._BEAN_POS[slot]
        return self._check_character("bean", x_ratio, y_ratio, threshold=0.7)

    def should_skip_skill(self):
        """判断是否应跳过秘技、改用普通攻击以保留秘技点。

        仅在二号位银狼秘技开启、且一号位为黄泉或白厄时生效：
        - 黄泉：剩余秘技点 ≤ 1 时跳过
        - 白厄：剩余秘技点 ≤ 2 时跳过

        Returns:
            True 表示应跳过秘技直接平A；未开启银狼、非黄泉/白厄、
            识别失败时返回 False，保持原行为。
        """
        if not self.parent.opt.get("silver_wolf_enable", False):
            return False
        if self.parent.quan:
            threshold = 1
        elif self.parent.bai_e:
            threshold = 2
        else:
            return False
        skill_num = match_skill_numbers_in_region(self.parent.get_screen())
        if skill_num is None:
            return False
        return skill_num <= threshold

    def activate(self):
        """在触发区域内切换到银狼。

        银狼位置只在首次进入触发区时判断并缓存；一号位银狼由调用方的
        历史逻辑处理，这里不接管。秘技点识别与秘技图标识别共用主循环
        截图，调用方在下一轮判断秘技图标并按 e。

        Returns:
            True 表示已切换到银狼所在位（或扑满节点切抓猪角色），调用方
            不要干涉角色切换；
            False 表示当前无需处理或无法处理，调用方按常规流程切回一号位。
        """
        if self.parent.need_end:
            return False
        if not self.parent.opt.get("silver_wolf_enable", False):
            return False
        in_trigger = any(kw in self.parent.area for kw in ("精英", "奖励", "事件", "首领"))
        in_pig = self.parent.is_pig_node()
        if not (in_trigger or in_pig):
            return False
        # 精英即使带扑满角标也按普通触发区域处理
        pig_only = in_pig and "精英" not in self.parent.area

        if self.silver_wolf_slot is None:
            self.silver_wolf_slot = self.find_silver_wolf_slot()
        if self.silver_wolf_slot is None:
            CUS_LOGGER.debug("银狼秘技：未识别到银狼位置")
            return False
        # 一号位银狼由调用方的历史逻辑处理，这里不接管
        if self.silver_wolf_slot == 1:
            return False

        skill_num = match_skill_numbers_in_region(self.parent.screen)
        if skill_num is None:
            CUS_LOGGER.warning("剩余秘技点识别失败")
            if pig_only:
                self.parent.switch_to_configured_role()
                return True
            return False
        self.parent.skill_num = skill_num

        CUS_LOGGER.debug(f"银狼秘技：剩余秘技点={skill_num}，银狼位于{self.silver_wolf_slot}号位")
        if skill_num < 1:
            if pig_only:
                CUS_LOGGER.debug("银狼秘技：扑满节点且秘技点为 0，切换抓猪角色")
                self.parent.switch_to_configured_role()
                return True
            CUS_LOGGER.debug("银狼秘技：秘技点为 0，切回一号位")
            self.parent.switch_current_role(1)
            return True

        self.parent.switch_current_role(self.silver_wolf_slot)
        self.parent.quan = 0
        self.parent.bai_e = 0
        key_mouse_manager.wait()
        return True