import os

import cv2 as cv

from route import PATHS
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.utils.ocr_num import match_skill_numbers_in_region


class SilverWolfManager:
    """银狼秘技：在触发区域内自动释放二号位银狼秘技。"""

    _ROLE_MAP = {"一号位": 1, "二号位": 2, "三号位": 3, "四号位": 4}

    def __init__(self, parent):
        self.parent = parent
        self.locked = False

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

    def _is_pig_node(self):
        """当前节点是否为祝福扑满。"""
        start_node = getattr(self.parent, 'start_nodes', None)
        if start_node is None:
            return False
        corner_marker = (start_node.get('orig') or {}).get('corner_marker')
        return bool(corner_marker) and corner_marker.get('name') in ('pig1', 'pig2')

    def _switch_to_pig_role(self):
        """扑满节点秘技点不足时切到子选项指定位置。"""
        switch_text = self.parent.opt.get("silver_wolf_switch", "三号位")
        target = self._ROLE_MAP.get(switch_text, 3)
        CUS_LOGGER.debug(f"银狼秘技：按设置切至{switch_text}（键位 {target}）")
        self.parent.switch_current_role(target)
        self.locked = False

    def activate(self):
        """尝试释放银狼秘技。..."""
        if self.parent.need_end:
            return False
        if not self.parent.opt.get("silver_wolf_enable", False):
            return False
        in_trigger = any(kw in self.parent.area for kw in ("精英", "奖励", "事件", "首领"))
        in_pig = self._is_pig_node()
        if not (in_trigger or in_pig):
            return False
        # 精英即使带扑满角标也按普通触发区域处理
        pig_only = in_pig and "精英" not in self.parent.area

        skill_num = match_skill_numbers_in_region(self.parent.get_screen())

        if skill_num is None:
            # 首次识别失败通常是 UI 未渲染完，等待后重试一次
            key_mouse_manager.sleep(0.3)
            skill_num = match_skill_numbers_in_region(self.parent.get_screen())

        if skill_num is None:
            CUS_LOGGER.warning("剩余秘技点识别失败")
            if pig_only:
                self._switch_to_pig_role()
                return True
            return False

        CUS_LOGGER.debug(f"银狼秘技：剩余秘技点={skill_num}")
        if skill_num < 1:
            if pig_only:
                CUS_LOGGER.debug("银狼秘技：仅扑满节点且秘技点为 0，切换抓猪角色")
                self._switch_to_pig_role()
                return True
            CUS_LOGGER.debug("银狼秘技：秘技点为 0，切回一号位")
            self.parent.switch_current_role(1)
            self.locked = False
            return True

        if not self._check_character("silverwolf", 0.9385, 0.3833, threshold=0.85, fresh=True):
            CUS_LOGGER.debug("银狼秘技：二号位不是银狼，跳过")
            return False
        self.parent.switch_current_role(2)
        self.parent.quan = 0
        self.parent.bai_e = 0
        self.locked = True
        key_mouse_manager.sleep(0.05)
        if self._check_character("bean", 0.8464, 0.3787, threshold=0.7, fresh=True):
            CUS_LOGGER.debug("银狼秘技图标已存在，跳过释放")
            return True
        CUS_LOGGER.info("释放银狼秘技")
        key_mouse_manager.press("e")
        key_mouse_manager.wait()
        return True

    def reset_lock(self):
        """节点移动完成后解除银狼的锁定切换状态。"""
        self.locked = False