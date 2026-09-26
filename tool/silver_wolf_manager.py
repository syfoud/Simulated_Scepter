import os

from route import PATHS
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.utils.ocr_num import match_skill_numbers_in_region


class SilverWolfManager:
    """银狼秘技：在触发区域内切换到银狼并释放秘技。

    银狼所在角色位在首次进入触发区域时判断并缓存，之后复用；秘技点与
    秘技图标的识别都基于主循环的同一张截图，不重复截图。
    """

    # 四个角色位的比例坐标（check 镜像坐标，对应屏幕原始坐标
    # (0.9385, 0.2963)、(0.9385, 0.3833)、(0.9385, 0.4694)、(0.9385, 0.5565)
    _SILVER_WOLF_POS = {
        1: (0.0615, 0.7037),
        2: (0.0615, 0.6167),
        3: (0.0615, 0.5306),
        4: (0.0615, 0.4435),
    }
    # 秘技图标在四个角色位上的比例坐标（check 镜像坐标）
    # (0.8464, 0.2944)、(0.8464, 0.3787)、(0.8464, 0.4657)、(0.8464, 0.5519)
    _BEAN_POS = {
        1: (0.1536, 0.7056),
        2: (0.1536, 0.6213),
        3: (0.1536, 0.5343),
        4: (0.1536, 0.4481),
    }
    # 角色位与秘技图标识别阈值；队伍列表为亮底块状 UI，
    # 低于该阈值时 TM_CCORR_NORMED 会把非银狼头像判为命中
    _CHECK_THRESHOLD = 0.98

    def __init__(self, parent):
        self.parent = parent
        self.silver_wolf_slot = None

    def is_silver_wolf_at(self, slot):
        """判断指定角色位是否处于银狼。

        Args:
            slot: 角色位序号（1~4）。

        Returns:
            该位置是否为银狼。
        """
        x_ratio, y_ratio = self._SILVER_WOLF_POS[slot]
        return self.parent.check(
            "silverwolf", x_ratio, y_ratio, threshold=self._CHECK_THRESHOLD
        )

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
        return self.parent.check(
            "bean", x_ratio, y_ratio, threshold=self._CHECK_THRESHOLD
        )

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
        """确保银狼位置缓存，并在触发区内切换到 2/3/4 号位银狼。

        位置缓存只在首次调用时判断，0 表示已判断未发现银狼；一号位与
        未识别到银狼的情况由调用方处理。

        Returns:
            True 表示已切换到银狼所在位（或扑满节点切抓猪角色），调用方
            不要干涉角色切换；
            False 表示当前无需处理或无法处理。
        """
        if self.parent.need_end:
            return False
        if self.silver_wolf_slot is None:
            slot = self.find_silver_wolf_slot()
            self.silver_wolf_slot = slot if slot is not None else 0
            if self.silver_wolf_slot == 0:
                CUS_LOGGER.debug("银狼秘技：未识别到银狼位置")
        if self.silver_wolf_slot not in (2, 3, 4):
            return False

        in_trigger = any(kw in self.parent.area for kw in ("精英", "奖励", "事件", "首领"))
        in_pig = self.parent.is_pig_node()
        if not (in_trigger or in_pig):
            return False
        # 精英即使带扑满角标也按普通触发区域处理
        pig_only = in_pig and "精英" not in self.parent.area

        skill_num = match_skill_numbers_in_region(self.parent.screen)
        if skill_num is None:
            # 进节点瞬间 UI 可能未渲染完，等待后重新截图再识别一次
            key_mouse_manager.sleep(0.6)
            skill_num = match_skill_numbers_in_region(self.parent.get_screen())
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