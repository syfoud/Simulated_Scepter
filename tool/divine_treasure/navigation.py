"""差分宇宙战斗区域寻路：朝向前进找怪，红点确认贴近，平A后按标记消失判成败。"""

import time
from dataclasses import dataclass

from tool.log import CUS_LOGGER


@dataclass(frozen=True)
class NavObservation:
    """一帧观察结果；检测层与离线回放共用同一结构。"""

    enemy_marker: tuple | None = None   # 顶部 Z 图标（固定位置，只表示"附近有怪"）
    enemy_close: bool = False           # 怪物身上出现红点：已到攻击距离
    battle_hud: bool = False            # 战斗界面
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

    def attack(self):
        raise NotImplementedError

    def interact(self):
        raise NotImplementedError

    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


# 实测经验（主人）：角色初始朝向怪物，所以只需前进；远处不渲染 Z 图标。
SEEK_SECONDS = 1.0            # 找怪阶段一次前进的时长
COMBAT_STEP_SECONDS = 0.4     # 靠近怪物的单次碎步
ATTACK_SETTLE = 2.0           # 平A后等待后摇，再看 Z 图标是否消失
MAX_ATTACK_ROUNDS = 8         # 连续"碎步+平A"次数上限，防止原地空挥
DEFAULT_BUDGET = 300.0


def run_battle_region(io, detect, cleared=False, budget=DEFAULT_BUDGET, max_ticks=3000,
                      on_round=None):
    """推进一个战斗区域。

    cleared=False：找怪 → 靠近 → 平A → 等战斗结束 → 找门；
    cleared=True ：已经打完（怪都在一起，一次战斗搞定）→ 直接找门。

    判据来自实机结论：Z 图标固定在页面顶部，只表示"附近有怪"；
    红点出现在怪物身上才表示已进入攻击距离；平A 后 2 秒 Z 图标仍在即视为空挥。
    """
    deadline = io.now() + budget
    ticks = 0
    attack_rounds = 0
    state = "find_door" if cleared else "find_enemy"

    while ticks < max_ticks and io.now() < deadline:
        ticks += 1
        obs = detect(io.capture())
        if on_round is not None:
            on_round(ticks, obs)

        if state == "find_enemy":
            if obs.enemy_marker is not None:
                state = "approach"
            elif obs.door is not None:
                state = "find_door"           # 已经清怪且门前就是：不必再找怪
            else:
                io.forward(SEEK_SECONDS)      # 一直往前走，直到顶部出现 Z 图标
        elif state == "approach":
            if obs.enemy_marker is None:
                state = "find_enemy"          # 标记消失：走过头或被遮挡
            elif obs.enemy_close:             # 红点出现 = 进入攻击距离
                io.attack()
                state = "verify"
            else:
                io.forward(COMBAT_STEP_SECONDS)
        elif state == "verify":
            io.sleep(ATTACK_SETTLE)           # 等普攻后摇结束再看结果
            if obs.battle_hud or obs.enemy_marker is None:
                CUS_LOGGER.info("平A命中，进入战斗")
                attack_rounds = 0
                state = "battle"
            else:
                attack_rounds += 1
                if attack_rounds >= MAX_ATTACK_ROUNDS:
                    CUS_LOGGER.warning("连续空挥到上限，放弃本区域")
                    return RegionResult("timeout", ticks, state)
                CUS_LOGGER.info(f"平A落空（第{attack_rounds}次），碎步靠近再试")
                io.forward(COMBAT_STEP_SECONDS)
                state = "approach"
        elif state == "battle":
            if obs.enemy_marker is None and not obs.battle_hud:
                state = "after_battle"        # Z 图标消失且回到大世界：战斗结束
            else:
                io.sleep(1.0)
        elif state == "after_battle":
            if obs.blessing:
                state = "blessing"
            elif obs.door is not None:
                io.interact()
                CUS_LOGGER.info("已与粉色随意门交互，等待区域切换")
                return RegionResult("done", ticks, state)
            else:
                io.forward(COMBAT_STEP_SECONDS)
        elif state == "blessing":
            if not obs.blessing:
                state = "find_door"           # 祝福页关闭后继续找门
            else:
                io.sleep(0.5)                 # 祝福点击流程由上层界面逻辑处理
        elif state == "find_door":
            if obs.door is None:
                io.forward(COMBAT_STEP_SECONDS)
            else:
                io.interact()
                CUS_LOGGER.info("已与粉色随意门交互，等待区域切换")
                return RegionResult("done", ticks, state)
    return RegionResult("timeout", ticks, state)
