"""寻路状态机的离线回放测试：不需要游戏，只验证"不卡死"与动作序列。"""

import unittest

from tool.divine_treasure.navigation import NavObservation, run_battle_region


class FakeIO:
    def __init__(self, frames, clock=None):
        self.frames = list(frames)
        self.actions = []
        self.t = 0.0
        self.clock = clock

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
        if self.clock is None:
            return self.t
        return self.clock()

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
    def test_far_enemy_is_approached_from_a_distance(self):
        io = FakeIO([{"enemy": (1400, 500)}])
        result = run_battle_region(io, detector_for(NavObservation(enemy=(1400, 500))), budget=0.02)
        self.assertEqual("timeout", result.status)
        self.assertIn(("turn", 1), io.actions)

    def test_aligned_enemy_triggers_forward_and_attack(self):
        io = FakeIO([{"enemy": (960, 500)}])
        run_battle_region(io, detector_for(NavObservation(enemy=(960, 500))), budget=0.001)
        self.assertIn(("attack",), io.actions)
        self.assertTrue(any(action[0] == "forward" for action in io.actions))

    def test_missing_enemy_gives_up_instead_of_hanging(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation()), budget=0.001)
        self.assertEqual("timeout", result.status)
        self.assertLess(result.ticks, 400)

    def test_battle_hud_switches_to_waiting(self):
        io = FakeIO([{"battle_hud": True}])
        result = run_battle_region(io, detector_for(NavObservation(battle_hud=True)), budget=0.001)
        self.assertEqual("in_battle", result.last_state)

    def test_battle_end_then_door_is_interacted(self):
        frames = [{"battle_hud": True}, {"stage_icon": True, "door": (960, 600)}]
        io = FakeIO(frames)
        result = run_battle_region(
            io, replay(NavObservation(battle_hud=True), NavObservation(door=(960, 600))), budget=5.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_cleared_region_goes_straight_to_the_door(self):
        io = FakeIO([{"door": (960, 600)}])
        result = run_battle_region(
            io, detector_for(NavObservation(enemy_visible=True, door=(960, 600))), budget=5.0)
        self.assertEqual("done", result.status)
        self.assertIn(("interact",), io.actions)

    def test_tick_budget_bounds_every_loop(self):
        io = FakeIO([])
        result = run_battle_region(io, detector_for(NavObservation()), budget=1e9, max_ticks=7)
        self.assertLessEqual(result.ticks, 7)


if __name__ == "__main__":
    unittest.main()
