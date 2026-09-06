import enum
import os
import re
import cv2 as cv

from route import PATHS
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text


class SilverWolfState(enum.IntEnum):
    """银狼秘技状态机"""
    IDLE = 0          # 未激活 / 已重置
    CASTED = 1        # 秘技已释放，等待进入战斗
    WAITING_CLEAR = 2 # 已进入战斗，等待区域弹窗清除后重放


TRIGGER_AREAS = ("精英", "事件", "奖励", "首领")
PIG_MARKERS = ("pig1", "pig2")
AREA_KEYWORDS = ("战斗", "精英", "事件", "冒险", "奖励", "休整", "交易", "首领", "空白", "虫群")


class SilverWolfManager:
    """银狼秘技管理器，封装所有银狼相关逻辑"""

    def __init__(self, parent):
        self.parent = parent
        self.state = SilverWolfState.IDLE

    # ---------- 派生属性 ----------
    @property
    def is_pig_node(self) -> bool:
        """当前节点是否为扑满（从 start_nodes 推导）"""
        node = getattr(self.parent, 'start_nodes', None)
        marker = ((node or {}).get('orig') or {}).get('corner_marker')
        return bool(marker) and marker.get('name') in PIG_MARKERS

    @property
    def block_role_switch(self) -> bool:
        """扑满节点内或银狼秘技生效期间禁止切回一号位"""
        return self.is_pig_node or self.state != SilverWolfState.IDLE
    def _check_character(self, template_name, x_ratio, y_ratio, threshold=0.7, fresh=False):
        """在固定比例坐标附近进行局部模板匹配"""
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
        half_w, half_h = tw, th
        x0 = max(0, px - half_w)
        y0 = max(0, py - half_h)
        x1 = min(w, px + half_w)
        y1 = min(h, py + half_h)
        if x1 - x0 < tw or y1 - y0 < th:
            return False
        roi = img[y0:y1, x0:x1]
        roi_gray = cv.cvtColor(roi, cv.COLOR_BGR2GRAY)
        res = cv.matchTemplate(roi_gray, tpl, cv.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv.minMaxLoc(res)
        return max_val >= threshold
    # ---------- 核心方法 ----------
    def try_activate(self) -> bool:
        """
        尝试激活银狼秘技。
        若状态为 IDLE 且检测到银狼，且当前区域为触发区域或扑满节点，则执行激活序列并返回 True。
        """
        if self.parent.need_end:
            return False
        if self.state != SilverWolfState.IDLE:
            return True
        if not (self.is_pig_node or any(kw in self.parent.area for kw in TRIGGER_AREAS)):
            return False
        if self._check_character("yinlang", 0.9378, 0.3801, threshold=0.8, fresh=True):
            self._activate()
            return True
        return False

    def process(self):
        """状态机主循环，需在每轮 normal() 中调用"""
        if self.parent.need_end:
            self.state = SilverWolfState.IDLE
            return

        if not (self.is_pig_node or any(kw in self.parent.area for kw in TRIGGER_AREAS)):
            if self.state != SilverWolfState.IDLE:
                CUS_LOGGER.debug("银狼：已离开触发区域，重置秘技状态")
                self.state = SilverWolfState.IDLE
            return

        if self.state == SilverWolfState.CASTED:
            if self.parent.state == "battle":
                CUS_LOGGER.debug("银狼：秘技已消耗")
                self.state = SilverWolfState.WAITING_CLEAR
        elif self.state == SilverWolfState.WAITING_CLEAR:
            ocr_text = self.parent.ts.find_with_box(
                box=[53, 104, 12, 42], forward=True, re_screen=True
            )
            text = merge_text(ocr_text) if len(ocr_text) else ""
            text = re.sub(r'[・·、]', '', text)
            if text and any(kw in text for kw in AREA_KEYWORDS):
                CUS_LOGGER.debug(f"银狼：弹窗已清除（区域: {text}），重新释放秘技")
                self._activate()

    # ---------- 私有方法 ----------
    def _activate(self):
        """执行激活序列：1 → 0.15s → 2 → 0.6s → E"""
        CUS_LOGGER.info("执行银狼秘技激活")
        key_mouse_manager.press("1")
        key_mouse_manager.sleep(0.05)  # 等待切换完成,删除会导致不执行后续切换
        key_mouse_manager.press("2")
        key_mouse_manager.sleep(0.05)   # 等待秘技可用,删除可能导致秘技释放无效
        key_mouse_manager.press('e')
        key_mouse_manager.wait()         # 等待所有操作完成
        self.state = SilverWolfState.CASTED
        CUS_LOGGER.debug("银狼秘技已激活")

    def reset(self):
        """重置状态（用于结束轮回、暂离等场景）"""
        self.state = SilverWolfState.IDLE