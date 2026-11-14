"""通用内核的窗口、识别与 JSON 脚本运行入口。"""

import ctypes
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

import cv2 as cv
import numpy as np
import pythoncom
import win32com.client

from core.common.engine import StateKernel
from core.common.ocr import get_global_my_ts
from route import PATHS
from tool import GLOBAL
from tool.calibration import get_multi
from tool.GLOBAL import factor, get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.mask import crop_region, quad_box, region_center_point
from tool.public_ocr import merge_text
from tool.screenshot import Screen
from tool.settings import load_settings
from tool.utils.game_window import (
    get_client_screen_rect,
    get_foreground_game_window,
    is_supported_resolution,
    set_game_foreground,
)


def set_forground():
    """把游戏窗口切到前台。

    先向系统发送一次空按键，绕开 Windows 对后台进程抢焦点的限制；
    焦点相关调用失败时静默忽略，由调用方后续的窗口等待逻辑兜底。
    """
    try:
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys("")
        set_game_foreground()
    except Exception:
        pass


def sprint():
    """切换疾跑状态（点按一次进入疾跑，再点按一次退出）。"""
    CUS_LOGGER.debug("「救世主，带领吾等前进吧。」")
    key_mouse_manager.press("sprint")


class ScriptKernel(StateKernel):
    # 等待游戏窗口出现的上限（秒）。测试场景由子类下调，正式运行保持 300。
    window_timeout = 300

    def __init__(self):
        super().__init__()
        # 全局调试模式来自用户配置（gui_settings.json 的 debug）：日志过滤与调试遮罩都按它开关。
        # 必须在这里就设置，等待游戏窗口期间也该按正确的调试模式运行。
        GLOBAL.DEBUG_MODE = bool(load_settings().get("debug", False))
        self._stop = False
        self.sct = None
        self._screen_lock = Lock()
        self.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.xx, self.yy = 1920, 1080
        self.scx = self.scy = 1.0
        self.fps_list = []
        self.last_get_screen_time = None
        # 游戏窗口句柄，供内核输出 DPI 等信息时复用
        self.hwnd = None
        # 转身倍率与 DPI 缩放：所有基于 ScriptKernel 的内核共用同一份机器级设置
        # 转身倍率由校准结果提供；DPI 只用于诊断输出，不参与转身距离换算。
        self.multi = 1.0
        self.scale = 1.0
        self.dpi_scale = 1.0
        self.ts = self.create_ts()
        # 先发一次空按键绕开 Windows 的后台抢焦点限制，再等窗口出现
        set_forground()
        deadline = time.monotonic() + self.window_timeout
        while not get_global_stop_flag():
            window = get_foreground_game_window()
            if window is not None:
                if not is_supported_resolution(window.kind, window.client_width, window.client_height):
                    raise ValueError(
                        f"当前游戏窗口为 {window.client_width} × {window.client_height}，"
                        f"请调整到 1920 × 1080 后重新运行。"
                    )
                self.x0, self.y0, _, _ = get_client_screen_rect(window.hwnd)
                self.hwnd = window.hwnd
                self.x1, self.y1 = self.x0 + self.xx, self.y0 + self.yy
                self.full = self.x0 == 0 and self.y0 == 0
                self.sct = Screen(self.xx, self.yy)
                self.multi = get_multi()
                self.dpi_scale = self._dpi_scale()
                key_mouse_manager.set_config(self)
                key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy)
                # 转身速度异常时据此判断是 DPI 还是校准值的问题
                CUS_LOGGER.debug(f"DPI: {self.dpi_scale} A: {int(self.multi * 100) / 100}")
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("等待游戏窗口超过 300 秒，请启动游戏并将游戏窗口置于前台。")
            time.sleep(0.3)
        self._stop = True

    def _dpi_scale(self):
        """当前窗口的 DPI 缩放比（96 DPI 为 1.0），仅用于诊断日志。"""
        try:
            return ctypes.windll.user32.GetDpiForWindow(self.hwnd) / 96.0
        except (AttributeError, OSError):
            CUS_LOGGER.warning("获取窗口 DPI 失败，按 100% 缩放处理")
            return 1.0

    def create_ts(self):
        """创建 OCR 识别器；内核需要使用自己的识别精度时覆盖本方法。"""
        return get_global_my_ts(father=self)

    def prepare_script(self):
        if self._stop or get_global_stop_flag():
            return
        super().prepare_script()

    def start(self, json_path=None):
        if json_path is not None:
            from tool.action_script import run_script
            return run_script(self, json_path)
        if not getattr(self, "default_json", None):
            raise ValueError("通用内核需要选择 JSON 动作脚本。")
        if self._stop or get_global_stop_flag():
            return
        try:
            self.prepare_script()
            while not self._stop and not get_global_stop_flag():
                self.ts.forward(self.get_screen())
                if self._stop or get_global_stop_flag():
                    break
                self.run_static()
        finally:
            if not self._stop:
                self.stop()

    def stop(self, *_, **__):
        self._stop = True
        try:
            key_mouse_manager.stop()
        finally:
            with self._screen_lock:
                if self.sct is not None:
                    self.sct.close()
                    self.sct = None

    def get_screen(self):
        with self._screen_lock:
            if self._stop:
                return self.screen
            return super().get_screen()

    def click_text(self, text, delay=0, box=None, after_delay=0, click=True,
                   find_all=False, warning=True, ocr_line=True,
                   need_fresh=True, allow_fail=False):
        """识别并点击（或仅查找）文本。

        Args:
            text: 目标文本；传列表时按列表顺序表示优先级，取优先级最高的一条命中。
            delay: 进入识别前等待的秒数。
            box: 限定 OCR 区域 [x1, y1, x2, y2]；给出时优先走单行识别。
            after_delay: 命中后等待的秒数。
            click: 是否真的点击，False 时只做识别。默认True。
            find_all: 是否返回全部命中（仅识别模式有效）。默认False。
            warning: 未命中时是否输出警告日志。默认True。
            ocr_line: 为 False 时先走“整块文本快速判定”；未命中仍会继续普通识别流程。默认True。
            need_fresh: 是否重新截屏后再识别。默认True。
            allow_fail: 单行识别未命中时是否直接返回 False、不再回退到全文匹配。默认False。

        Returns:
            命中返回 True，未命中返回 False。
        """
        if delay:
            time.sleep(delay)
        if not ocr_line:
            ocr_text = self.ts.find_with_box(box=box, re_screen=need_fresh)
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
            # 检查匹配结果是否包含目标文本
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
                key_mouse_manager.click_point(
                    (pt[0][0] + pt[1][0]) / 2,
                    (pt[0][1] + pt[2][1]) / 2,
                    box=quad_box(pt)
                )
            if after_delay:
                time.sleep(after_delay)
            return True
        if warning:
            CUS_LOGGER.warning(f"{text}文本未找到")
        return False

    def wait_until(self, predicate, timeout=3.0):
        """轮询直到回调返回真值。

        每轮重新截屏，供回调基于最新画面判断。

        Args:
            predicate: 条件回调；返回真值表示条件已满足，可以结束等待。
            timeout: 最长等待秒数。

        Returns:
            条件满足返回 True；超时或被停止返回 False。
        """
        end = time.time() + timeout
        while time.time() < end:
            if self._stop:
                return False
            if predicate():
                return True
            time.sleep(0.05)
            if self._stop:
                return False
            self.get_screen()
        return False

    def calc_point(self, point, offset):
        """把识别框或坐标加上偏移，得到实际点击点。

        point 为 4 元组时按区域中心计算，为 2 元组时视为点坐标。
        """
        if len(point) == 4:
            point = region_center_point(point)
        return point[0] + offset[0], point[1] + offset[1]

    def get_small_interaction_img(self, mask, fresh=False):
        """按掩膜裁出小地图交互区域。"""
        if fresh:
            self.get_screen()
        return crop_region(self.screen, mask)

    def save_screen(self, save_path=None, force=False, not_now=False):
        screen = self.screen if not_now else self.get_screen()
        folder = Path(save_path or os.path.join(PATHS["temp"], "screenshot"))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now():%Y%m%d_%H%M%S_%f}.png"
        if not cv.imwrite(str(path), screen):
            raise OSError(f"截图保存失败：{path}")
        if force:
            cv.imshow("save", screen)
            cv.waitKey(0)
        return screen


def create_engine(*, script=False):
    return ScriptKernel()
