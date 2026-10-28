"""结算流程（settle_university）的内核行为测试。

背景：一局模拟宇宙结束时，内核要在「来自黑塔的分析报告」结算界面上做三件事——记账、
点掉界面、切分下一局的录像。这三件事原先由动作脚本里连续三个动作完成，而事件本身没有节流：
标题比界面可点击早出现约 0.3~0.5 秒，首次点击有概率不生效，界面留在屏幕上，下一轮识别又
命中同一条事件，整段动作重跑一遍，同一局于是被记了两次账（kill_record.txt 里留下用时 1 秒、
开局期望 -5 的假记录，录像也被多切一段）。

现在三个动作收进 settle_university 一个方法，并用 state 做闸门：记账时把 state 置为
"restart"，闸门看到它就说明本局已结算过，只补一次点击。切入下一局后 state 会被其它流程改走
（回到大地图时 is_run 写 "run"，开局写 "exit"/"init"），所以下一局不会误判。动作脚本里的接线
由 test_settle_wiring.py 锁定。

这里锁定：闸门的三种分支（首次结算 / 已结算过只补点击 / 达次数上限后停在结算界面）、
state 的写入时机（记账时写、且在录像分支之外无条件写）、各模式的录像切分决策。
"""

import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from importing import load_img

# 内核在导入期就会读图像记忆切片，必须先预热图片缓存
load_img()

from core.any_fate import engine as any_fate_engine  # noqa: E402
from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402
from core.simulated import engine as simulated_engine  # noqa: E402
from core.simulated.engine import SimulatedUniverse  # noqa: E402

# 结算界面上点掉的落点（报告界面上的空白处，与 settle_university 同值）
SETTLE_CLICK = [900, 1000]

# do_action 支持的字典动作（见 core/common/engine.py:114-143）：主键决定走哪个分支，
# 分支内部还会读几个附加键；除这些以外的键会被静默忽略。
ACTION_KEYS = {
    "text": {"text", "box", "redundancy"},
    "photo": {"photo", "threshold"},
    "position": {"position"},
    "sleep": {"sleep"},
    "real_sleep": {"real_sleep"},
    "press": {"press", "time"},
    "drag": {"drag"},
    "scroll": {"scroll"},
    "set_state": {"set_state"},
}
# 普通模拟宇宙里「点击空白处继续」的六类界面
BLANK_CLICK_EVENTS = (
    "获得祝福",
    "获得奇物",
    "获得物品",
    "失去祝福",
    "失去奇物",
    "失去物品",
)
# 四个内核都由同一条结算流程驱动
KERNELS = (SimulatedUniverse, any_fate_engine.AnyFateUniverse, IronBloodUniverse, FingerSnap)


def make_engine(cls=SimulatedUniverse, state="exit"):
    """造一个只装了结算所需属性的假内核：object.__new__ 跳过 __init__ 的窗口与录像初始化。"""
    engine = object.__new__(cls)
    engine.state = state
    engine._stop = 0
    engine.calls = []
    engine.states = []
    engine.update_state = engine.states.append
    engine.click_position = lambda position: engine.calls.append(("click", list(position)))
    return engine


class SettleUniversityGateTest(unittest.TestCase):
    """闸门：state 为 restart 说明本局已结算过，只补一次点击，不再记账也不再切录像。"""

    def settle(self, cls=SimulatedUniverse, state="exit", stop_at_end=False):
        engine = make_engine(cls, state)
        calls = engine.calls

        def end_of_university(inner):
            calls.append(("end_of_university", None))
            if stop_at_end:
                inner._stop = 1

        with patch.object(cls, "end_of_university", end_of_university), \
                patch.object(cls, "restart_recording",
                             lambda inner: calls.append(("restart_recording", None))):
            engine.settle_university()
        return calls

    def test_first_settlement_accounts_clicks_and_cuts_recording(self):
        """首次结算按固定顺序：先记账（含子类写记录），再点掉界面，最后切分录像。"""
        self.assertEqual(
            self.settle(),
            [("end_of_university", None), ("click", SETTLE_CLICK), ("restart_recording", None)],
        )

    def test_every_kernel_settles_with_the_same_gate(self):
        """四个内核共用基类的结算流程，子类只在自己的钩子里追加动作。"""
        for cls in KERNELS:
            with self.subTest(kernel=cls.__name__):
                self.assertEqual(
                    self.settle(cls),
                    [("end_of_university", None), ("click", SETTLE_CLICK),
                     ("restart_recording", None)],
                )

    def test_settled_round_only_clicks_again(self):
        """结算界面没被点掉时下一轮会再次命中：只补点一次，不再记账、不再切录像。"""
        self.assertEqual(self.settle(state="restart"), [("click", SETTLE_CLICK)])

    def test_rounds_started_outside_the_report_screen_settle_fully(self):
        """开局流程写入的 exit/init/run，以及进程刚启动时的空状态，都必须走完整结算。"""
        for state in ("exit", "init", "run", None):
            with self.subTest(state=state):
                self.assertEqual(len(self.settle(state=state)), 3)

    def test_round_limit_keeps_the_report_screen(self):
        """达到次数上限时 stop() 已经关掉了键鼠：不再点击，界面留在屏幕上。"""
        self.assertEqual(self.settle(stop_at_end=True), [("end_of_university", None)])


class SettlementStateTest(unittest.TestCase):
    """state 的写入：记账完成时进入 restart，录像权限关掉也要写。"""

    def test_bookkeeping_marks_the_round_as_settled(self):
        engine = make_engine(state="exit")
        engine.update_count = lambda read=True: None
        engine.my_cnt = 0
        engine.nums = 0
        engine.check_bonus = 1
        engine.end = 0
        engine.count = 128
        engine.init_time = time.time()
        engine.update_floor = Mock()

        engine.end_of_university()

        self.assertEqual(engine.states, ["restart"])
        engine.update_floor.assert_called_once_with(1)
        self.assertEqual(engine.end, 0)

    def test_last_round_raises_the_stop_flag(self):
        """取消奖励次数用尽时置 self.end=1，让主流程在本次结算后停车。"""
        engine = make_engine(state="exit")
        engine.update_count = lambda read=True: None
        engine.my_cnt = 0
        engine.nums = 1
        engine.check_bonus = 0
        engine.end = 0
        engine.count = 128
        engine.init_time = time.time()
        engine.update_floor = Mock()

        engine.end_of_university()

        self.assertEqual(engine.end, 1)

    def test_settled_state_is_written_even_when_recording_is_off(self):
        """没有录制权限（例如高级模式未授权）时状态也必须离开结算态，否则闸门永远不关。"""
        engine = make_engine()
        engine.record = False
        engine.cut_video = False
        engine.bveerelbcpgyqan = False
        engine.YKItDYvq3FpnOYx = False
        engine.recorder = Mock()
        engine.count = 12

        engine.restart_recording()

        self.assertEqual(engine.states, ["restart"])
        engine.recorder.stop_recording.assert_not_called()
        engine.recorder.start_recording.assert_not_called()

    def test_recording_is_cut_between_rounds(self):
        """有权限时停止本局录像、等界面淡出、再以新的轮回次数开始录制。"""
        engine = make_engine()
        for name in ("record", "cut_video", "bveerelbcpgyqan", "YKItDYvq3FpnOYx"):
            setattr(engine, name, True)
        engine.recorder = Mock()
        engine.count = 7

        with patch.object(simulated_engine, "time", SimpleNamespace(sleep=lambda seconds: None)):
            engine.restart_recording()

        engine.recorder.stop_recording.assert_called_once_with()
        engine.recorder.start_recording.assert_called_once_with(8)
        self.assertEqual(engine.states, ["restart"])

    def test_any_fate_resets_per_run_flags(self):
        """跨轮回的标记必须逐轮清零：阮·梅其二决定下一轮是否裁剪录像。"""
        engine = make_engine(cls=any_fate_engine.AnyFateUniverse)
        engine.record = engine.cut_video = False
        engine.fail_match_count = 3
        engine.node_count = 4
        engine.now_area = ["区域"]
        engine.chaoyan_seen = True
        engine.ruanmei2 = True

        engine.restart_recording()

        self.assertEqual(engine.states, ["restart"])
        self.assertEqual(engine.fail_match_count, 0)
        self.assertEqual(engine.node_count, 0)
        self.assertEqual(engine.now_area, [])
        self.assertFalse(engine.chaoyan_seen)
        self.assertFalse(engine.ruanmei2)


class RoundRecordingTest(unittest.TestCase):
    """录像切分决策：各模式按自己的指标决定本局录像留不留。"""

    def make_iron_blood(self, kill_count, del_record_time=10, first_plane_weight=3.5):
        engine = make_engine(IronBloodUniverse)
        engine.recorder = Mock()
        engine.elapsed_time = 600
        engine.kill_count = kill_count
        engine.del_record_time = del_record_time
        engine.debug = False
        engine.opt = {}
        engine.first_plane_weight = first_plane_weight
        return engine

    def test_iron_blood_deletes_recordings_below_the_kill_limit(self):
        engine = self.make_iron_blood(kill_count=5)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(
            True, battle_count=5, elapsed_time=600, first_plane_weight=3.5,
        )

    def test_iron_blood_keeps_recordings_above_the_kill_limit(self):
        engine = self.make_iron_blood(kill_count=20)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(
            False, battle_count=20, elapsed_time=600, first_plane_weight=3.5,
        )

    def make_finger_snap(self, countdown, ruanmei2, del_record_time=10):
        engine = make_engine(FingerSnap)
        engine.recorder = Mock()
        engine.countdown = countdown
        engine.ruanmei2 = ruanmei2
        engine.del_record_time = del_record_time
        return engine

    def test_finger_snap_deletes_recordings_that_end_early(self):
        engine = self.make_finger_snap(countdown=5, ruanmei2=False)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(True)

    def test_finger_snap_keeps_recordings_that_ran_long_enough(self):
        engine = self.make_finger_snap(countdown=15, ruanmei2=False)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(False)

    def test_finger_snap_keeps_the_round_that_met_ruan_mei(self):
        """遇到「阮·梅（其二）」的一轮无论多短都保留，同时下一轮要能恢复正常裁剪。"""
        engine = self.make_finger_snap(countdown=5, ruanmei2=True)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
