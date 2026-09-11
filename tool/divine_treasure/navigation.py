"""差分宇宙战斗区域寻路：每轮先观察再行动，任何失败都退出而不挂住。"""

import time
from dataclasses import dataclass

from tool.log import CUS_LOGGER


@dataclass(frozen=True)
class NavObservation:
    """一帧观察结果；检测层与离线回放共用同一结构。"""

    enemy_marker: tuple | None = None   # 顶部敌标记屏幕坐标
    battle_hud: bool = False            # 战斗界面（底部橙色占比区间）
    blessing: bool = False              # 战后祝福选择页
    door: tuple | None = None           # 粉色随意门中心


@dataclass(frozen=True)
class RegionResult:
    """一个区域的结束方式；timeout 表示放弃本区域，交由上层决定是否重进。"""

    status: str          # done | timeout
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


SEARCH_TURNS = 3          # 找不到敌标记时的原地搜索上限
SEARCH_STEPS = 1          # 原地搜索无果后的前进次数上限（远处不渲染敌标记）
FACE_TOLERANCE = 120      # 已对准的横向容差（1920 基准像素）
APPROACH_SECONDS = 0.6    # 每次靠近的时长
SEARCH_SECONDS = 0.7      # 每次搜索前进的时长
DEFAULT_BUDGET = 90.0


def run_battle_region(io, detect, cleared=False, budget=DEFAULT_BUDGET, max_ticks=600,
                      approach_seconds=APPROACH_SECONDS):
    """推进一个战斗区域。

    cleared=False：本区域还没打过 → 找怪、靠近、平A，以"战斗界面跳变"确认进战斗；
    cleared=True ：已经打完（差分宇宙的怪都在一起，一次战斗搞定）→ 直接找粉色门。
    远处不渲染顶部敌标记，因此找不到标记时会前进搜索而不是原地转圈。
    全程由 budget 与 max_ticks 双上限兜底，到期返回 timeout。
    """
    deadline = io.now() + budget
    ticks = 0
    turn_count = 0
    step_count = 0
    engaged = cleared          # 是否已经打过本区域的战斗
    state = "find_door" if cleared else "find_enemy"

    def scan() -> None:
        """原地左右搜索；转过上限后改为前进，以便走到有标记的距离。"""
        nonlocal turn_count, step_count
        if turn_count < SEARCH_TURNS:
            io.turn(1 if turn_count % 2 == 0 else -1)
            turn_count += 1
            return True
        if step_count < SEARCH_STEPS:
            io.forward(SEARCH_SECONDS)
            step_count += 1
            turn_count = 0
            return True
        return False

    while ticks < max_ticks and io.now() < deadline:
        ticks += 1
        obs = detect(io.capture())

        if state == "find_enemy":
            if obs.enemy_marker is not None:
                state = "approach"
            elif not scan():
                CUS_LOGGER.info("搜索范围内未发现敌人，放弃本区域")
                return RegionResult("timeout", ticks, state)
        elif state == "approach":
            if obs.battle_hud:
                engaged = True
                state = "in_battle"
            elif obs.enemy_marker is None:
                state = "find_enemy"      # 标记丢失（走过头或被遮挡）
            else:
                offset = obs.enemy_marker[0] - 960
                if abs(offset) > FACE_TOLERANCE:
                    io.turn(1 if offset > 0 else -1)
                else:
                    io.forward(approach_seconds)
                    io.attack()
        elif state == "in_battle":
            if obs.blessing:
                state = "blessing"
            elif not obs.battle_hud:
                state = "find_door"
            else:
                io.sleep(1.0)
        elif state == "blessing":
            if not obs.blessing:
                state = "find_door"
            else:
                io.sleep(0.5)             # 祝福选择交给上层界面流程，这里只等它结束
        elif state == "find_door":
            if not engaged:
                CUS_LOGGER.info("战斗区域未发现敌人，放弃本区域")
                return RegionResult("timeout", ticks, state)
            if obs.door is None:
                io.turn(1 if ticks % 2 == 0 else -1)
            else:
                io.interact()
                CUS_LOGGER.info("已与粉色随意门交互，等待区域切换")
                return RegionResult("done", ticks, state)
    return RegionResult("timeout", ticks, state)
