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


CENTER_MARKER = NavObservation(enemy_marker=(960, 60))
WORLD = NavObservation()


class BattleRegionTests(unittest.TestCase):
    def test_far_enemy_is_searched_for_by_walking_forward(self):
        # 主人实测：离得远时顶部没有敌标记，必须边走边找，不能原地转圈。
        io = FakeIO([])
        run_battle_region(io, detector_for(WORLD), cleared=False, budget=0.001)
        self.assertTrue(any(a[0] == "forward" for a in io.actions), "远处找不到标记时应当前进搜索")
        self.assertIn(("turn", 1), io.actions)

    def test_marker_off_center_is_approached_by_turning(self):
        io = FakeIO([])
        run_battle_region(io, detector_for(NavObservation(enemy_marker=(1400, 60))),
                          cleared=False, budget=0.02)
        self.assertIn(("turn", 1), io.actions)

    def test_centered_marker_triggers_forward_and_attack(self):
        io = FakeIO([])
        run_battle_region(io, detector_for(CENTER_MARKER), cleared=False, budget=0.02)
        self.assertIn(("attack",), io.actions)
        self.assertTrue(any(a[0] == "forward" for a in io.actions))

    def test_battle_hud_appearing_means_combat_started(self):
        io = FakeIO([])
        result = run_battle_region(
            io, replay(CENTER_MARKER, CENTER_MARKER, NavObservation(battle_hud=True),
                       WORLD, NavObservation(door=(800, 500))),
            cleared=False, budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("attack",), io.actions)
        self.assertIn(("interact",), io.actions)

    def test_blessing_then_door_completes_region(self):
        io = FakeIO([])
        result = run_battle_region(
            io,
            replay(CENTER_MARKER, CENTER_MARKER, NavObservation(battle_hud=True),
                   NavObservation(blessing=True), WORLD, WORLD, NavObservation(door=(800, 500))),
            cleared=False, budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_cleared_region_goes_straight_to_the_door(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation(door=(800, 500))),
                                   cleared=True, budget=10.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)
        self.assertNotIn(("attack",), io.actions)

    def test_uncleared_region_without_enemy_gives_up(self):
        # 搜索上限用尽即主动放弃，不等 budget/max_ticks 兜底。
        io = FakeIO([])
        result = run_battle_region(io, detector_for(WORLD), cleared=False, budget=1e9)
        self.assertEqual("timeout", result.status)
        self.assertLessEqual(result.ticks, 12)

    def test_tick_budget_bounds_every_loop(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation(battle_hud=True)),
                                   cleared=True, budget=1e9, max_ticks=7)
        self.assertLessEqual(result.ticks, 7)


if __name__ == "__main__":
    unittest.main()
