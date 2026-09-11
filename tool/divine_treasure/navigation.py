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


SEARCH_STEPS = 12         # 搜索前进的步数上限（仅用于统计）
SEARCH_TURN_STEP = 0.23   # 原地扫视每步约 30°
FACE_TOLERANCE = 120      # 已对准的横向容差（1920 基准像素）；转向用偏移/屏宽比例
MAX_AIM_TURNS = 12        # 同一目标连续微调上限，超过就上前打，避免原地转到超时
APPROACH_SECONDS = 0.6    # 每次靠近的时长
SEARCH_SECONDS = 0.7      # 每次搜索前进的时长
DEFAULT_BUDGET = 90.0


def run_battle_region(io, detect, cleared=False, budget=DEFAULT_BUDGET, max_ticks=600,
                      approach_seconds=APPROACH_SECONDS, on_round=None):
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
    aim_turns = 0            # 连续微调次数，超限直接上前攻击
    engaged = cleared          # 是否已经打过本区域的战斗
    state = "find_door" if cleared else "find_enemy"

    def scan() -> None:
        """丢失标记时的搜索：原地左右扫视（每步约 30°），扫满一圈再走近一点。

        实机教训：转向后标记会移出视野；若此时直走就会越走越偏（转 90° 后一路撞墙），
        所以搜索先原地扫视，确认没有目标才小幅前进。
        """
        nonlocal turn_count, step_count
        if step_count < SEARCH_STEPS:
            io.turn(0.23 if turn_count % 2 == 0 else -0.23)
            turn_count += 1
            if turn_count >= 2:
                turn_count = 0
                step_count += 1
            return
        io.forward(SEARCH_SECONDS)
        step_count = 0
        turn_count = 0

    while ticks < max_ticks and io.now() < deadline:
        ticks += 1
        obs = detect(io.capture())
        if on_round is not None:
            on_round(ticks, obs)

        if state == "find_enemy":
            if obs.enemy_marker is not None:
                state = "approach"
                aim_turns = 0
            else:
                scan()
        elif state == "approach":
            if obs.battle_hud:
                engaged = True
                state = "in_battle"
            elif obs.enemy_marker is None:
                state = "find_enemy"      # 标记丢失（走过头或被遮挡）
            else:
                offset = obs.enemy_marker[0] - 960
                if abs(offset) > FACE_TOLERANCE and aim_turns < MAX_AIM_TURNS:
                    aim_turns += 1
                    io.turn(offset / 960)   # 比例转向：偏得越多转得越多
                    CUS_LOGGER.info(f"对准中：偏移{offset}px，第{aim_turns}/{MAX_AIM_TURNS}次微调") 
                else:
                    if abs(offset) > FACE_TOLERANCE:
                        CUS_LOGGER.warning(f"微调{MAX_AIM_TURNS}次仍偏{offset}px，改为直接上前攻击") 
                    aim_turns = 0
                    io.forward(approach_seconds)
                    io.attack()
                    CUS_LOGGER.info("前进并平A") 
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
