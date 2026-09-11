"""差分宇宙战斗区域寻路：每轮先观察再行动，任何失败都退出而不挂住。"""

import time
from dataclasses import dataclass

from tool.log import CUS_LOGGER


@dataclass(frozen=True)
class NavObservation:
    """一帧观察结果；检测层与离线回放共用同一结构。"""

    enemy_marker: tuple | None = None   # 顶部敌标记屏幕坐标
    battle_hud: bool = False            # 战斗界面（底部橙色占比跌破阈值）
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


SEARCH_TURNS = 6          # 找不到敌标记时的转视角次数上限
FACE_TOLERANCE = 120      # 已对准的横向容差（1920 基准像素）
APPROACH_SECONDS = 0.6    # 每次靠近的时长
DEFAULT_BUDGET = 60.0


def run_battle_region(io, detect, budget=DEFAULT_BUDGET, max_ticks=600,
                      approach_seconds=APPROACH_SECONDS):
    """推进一个战斗区域：找怪 → 靠近 → 平A → 等战斗结束 → 祝福 → 找门。

    与旧开环实现的差别：不再盲走固定时长；每轮先取一帧观察，
    进战斗以"大世界 → 战斗界面"的跳变为准，budget/max_ticks 到期即返回。
    """
    deadline = io.now() + budget
    ticks = 0
    search_turns = 0
    state = "find_enemy"
    while ticks < max_ticks and io.now() < deadline:
        ticks += 1
        obs = detect(io.capture())
        if state == "find_enemy":
            if obs.enemy_marker is not None:
                state = "approach"
                continue
            if search_turns >= SEARCH_TURNS:
                # 无敌人：可能已清怪。有门就过门，没门则放弃本区域。
                if obs.door is not None:
                    state = "find_door"
                    continue
                CUS_LOGGER.info("战斗区域未发现敌人，放弃本区域")
                return RegionResult("timeout", ticks, state)
            io.turn(1 if search_turns % 2 == 0 else -1)
            search_turns += 1
        elif state == "approach":
            if obs.battle_hud:            # 大世界 → 战斗界面：攻击已命中
                state = "in_battle"
                continue
            if obs.enemy_marker is None:  # 标记丢失（走过头/被遮挡）
                state = "find_enemy"
                continue
            offset = obs.enemy_marker[0] - 960
            if abs(offset) > FACE_TOLERANCE:
                io.turn(1 if offset > 0 else -1)
            else:
                io.forward(approach_seconds)
                io.attack()
        elif state == "in_battle":
            if obs.blessing:              # 战斗结束进入祝福页（可能连续多轮）
                state = "blessing"
                continue
            if not obs.battle_hud:        # 已回到大世界：本轮无祝福或已选完
                state = "find_door"
                continue
            io.sleep(1.0)
        elif state == "blessing":
            if not obs.blessing:
                state = "find_door"
                continue
            io.sleep(0.5)                 # 祝福选择由上层界面流程处理，这里只等它结束
        elif state == "find_door":
            if obs.door is None:
                io.turn(1 if ticks % 2 == 0 else -1)
                continue
            io.interact()
            CUS_LOGGER.info("已与粉色随意门交互，等待区域切换")
            return RegionResult("done", ticks, state)
    return RegionResult("timeout", ticks, state)
