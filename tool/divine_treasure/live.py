"""战斗区域实机驱动：真实截图/键鼠 + 有界探针。"""

import time

import cv2
import numpy as np

from tool.divine_treasure.detect import (
    battle_hud_visible,
    detect_door,
    enemy_marker,
)
from tool.divine_treasure.navigation import NavIO, NavObservation, run_battle_region
from tool.log import CUS_LOGGER

MOVE_SECONDS_PER_PRESS = 0.8    # 一次 forward 的按键时长
HUD_OCR_EVERY = 3               # 战斗标签 OCR 每 3 轮一次，避免拖慢动作周期


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
    """实机输入：keyops 管键、key_mouse_manager 管鼠标。readonly 时只观察不输入。"""

    def __init__(self, readonly=False, ocr=None, hud_ocr_every=HUD_OCR_EVERY):
        self.readonly = readonly
        self.ocr = ocr or LiveOcr()
        self.hud_ocr_every = hud_ocr_every
        self._round = 0
        self._last_hud = False
        self.hwnd = None
        self.rect = None

    def capture(self):
        from divine_treasure_entry import capture_game
        image, self.hwnd, self.rect = capture_game()
        return image

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
        key_mouse_manager.mouse_move(40 * direction)   # 一次只转一点，下一轮再看画面

    def attack(self):
        if self.readonly:
            return
        from tool.GLOBAL import key_mouse_manager
        key_mouse_manager.click(0.5, 0.5)              # 屏幕中央平A

    def interact(self):
        if self.readonly:
            return
        for _ in range(3):
            self._keys().keyDown("f")
            self._keys().keyUp("f")
            time.sleep(0.12)

    def detect(self, image):
        """一帧观察：敌标记随时可查，战斗标签按节流跑 OCR，门用颜色定位。"""
        self._round += 1
        if self._round % self.hud_ocr_every == 1:
            self._last_hud = battle_hud_visible(image, ocr=lambda img, box: self.ocr.read(img, box))
        return NavObservation(
            enemy_marker=enemy_marker(image),
            battle_hud=self._last_hud,
            door=detect_door(image),
        )


def _save(output, index, image, note):
    if output is None:
        return
    output.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(str(output / f"{index:03d}-{note}.png"))


def run_battle_probe(output, cleared=False, readonly=False, budget=240.0, max_rounds=200):
    """有界实机探针：跑一个战斗区域就停，全程留证据。返回状态字符串。"""
    io = LiveNavIO(readonly=readonly)
    rounds = 0
    deadline = time.monotonic() + budget
    last_state = "?"
    last_obs = None
    while rounds < max_rounds and time.monotonic() < deadline:
        rounds += 1
        started = time.monotonic()
        image = io.capture()
        obs = io.detect(image)
        last_obs = obs
        elapsed = time.monotonic() - started
        CUS_LOGGER.info(
            f"第{rounds}轮 marker={obs.enemy_marker} battle={obs.battle_hud} door={obs.door} 耗时{elapsed:.2f}s"
        )
        _save(output, rounds, image, "frame")
        decision = _decide(obs, cleared, last_state)
        last_state = decision
        if decision == "done":
            return "done"
        if readonly:
            time.sleep(0.5)
        else:
            time.sleep(0.2)
    CUS_LOGGER.warning(f"探针结束：rounds={rounds} state={last_state} obs={last_obs}")
    return "stopped"


def _decide(obs, cleared, last_state):
    """探针内的轻量决策记录：只用于日志与判定"是否已到达门口"。"""
    if last_state == "find_door" and obs.door is not None:
        return "at_door"
    if obs.battle_hud:
        return "in_battle"
    if obs.enemy_marker is not None and not cleared:
        return "approach"
    return "find_door" if cleared else "find_enemy"