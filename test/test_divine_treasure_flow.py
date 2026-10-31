"""校验状态驱动主循环：分发、稳定帧、冷却与结束。"""

import unittest

from tool.divine_treasure.flow import FlowDone, run_flow


class FakeScreen:
    """按给定顺序吐状态；耗尽后重复最后一帧。"""

    def __init__(self, states):
        self.states = list(states)
        self.served = 0

    def capture(self):
        state = self.states[min(self.served, len(self.states) - 1)]
        self.served += 1
        return state

    def identify(self, image):
        return {"state": image}

    def exhausted(self):
        return self.served > len(self.states)


class TestRunFlow(unittest.TestCase):
    def drive(self, states, handlers, **kwargs):
        screen = FakeScreen(states)
        kwargs.setdefault("idle", 0)
        kwargs.setdefault("cooldown", 0)
        try:
            run_flow(screen.capture, screen.identify, handlers,
                     should_stop=screen.exhausted, **kwargs)
        except (FlowDone, InterruptedError):
            pass
        return screen

    def test_unknown_state_times_out(self):
        with self.assertRaises(TimeoutError):
            self.drive(["unknown"] * 500, {}, idle=0.001, unknown_timeout=0.001)

    def test_single_frame_does_not_act(self):
        calls = []
        self.drive(["home", "unknown"], {"home": lambda snapshot: calls.append(1)},
                   idle=0.001, unknown_timeout=10)
        self.assertEqual(calls, [], "只出现一帧不算稳定，不应动作")

    def test_stable_frames_trigger_handler(self):
        calls = []
        self.drive(["home"] * 3, {"home": lambda snapshot: calls.append(1)}, retry_limit=99)
        self.assertTrue(calls)

    def test_cooldown_blocks_repeat_click(self):
        calls = []
        self.drive(["home"] * 8, {"home": lambda snapshot: calls.append(1)}, cooldown=999)
        self.assertEqual(len(calls), 1, "冷却期内同一界面不应重复点击")

    def test_flow_done_stops_immediately(self):
        calls = []

        def finish(snapshot):
            raise FlowDone()

        handlers = {"home": lambda snapshot: calls.append("home"), "masks": finish}
        self.drive(["home", "home", "masks", "masks", "home"], handlers)
        self.assertEqual(calls, ["home"])

    def test_repeat_without_change_raises(self):
        calls = []
        with self.assertRaises(RuntimeError):
            self.drive(["home"] * 50, {"home": lambda snapshot: calls.append(1)}, retry_limit=2)
        self.assertEqual(len(calls), 2, "超过重试上限应停止而不是无限点击")


if __name__ == "__main__":
    unittest.main()
