"""货币战争内核的通用基础：等待游戏窗口、截图与文本点击。

货币战争是纯 UI + 战斗的玩法，不需要大世界寻路，因此这里只保留窗口定位与
截图/点击能力；地图、寻路、命途等旧模拟宇宙的公共逻辑都不再需要。
"""

import ctypes
import time

import pythoncom
import win32com.client

from core.common.engine import StateKernel
from core.common.ocr import get_global_my_ts
from tool.GLOBAL import (
    factor,
    get_global_stop_flag,
    key_mouse_manager,
    set_global_stop_flag,
)
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.screenshot import Screen
from tool.utils.game_window import (
    BASE_HEIGHT,
    BASE_WIDTH,
    CLOUD_WINDOW_KIND,
    find_game_window,
    get_client_screen_rect,
    is_supported_resolution,
    set_game_foreground,
)
from tool.utils.get_win_rect import get_window_rect

# 等待游戏窗口出现的上限（秒）
WINDOW_WAIT_TIMEOUT = 300


def set_forground():
    """把游戏窗口切到前台。

    先向系统发送一次空按键，绕开 Windows 对后台进程抢焦点的限制；
    焦点相关调用失败时静默忽略，由窗口等待逻辑兜底。
    """
    try:
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys("")
        set_game_foreground()
    except Exception:
        pass


class CurrencyUtils(StateKernel):
    """货币战争共享基类：窗口定位、截图与文本点击。"""

    def __init__(self):
        super().__init__()
        self._stop = False
        self.fps_list = []
        self.last_get_screen_time = None
        self.ts = get_global_my_ts(father=self)
        self.sct = None
        self.xx, self.yy = BASE_WIDTH, BASE_HEIGHT
        self.x0 = self.y0 = self.x1 = self.y1 = 0
        self.scx = self.scy = 1.0
        self.wait_game_window()
        self.sct = Screen()

    def wait_game_window(self):
        """等待游戏窗口出现并记录客户区坐标，用户中断时把 _stop 置位。"""
        CUS_LOGGER.warning(
            "我会等待那一天的到来。一直等待下去。总有一天……会有人翻开这近乎「永恒」的一页……(等待游戏窗口)"
        )
        start_time = time.time()
        while not get_global_stop_flag():
            try:
                if self.get_xy():
                    return
            except TimeoutError:
                raise
            except Exception:
                CUS_LOGGER.warning("定位游戏窗口失败", exc_info=True)
            if time.time() - start_time > WINDOW_WAIT_TIMEOUT:
                raise TimeoutError(
                    f"等待游戏窗口超时({WINDOW_WAIT_TIMEOUT}秒)，请检查游戏是否启动"
                )
            time.sleep(0.3)
        CUS_LOGGER.debug("初始化被用户中断")
        set_global_stop_flag(False)
        self._stop = True

    def get_xy(self):
        """定位游戏窗口并计算客户区坐标；窗口不可用时返回 0。"""
        game_window = find_game_window(prefer_foreground=True)
        if game_window is None:
            time.sleep(0.3)
            return 0
        hwnd = game_window.hwnd
        self.xx = game_window.client_width
        self.yy = game_window.client_height
        if game_window.kind == CLOUD_WINDOW_KIND:
            self.x0, self.y0, self.x1, self.y1 = get_client_screen_rect(hwnd)
        else:
            self.x0, self.y0, self.x1, self.y1 = get_window_rect(hwnd)
        self.x0 = max(0, self.x1 - self.xx)
        self.y0 = max(0, self.y1 - self.yy)
        if game_window.kind != CLOUD_WINDOW_KIND and (
                (self.xx == 1920 or self.yy == 1080)
                and self.xx >= 1920
                and self.yy >= 1080
        ):
            # 带边框的 1920x1080 窗口：把客户区从窗口矩形里对中裁出来
            self.x0 += (self.xx - 1920) // 2
            self.y0 += (self.yy - 1080) // 2
            self.x1 -= (self.xx - 1920) // 2
            self.y1 -= (self.yy - 1080) // 2
            self.xx, self.yy = BASE_WIDTH, BASE_HEIGHT
        if not is_supported_resolution(game_window.kind, self.xx, self.yy):
            if game_window.kind == CLOUD_WINDOW_KIND:
                CUS_LOGGER.error(
                    f"云游戏窗口大小错误 {self.xx} {self.yy}，"
                    f"请将窗口调整到接近{BASE_WIDTH}*{BASE_HEIGHT}"
                )
            else:
                CUS_LOGGER.error(f"分辨率错误 {self.xx} {self.yy} 请设为1920*1080")
            time.sleep(0.3)
            return 0
        if game_window.kind == CLOUD_WINDOW_KIND:
            self.x1 = self.x0 + BASE_WIDTH
            self.y1 = self.y0 + BASE_HEIGHT
            self.xx, self.yy = BASE_WIDTH, BASE_HEIGHT
        self.scx = self.xx / BASE_WIDTH
        self.scy = self.yy / BASE_HEIGHT
        try:
            dpi_scale = ctypes.windll.user32.GetDpiForWindow(hwnd) / 96.0
        except Exception:
            CUS_LOGGER.warning("DPI获取失败")
            dpi_scale = 1.0
        CUS_LOGGER.debug("DPI: " + str(dpi_scale))
        CUS_LOGGER.info("当前演算世界: " + str(game_window.title))
        time.sleep(1)
        return 1

    def click_text(self, text, delay=0, box=None, after_delay=0, click=True,
                   find_all=False, warning=True, ocr_line=True,
                   need_fresh=True, allow_fail=False):
        """识别并点击（或仅查找）文本。

        Args:
            text: 目标文本；传列表时按列表顺序表示优先级，取优先级最高的一条命中。
            delay: 进入识别前等待的秒数。
            box: 限定 OCR 区域 [x1, y1, x2, y2]；给出时优先走单行识别。
            after_delay: 命中后等待的秒数。
            click: 是否真的点击，False 时只做识别。
            find_all: 是否返回全部命中（仅识别模式有效）。
            warning: 未命中时是否输出警告日志。
            ocr_line: 为 False 时走“整块文本快速判定”分支，只判定不点击。
            need_fresh: 是否重新截屏后再识别。
            allow_fail: 单行识别未命中时是否直接返回 False、不再回退到全文匹配。

        Returns:
            命中返回 True，未命中返回 False。
        """
        if delay:
            time.sleep(delay)
        if not ocr_line:
            ocr_text = self.ts.find_with_box(box=box, forward=need_fresh)
            ocr_text_merged = merge_text(ocr_text) if len(ocr_text) else ""
            targets = text if isinstance(text, list) else [text]
            if any(t in ocr_text_merged for t in targets):
                CUS_LOGGER.debug(f"找到{text}当前返回结果{ocr_text}")
                return True
            if warning:
                CUS_LOGGER.warning(f"{text}文本未找到(非单行)当前返回结果{ocr_text}")
        if need_fresh:
            img = self.get_screen()
        else:
            img = self.screen
        if box:
            match = self.ts.ocr_one_row(img, box)
            CUS_LOGGER.info(f"{factor}请求：{text}响应：{match}")
            targets = text if isinstance(text, list) else [text]
            if len(match) and any(t in match for t in targets):
                if click:
                    key_mouse_manager.click_point(
                        (box[0] + box[2]) // 2,
                        (box[1] + box[3]) // 2,
                        box=box
                    )
                if after_delay:
                    time.sleep(after_delay)
                return True
            if allow_fail:
                return False
        pt = self.ts.find_text(img, text, find_all)
        if pt is not None:
            if click:
                xs = [point[0] for point in pt]
                ys = [point[1] for point in pt]
                hit = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
                key_mouse_manager.click_point(
                    (hit[0] + hit[2]) / 2,
                    (hit[1] + hit[3]) / 2,
                    box=hit
                )
            if after_delay:
                time.sleep(after_delay)
            return True
        if warning:
            CUS_LOGGER.warning(f"{text}文本未找到")
        return False
