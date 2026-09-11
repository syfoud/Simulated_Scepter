"""战斗区域实机驱动：真实截图/键鼠 + 有界探针。"""

import time
from pathlib import Path

import cv2

from tool.divine_treasure.detect import battle_hud_visible, detect_door, enemy_marker
from tool.divine_treasure.navigation import NavIO, NavObservation, run_battle_region
from tool.log import CUS_LOGGER

MOVE_SECONDS_PER_PRESS = 0.8    # 一次 forward 的按键时长
HUD_OCR_EVERY = 3               # 战斗标签 OCR 每 3 轮一次，避免拖慢动作周期
FIXED_MARKER_STRIKES = 4        # 同一坐标连续不变的轮数上限，超过判为固定 UI


class LiveOcr:
    """把项目 OCR 接成 battle_hud_visible 需要的 (image, box) -> text。"""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        if self._engine is None:
            from tool.diver.ocr import My_TS

            self._engine = My_TS()
        return self._engine

    def read(self, image, box):
        text = self._get_engine().ocr_one_row(image, list(box))
        return text or ""


class LiveNavIO(NavIO):
    """实机输入。readonly 只观察；其余动作与主类同源（keyops 管键、key_mouse_manager 管鼠标）。"""

    def __init__(self, readonly=False, ocr=None, hud_ocr_every=HUD_OCR_EVERY):
        self.readonly = readonly
        self.ocr = ocr or LiveOcr()
        self.hud_ocr_every = hud_ocr_every
        self._round = 0
        self._last_hud = False
        self._last_marker = None
        self._same_marker = 0
        self.hwnd = None
        self.rect = None
        self._armed = False

    def capture(self):
        from divine_treasure_entry import capture_game

        image, self.hwnd, self.rect = capture_game()
        if not self._armed and self.rect:
            self._arm(self.rect)          # 必须在截图之后：键鼠坐标依赖真实窗口矩形
        return image

    def _arm(self, rect):
        """与 DivergentUniverse.__init__ 相同的键鼠初始化，否则操作只会烂在队列里。"""
        import pyautogui

        from tool.GLOBAL import key_mouse_manager
        from tool.diver.config import config as diver_config

        pyautogui.FAILSAFE = False
        key_mouse_manager.set_config(diver_config)
        key_mouse_manager.set_screen_params(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], False)
        key_mouse_manager.start()
        self._armed = True
        self._center = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        CUS_LOGGER.info(f"键鼠管理器已启动（窗口 {rect}，中心 {self._center}）")

    def _recenter(self):
        """把光标放回窗口中心。

        mouse_event 的相对移动会被屏幕边界截断：项目每次 click 前都会 SetCursorPos，
        而转向只做相对移动，不归位就会出现"转很多次视角不动"。
        """
        import win32api

        win32api.SetCursorPos(self._center)

    def _keys(self):
        import tool.diver.keyops as keyops

        return keyops

    def forward(self, seconds):
        if self.readonly:
            return
        keys = self._keys()
        keys.keyDown("w")
        time.sleep(min(seconds, MOVE_SECONDS_PER_PRESS))
        keys.keyUp("w")

    def turn(self, direction):
        if self.readonly:
            return
        from tool.GLOBAL import key_mouse_manager

        self._recenter()                               # 先归位，避免相对移动被屏幕边界截断
        key_mouse_manager.mouse_move(40 * direction)   # 一次只转一点，下一轮再看画面

    def attack(self):
        if self.readonly:
            return
        from tool.GLOBAL import key_mouse_manager

        key_mouse_manager.click(0.5, 0.5)              # 屏幕中央平A

    def interact(self):
        if self.readonly:
            return
        keys = self._keys()
        for _ in range(3):
            keys.keyDown("f")
            keys.keyUp("f")
            time.sleep(0.12)

    def detect(self, image):
        """一帧观察：敌标记随时可查，战斗标签按节流跑 OCR，门用颜色定位。"""
        self._round += 1
        if self._round % self.hud_ocr_every == 1:
            self._last_hud = battle_hud_visible(image, ocr=lambda img, box: self.ocr.read(img, box))
        marker = enemy_marker(image)
        return NavObservation(
            enemy_marker=self._stable_marker(marker),
            battle_hud=self._last_hud,
            door=detect_door(image),
        )

    def _stable_marker(self, marker):
        """过滤"永远不动"的固定 UI：真实的怪物标记会随视角移动。

        实机教训：转视角 12 次坐标仍是 (1247,45)，说明命中的是 HUD 固定元素，
        据此靠近/攻击只能靠蒙。同一坐标连续 FIXED_MARKER_STRIKES 轮不变即放弃。
        """
        if marker is None:
            self._same_marker = 0
            self._last_marker = None
            return None
        if self._last_marker is not None and max(
            abs(marker[0] - self._last_marker[0]), abs(marker[1] - self._last_marker[1])
        ) <= 2:
            self._same_marker += 1
        else:
            self._same_marker = 0
        self._last_marker = marker
        if self._same_marker >= FIXED_MARKER_STRIKES:
            CUS_LOGGER.debug(f"标记 {marker} 连续 {self._same_marker} 轮未随视角移动，按固定 UI 忽略")
            return None
        return marker

def _save(output, index, image, note):
    if output is None or image is None:
        return
    output.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(str(output / f"{index:03d}-{note}.png"))


def run_battle_probe(output, cleared=False, readonly=False, budget=240.0, max_rounds=200,
                     max_capture_failures=20):
    """有界实机探针：动作交给状态机，每轮留截图与判定日志。"""
    io = LiveNavIO(readonly=readonly)
    counter = {"round": 0, "failures": 0, "frame": None}

    def on_round(tick, obs):
        counter["round"] = tick
        CUS_LOGGER.info(f"第{tick}轮 marker={obs.enemy_marker} battle={obs.battle_hud} door={obs.door}")
        _save(output, tick, counter["frame"], "frame")

    def capture():
        try:
            frame = io.capture()
        except InterruptedError:
            raise
        except Exception as error:            # 失焦/几何变化：累计到上限就退出，不空转
            counter["failures"] += 1
            failures = counter["failures"]
            CUS_LOGGER.warning(f"截图失败 {failures}/{max_capture_failures}：{error}")
            if failures >= max_capture_failures:
                raise InterruptedError("游戏窗口长时间不可用") from error
            time.sleep(0.5)
            return None
        counter["failures"] = 0
        counter["frame"] = frame
        return frame

    def detect(image):
        if image is None:                     # 截图失败的一轮：不触发任何动作
            return NavObservation()
        return io.detect(image)

    try:
        result = run_battle_region(io, detect, cleared=cleared, budget=budget,
                                   max_ticks=max_rounds, on_round=on_round)
    except InterruptedError as error:
        CUS_LOGGER.warning(f"探针停止：{error}")
        return "stopped"
    except Exception as error:
        CUS_LOGGER.error(f"探针异常退出：{type(error).__name__}: {error}")
        return "stopped"
    CUS_LOGGER.info(f"探针结束：status={result.status} state={result.last_state} ticks={result.ticks}")
    return result.status
