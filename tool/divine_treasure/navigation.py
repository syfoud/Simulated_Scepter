"""差分宇宙局内寻路状态机：每步先观察再行动，任何失败都退出而不挂住。"""

import time
from dataclasses import dataclass

from tool.log import CUS_LOGGER


@dataclass(frozen=True)
class NavObservation:
    """一帧观察结果；由检测器产出，实机与离线回放共用同一结构。"""

    enemy: tuple | None = None      # 屏幕坐标
    enemy_visible: bool = False     # 顶部敌标记（看不清具体位置时为 True）
    door: tuple | None = None
    battle_hud: bool = False
    stage_icon: bool = True


@dataclass(frozen=True)
class RegionResult:
    """一个区域的结束方式；timeout 表示放弃本区域，交由上层决定是否重进。"""

    status: str          # done | timeout | stopped
    ticks: int
    last_state: str


class NavIO:
    """输入输出边界；实机注入真实键鼠，测试注入可回放的帧队列。"""

    def capture(self):
        raise NotImplementedError

    def forward(self, seconds):
        raise NotImplementedError

    def turn(self, direction):
        raise NotImplementedError

    def attack(self):
        raise NotImplementedError

    def interact(self):
        raise NotImplementedError

    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


SEARCH_TURNS = 6          # 找不到敌人时的转视角次数上限
FACE_TOLERANCE = 120      # 屏幕中心 ±像素内视为已对准


def run_battle_region(io, detect, budget=45.0, approach_seconds=0.35, max_ticks=400):
    """推进一个战斗区域：找怪 → 靠近 → 平A → 等战斗结束 → 找门。

    与旧实现的关键差别：不再盲走固定时长、不再朝屏幕中央盲打，
    每轮先取一帧观察再决定；budget/max_ticks 到期即返回 timeout。
    """
    deadline = io.now() + budget
    ticks = 0
    search_turns = 0
    state = "find_enemy"
    while ticks < max_ticks and io.now() < deadline:
        ticks += 1
        obs = detect(io.capture())
        if obs.battle_hud or not obs.stage_icon:
            state = "in_battle"
            io.sleep(1.0)
            continue
        if state == "find_enemy":
            if obs.enemy is not None:
                state = "approach"
                continue
            if obs.door is not None:
                # 区域已清（门口可达）时直接过门，不再原地搜索
                state = "battle_finish"
                continue
            if obs.enemy_visible:
                # 顶部敌标记仍在，但具体位置未知：转视角继续找
                io.turn(1 if search_turns % 2 == 0 else -1)
                search_turns += 1
                continue
            if search_turns >= SEARCH_TURNS:
                CUS_LOGGER.info("战斗区域未发现敌人，放弃本区域")
                return RegionResult("timeout", ticks, state)
            io.turn(1 if search_turns % 2 == 0 else -1)
            search_turns += 1
        elif state == "approach":
            if obs.enemy is None:
                state = "find_enemy"
                continue
            offset = obs.enemy[0] - 960
            if abs(offset) > FACE_TOLERANCE:
                io.turn(1 if offset > 0 else -1)
            else:
                io.forward(approach_seconds)
                io.attack()
        elif state == "battle_finish":
            if obs.door is None:
                io.turn(1 if ticks % 2 == 0 else -1)
                continue
            io.interact()
            CUS_LOGGER.info("已与门交互，等待区域切换")
            return RegionResult("done", ticks, state)
        if state == "in_battle" and not obs.battle_hud and obs.stage_icon:
            state = "battle_finish"
    return RegionResult("timeout", ticks, state)
