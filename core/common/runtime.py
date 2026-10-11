"""通用内核的窗口、识别与 JSON 脚本运行入口。"""

import time
from datetime import datetime
from pathlib import Path
from threading import Lock

import cv2 as cv
import numpy as np

from core.common.engine import StateKernel
from core.common.ocr import get_global_my_ts
from route import PATHS
from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.screenshot import Screen
from tool.utils.game_window import (
    BASE_HEIGHT,
    BASE_WIDTH,
    get_client_screen_rect,
    get_foreground_game_window,
    is_supported_resolution,
    set_game_foreground,
)


class ScriptKernel(StateKernel):
    def __init__(self):
        super().__init__()
        self._stop = False
        self.sct = None
        self._screen_lock = Lock()
        self.screen = np.zeros((BASE_HEIGHT, BASE_WIDTH, 3), dtype=np.uint8)
        self.config = None
        self.xx, self.yy = BASE_WIDTH, BASE_HEIGHT
        self.scx = self.scy = 1.0
        self.threshold = 0.97
        self.last_info = ""
        self.fps_list = []
        self.last_get_screen_time = None
        self.ts = get_global_my_ts(father=self)
        set_game_foreground()
        deadline = time.monotonic() + 300
        while not get_global_stop_flag():
            window = get_foreground_game_window()
            if window is not None:
                if not is_supported_resolution(window.kind, window.client_width, window.client_height):
                    raise ValueError(
                        f"当前游戏窗口为 {window.client_width} × {window.client_height}，"
                        f"请调整到 {BASE_WIDTH} × {BASE_HEIGHT} 后重新运行。"
                    )
                self.x0, self.y0, _, _ = get_client_screen_rect(window.hwnd)
                self.x1, self.y1 = self.x0 + self.xx, self.y0 + self.yy
                self.full = self.x0 == 0 and self.y0 == 0
                self.sct = Screen(self.xx, self.yy)
                key_mouse_manager.set_config(None)
                key_mouse_manager.multi = key_mouse_manager.scale = 1.0
                key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy, self.full)
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("等待游戏窗口超过 300 秒，请启动游戏并将游戏窗口置于前台。")
            time.sleep(0.3)
        self._stop = True

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

    def click_text(self, text, click=True, find_all=False):
        box = self.ts.find_text(self.get_screen(), text, find_all)
        if box is None:
            return False
        if click:
            self.prepare_script()
            self.click_position(((box[0][0] + box[1][0]) / 2,
                                 (box[0][1] + box[2][1]) / 2))
            key_mouse_manager.wait()
        return True

    def save_screen(self, save_path=None, force=False, not_now=False):
        screen = self.screen if not_now else self.get_screen()
        folder = Path(save_path or PATHS["temp"])
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
