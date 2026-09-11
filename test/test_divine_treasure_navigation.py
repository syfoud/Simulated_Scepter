"""寻路状态机的离线回放测试：不需要游戏，只验证"不卡死"与动作序列。"""

import unittest

from tool.divine_treasure.navigation import NavObservation, run_battle_region


class FakeIO:
    def __init__(self, frames):
        self.frames = list(frames)
        self.actions = []
        self.t = 0.0

    def capture(self):
        return self.frames.pop(0) if self.frames else {}

    def forward(self, seconds):
        self.actions.append(("forward", seconds))

    def turn(self, direction):
        self.actions.append(("turn", direction))

    def attack(self):
        self.actions.append(("attack",))

    def interact(self):
        self.actions.append(("interact",))

    def now(self):
        return self.t

    def sleep(self, seconds):
        return None


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


class BattleRegionTests(unittest.TestCase):
    def test_marker_off_center_is_approached_by_turning(self):
        io = FakeIO([{"marker": (1400, 60)}])
        run_battle_region(io, detector_for(NavObservation(enemy_marker=(1400, 60))), budget=0.02)
        self.assertIn(("turn", 1), io.actions)

    def test_centered_marker_triggers_forward_and_attack(self):
        io = FakeIO([{"marker": (960, 60)}])
        run_battle_region(io, detector_for(NavObservation(enemy_marker=(960, 60))), budget=0.02)
        self.assertIn(("attack",), io.actions)
        self.assertTrue(any(a[0] == "forward" for a in io.actions))

    def test_battle_hud_appearing_means_combat_started(self):
        io = FakeIO([])
        result = run_battle_region(
            io, replay(NavObservation(enemy_marker=(960, 60)),
                       NavObservation(enemy_marker=(960, 60)),   # 先对准攻击一次
                       NavObservation(battle_hud=True),          # 界面跳变 = 已进战斗
                       NavObservation(), NavObservation(door=(800, 500))),
            budget=5.0)
        self.assertEqual("done", result.status)
        self.assertIn(("attack",), io.actions)

    def test_blessing_then_door_completes_region(self):
        io = FakeIO([])
        result = run_battle_region(
            io,
            replay(NavObservation(enemy_marker=(960, 60)), NavObservation(battle_hud=True),
                   NavObservation(blessing=True), NavObservation(),   # 选完祝福回到大世界
                   NavObservation(), NavObservation(door=(800, 500))),
            budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_cleared_region_goes_straight_to_the_door(self):
        io = FakeIO([{"door": (800, 500)}])
        result = run_battle_region(io, detector_for(NavObservation(door=(800, 500))), budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_missing_enemy_gives_up_instead_of_hanging(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation()), budget=1e9)
        self.assertEqual("timeout", result.status)
        self.assertLess(result.ticks, 20)

    def test_tick_budget_bounds_every_loop(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation(battle_hud=True)),
                                   budget=1e9, max_ticks=7)
        self.assertLessEqual(result.ticks, 7)


if __name__ == "__main__":
    unittest.main()
