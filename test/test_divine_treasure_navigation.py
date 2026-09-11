"""寻路状态机的离线回放测试：不需要游戏，只验证"不卡死"与动作序列。"""

import unittest

from tool.divine_treasure.navigation import NavObservation, run_battle_region


class FakeIO:
    def __init__(self, frames=(), step=0.0):
        self.frames = list(frames)
        self.actions = []
        self.t = 0.0
        self.step = step

    def capture(self):
        self.t += self.step
        return self.frames.pop(0) if self.frames else {}

    def forward(self, seconds):
        self.actions.append(("forward", seconds))

    def attack(self):
        self.actions.append(("attack",))

    def interact(self):
        self.actions.append(("interact",))

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.actions.append(("sleep", seconds))


def detector_for(obs):
    def detect(_frame):
        return obs
    return detect


def replay(*observations):
    """按帧回放观察结果；帧用尽后保持最后一帧，模拟持久的画面状态。"""
    queue = list(observations)
    last = queue[-1]

    def detect(_frame):
        return queue.pop(0) if queue else last
    return detect


MARKER = NavObservation(enemy_marker=(816, 59))          # 顶部 Z 图标：附近有怪
CLOSE = NavObservation(enemy_marker=(816, 59), enemy_close=True)  # 红点：已到攻击距离
WORLD = NavObservation()                                  # 大世界，无敌无门


class BattleRegionTests(unittest.TestCase):
    def test_no_marker_keeps_walking_forward(self):
        # 主人实测：角色初始朝向怪物，没看到 Z 图标就一直往前走。
        io = FakeIO(step=0.5)
        result = run_battle_region(io, detector_for(WORLD), budget=3.0)
        self.assertEqual("timeout", result.status)
        self.assertTrue(any(a[0] == "forward" for a in io.actions))
        self.assertNotIn(("attack",), io.actions)

    def test_marker_without_close_marker_keeps_stepping(self):
        io = FakeIO(step=0.5)
        run_battle_region(io, detector_for(MARKER), budget=3.0)
        self.assertTrue(any(a[0] == "forward" for a in io.actions))
        self.assertNotIn(("attack",), io.actions)   # 没红点不空挥

    def test_close_marker_triggers_attack(self):
        io = FakeIO(step=0.5)
        run_battle_region(io, detector_for(CLOSE), budget=3.0)
        self.assertIn(("attack",), io.actions)

    def test_attack_settle_two_seconds(self):
        io = FakeIO(step=0.5)
        run_battle_region(io, detector_for(CLOSE), budget=3.0)
        self.assertIn(("sleep", 2.0), io.actions)   # 等普攻后摇

    def test_hit_is_confirmed_when_marker_disappears(self):
        io = FakeIO(step=0.5)
        result = run_battle_region(
            io, replay(CLOSE, WORLD, WORLD, NavObservation(door=(800, 500))), budget=100.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_empty_swing_steps_closer_and_retries(self):
        # 平A后 2 秒 Z 图标仍在 = 空挥 → 碎步靠近再试
        io = FakeIO(step=0.5)
        run_battle_region(io, replay(CLOSE, CLOSE, CLOSE, CLOSE), budget=100.0)
        attacks = [a for a in io.actions if a[0] == "attack"]
        self.assertGreaterEqual(len(attacks), 2)

    def test_endless_empty_swings_give_up(self):
        io = FakeIO(step=0.2)
        result = run_battle_region(io, detector_for(CLOSE), budget=1e9)
        self.assertEqual("timeout", result.status)   # 到上限就放弃，不无限空挥

    def test_cleared_region_goes_straight_to_the_door(self):
        io = FakeIO(step=0.5)
        result = run_battle_region(io, detector_for(NavObservation(door=(800, 500))),
                                   cleared=True, budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)
        self.assertNotIn(("attack",), io.actions)

    def test_tick_budget_bounds_every_loop(self):
        io = FakeIO()
        result = run_battle_region(io, detector_for(WORLD), budget=1e9, max_ticks=7)
        self.assertLessEqual(result.ticks, 7)


if __name__ == "__main__":
    unittest.main()
