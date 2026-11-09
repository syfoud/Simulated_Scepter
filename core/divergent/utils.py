import time

import cv2 as cv
import numpy as np
import pyautogui

import core.divergent.keyops as keyops
import core.divergent.ocr as ocr
from core.any_fate.text_key import text_keys
from core.common.runtime import ScriptKernel
from core.divergent.config import config
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.mask import MASK, crop_region


class UniverseUtils(ScriptKernel):
    """差分宇宙共享基类：窗口、截图与文本点击复用通用内核，只保留差分玩法差异。"""

    def __init__(self):
        # 每次启动重新读配置，改过设置不需要重启程序
        config.read()
        super().__init__()
        self.diffi = config.diffi
        self.my_fate = -1
        self.fail_count = 0
        self.stop_move = 0
        self.slow = 0
        self.allow_e = 1
        self.quan = 0
        # 祝福文本表暂时沿用命途内核的数据，后续会替换为差分宇宙专用版本
        self.tk = text_keys(self.my_fate)
        # 祝福匹配需要一个「本命途」名字；差分宇宙不做命途选择，沿用默认下标
        self.fate = self.tk.fates[self.my_fate]
        self.debug = 0
        self.lst_mask = None
        self.event_mask = None

    def create_ts(self):
        """差分宇宙使用自己配置的识别精度，不复用通用内核的 OCR 实例。"""
        return ocr.My_TS(father=self)

    def press(self, c, t=0):
        if c not in ("role_3", "quest_item"):
            CUS_LOGGER.debug(f"按下按钮 {c}，等待 {t} 秒后释放")
        if c == 'technique' and self.allow_e == 0:
            return
        if self.slow and c == 'sprint':
            return
        if self._stop == 0:
            keyops.keyDown(c)
        else:
            raise ValueError("正在退出")
        time.sleep(t)
        keyops.keyUp(c)

    def click_point(self, x, y, box=None):
        """按 1920x1080 像素坐标点击，并等点击真正生效后才返回。

        差分宇宙的流程普遍是「点完立刻截屏判断结果」，而键鼠管理器是队列异步执行的，
        所以这里必须等队列排空，否则会读到点击前的旧画面。
        """
        if self._stop != 0:
            raise ValueError("正在退出")
        key_mouse_manager.click_point(x, y, box=box)
        key_mouse_manager.wait()
        time.sleep(0.3)

    def click_box(self, box):
        """点击坐标框 [x1, y1, x2, y2] 的中心。"""
        self.click_point((box[0] + box[2]) // 2, (box[1] + box[3]) // 2, box=box)

    def click_position(self, position, box=None):
        """按 1920x1080 像素坐标 [x, y] 点击。"""
        self.click_point(position[0], position[1], box=box)

    # 由click_target调用，返回图片匹配结果
    def scan_screenshot(self, prepared, mask=None, refine_mask=None, use_binary=False):
        temp = pyautogui.screenshot()
        screenshot = np.array(temp)
        screenshot = cv.cvtColor(screenshot, cv.COLOR_BGR2RGB)
        if use_binary:
            if len(screenshot.shape) == 3:
                gray_screenshot = cv.cvtColor(screenshot, cv.COLOR_RGB2GRAY)
            else:
                gray_screenshot = screenshot

            if len(prepared.shape) == 3:
                gray_prepared = cv.cvtColor(prepared, cv.COLOR_RGB2GRAY)
            else:
                gray_prepared = prepared

            _, binary_screenshot = cv.threshold(gray_screenshot, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            _, binary_prepared = cv.threshold(gray_prepared, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            if mask is not None:
                result = cv.matchTemplate(binary_screenshot, binary_prepared, cv.TM_CCOEFF_NORMED, mask=mask)
            else:
                result = cv.matchTemplate(binary_screenshot, binary_prepared, cv.TM_CCOEFF_NORMED)
        else:
            if mask is not None:
                result = cv.matchTemplate(screenshot, prepared, cv.TM_CCOEFF_NORMED, mask=mask)
            else:
                result = cv.matchTemplate(screenshot, prepared, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)

        # 如果提供了refine_mask，则在最佳匹配点位置使用refine_mask进行更精确的匹配度计算
        if refine_mask is not None:
            # 获取最佳匹配点位置
            best_x, best_y = max_loc[0], max_loc[1]

            if refine_mask.shape[:2] == prepared.shape[:2]:
                if (best_y + prepared.shape[0] <= screenshot.shape[0] and
                    best_x + prepared.shape[1] <= screenshot.shape[1]):
                    region = screenshot[best_y:best_y+prepared.shape[0], best_x:best_x+prepared.shape[1]]

                    refined_result = cv.matchTemplate(region, prepared, cv.TM_CCOEFF_NORMED, mask=refine_mask)
                    refined_min_val, refined_max_val, _, _ = cv.minMaxLoc(refined_result)

                    # 显示叠加后的效果
                    if hasattr(self, 'debug') and self.debug:
                        # 应用掩码到区域
                        masked_region = cv.bitwise_and(region, region, mask=refine_mask)
                        # 创建一个合并显示的图像
                        display_img = np.hstack((masked_region, prepared))
                        cv.imshow("Match Region and Template (Masked)", display_img)
                        cv.waitKey(0)

                    # 使用更精确的匹配度
                    max_val = refined_max_val

        return {
            "screenshot": screenshot,
            "min_val": min_val,
            "max_val": max_val,
            "min_loc": min_loc,
            "max_loc": max_loc,
        }

    def format_path(self, path):
        return f"resource/imgs/{path}.jpg"

    def click_img(self, path, threshold=0.95):
        path = self.format_path(path)
        target = cv.imread(path)
        result = cv.matchTemplate(self.screen, target, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        if max_val > threshold:
            x, y = max_loc
            # 全屏匹配的坐标就是绝对坐标，匹配框由匹配位置和模板尺寸组成
            self.click_position(
                (x + target.shape[1]//2, y + target.shape[0]//2),
                box=[int(x), int(y), int(x + target.shape[1]), int(y + target.shape[0])]
            )
            return 1
        return 0

    def check_box(self, path, box=[0, 0, 1920, 1080], threshold=0.96):
        path = self.format_path(path)
        target = cv.imread(path)
        local_screen = self.screen[box[1]:box[3], box[0]:box[2]]
        result = cv.matchTemplate(local_screen, target, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        self.tx, self.ty = (max_loc[0]+box[0], max_loc[1]+box[1])
        if max_val > threshold:
            if self.last_info != path:
                CUS_LOGGER.info(f"匹配到图片 {path} 相似度 {max_val} 阈值 {threshold}")
            self.last_info = path
        return max_val > threshold


    def check_f(self, is_in=[], check_text=1):
        if self.check("interact", mask=MASK["interact_icon"], threshold=0.95):
            if not check_text:
                return 1
            text = self.ts.ocr_one_row(self.screen, [1206, 587, 1437, 635])
            CUS_LOGGER.debug(f"text: {text}")
            if len(text):
                CUS_LOGGER.info('识别到交互信息：' + text)
                for i in is_in:
                    if i in text:
                        return 1
            return 0
        else:
            return None


    # 视角转动 degrees 度（正数向右），同步等待转动生效
    def turn(self, degrees, fine=1):
        if self.stop_move:
            # 地图寻路期间不允许动视角；仍保留一点等待，避免调用方变成忙循环
            time.sleep(0.05 * fine)
            return
        if self._stop != 0:
            raise ValueError("正在退出")
        key_mouse_manager.turn(degrees, fine)
        key_mouse_manager.wait()

    def get_text_position(self, clean=0):
        if self.event_mask is None:
            self.event_mask = (cv.imread('resource/imgs/divergent/event_mask.jpg', cv.IMREAD_GRAYSCALE) > 70)[:497]
            self.event_mask_clean = (cv.imread('resource/imgs/divergent/event_mask_clean.jpg', cv.IMREAD_GRAYSCALE) > 70)[:497]
        scr = self.screen[:497]
        mask = np.zeros((497, scr.shape[1]), dtype=np.uint8)
        mask_zero = np.zeros((497, scr.shape[1]), dtype=np.uint8)
        mask[((scr.max(axis=-1)-scr.min(axis=-1)) < 3)&(scr.max(axis=-1)>247)] = 255
        mask_zero[((scr.max(axis=-1)-scr.min(axis=-1)) < 3)&(scr.max(axis=-1)<21)] = 255
        kernel = np.ones((10, 30), np.uint8)
        mask_zero = cv.dilate(mask_zero, kernel, iterations=1)
        mask &= mask_zero
        if clean:
            mask[self.event_mask_clean] = 0
        else:
            mask[self.event_mask] = 0
        if clean == 0 and self.lst_mask is not None:
            mask[self.lst_mask] = 0
        self.lst_mask = mask
        kernel = np.ones((8, 55), np.uint8)
        mask = cv.dilate(mask, kernel, iterations=1)
        kernel = np.ones((6, 40), np.uint8)
        mask = cv.erode(mask, kernel, iterations=2)
        contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        mx_area, mx_cnt = 0, None
        for cnt in contours:
            x, y, w, h = cv.boundingRect(cnt)
            # print(w,h)
            if h > 22:
                continue
            if mx_area < w * h:
                mx_area = w * h
                mx_cnt = cnt
        res = []
        if mx_area < 4:
            return res
        xx, yy, ww, hh = cv.boundingRect(mx_cnt)
        for cnt in contours:
            x, y, w, h = cv.boundingRect(cnt)
            if w * h >= 4 and abs(y - yy) < 20:
                res.append((x+w//2,y+h//2))
        res = sorted(res, key=lambda x: x[0])
        if len(res) == 2 and res[1][0]-res[0][0] < 150:
            res = [((res[0][0]+res[1][0])//2,res[0][1])]
        return res
