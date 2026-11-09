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

这里锁定：闸门的三种分支（首次结算 / 已结算过只补点击 / 达到运行次数后退出并停止）、
记账的 state 写入时机、以及各模式的录像切分决策。
"""

import time
import unittest
from unittest.mock import Mock, patch

from importing import load_img

# 内核在导入期就会读图像记忆切片，必须先预热图片缓存
load_img()

from core.any_fate import utils as any_fate_utils  # noqa: E402
from core.any_fate.engine import AnyFateUniverse  # noqa: E402
from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402

# 结算界面上点掉的落点（报告界面上的空白处，与 settle_university 同值）
SETTLE_CLICK = [900, 1000]

# 三条内核都由同一个 base 结算流程驱动；普通模拟宇宙入口已删除
KERNELS = (AnyFateUniverse, IronBloodUniverse, FingerSnap)


def make_engine(cls=AnyFateUniverse, state="exit"):
    """造一个只装了结算所需属性的假内核：object.__new__ 跳过 __init__ 的窗口与录像初始化。"""
    engine = object.__new__(cls)
    engine.state = state
    engine._stop = 0
    engine.calls = []
    engine.states = []
    engine.update_state = engine.states.append
    engine.click_position = lambda position: engine.calls.append(("click", list(position)))
    engine.max_run_time = 0
    engine.my_cnt = 0
    engine.keep_video_for_error = False
    engine.keep_round_video = False
    engine.stop = Mock()
    return engine


class SettleUniversityGateTest(unittest.TestCase):
    """闸门：state 为 restart 说明本局已结算过，只补一次点击，不再记账也不再切录像。"""

    def setUp(self):
        manager = self.enterContext(patch.object(any_fate_utils, "key_mouse_manager", Mock()))
        self.manager = manager

    def settle(self, cls=AnyFateUniverse, state="exit", reached_limit=False):
        engine = make_engine(cls, state)
        calls = engine.calls

        def end_of_university(inner):
            calls.append(("end_of_university", None))
            if reached_limit:
                inner.my_cnt = 1
                inner.max_run_time = 1

        with patch.object(cls, "end_of_university", end_of_university), \
                patch.object(cls, "restart_recording",
                             lambda inner: calls.append(("restart_recording", None))):
            engine.settle_university()
        return calls, engine

    def test_first_settlement_accounts_clicks_and_cuts_recording(self):
        """首次结算按固定顺序：先记账（含子类写记录），再点掉界面，最后切分录像。"""
        self.assertEqual(
            self.settle()[0],
            [("end_of_university", None), ("click", SETTLE_CLICK), ("restart_recording", None)],
        )

    def test_every_kernel_settles_with_the_same_gate(self):
        """所有内核共用基类的结算流程，子类只在自己的钩子里追加动作。"""
        for cls in KERNELS:
            with self.subTest(kernel=cls.__name__):
                self.assertEqual(
                    self.settle(cls)[0],
                    [("end_of_university", None), ("click", SETTLE_CLICK),
                     ("restart_recording", None)],
                )

    def test_settled_round_only_clicks_again(self):
        """结算界面没被点掉时下一轮会再次命中：只补点一次，不再记账、不再切录像。"""
        self.assertEqual(self.settle(state="restart")[0], [("click", SETTLE_CLICK)])

    def test_rounds_started_outside_the_report_screen_settle_fully(self):
        """开局流程写入的 exit/init/run，以及进程刚启动时的空状态，都必须走完整结算。"""
        for state in ("exit", "init", "run", None):
            with self.subTest(state=state):
                self.assertEqual(len(self.settle(state=state)[0]), 3)

    def test_run_limit_exits_instead_of_clicking_again(self):
        """达到设定的运行次数后退出并停止，不再点结算界面进入下一局。"""
        calls, engine = self.settle(reached_limit=True)

        self.assertEqual(calls, [("end_of_university", None)])
        self.manager.press.assert_called_once_with("esc")
        self.manager.wait.assert_called_once_with()
        engine.stop.assert_called_once_with()


class SettlementStateTest(unittest.TestCase):
    """记账的落点：state 必须进入 restart，且与录像权限无关。"""

    def test_bookkeeping_marks_the_round_as_settled(self):
        engine = make_engine(state="exit")
        engine.update_count = lambda read=True: None
        engine.my_cnt = 0
        engine.count = 128
        engine.init_time = time.time()

        any_fate_utils.FateUtils.end_of_university(engine)

        self.assertEqual(engine.states, ["restart"])
        self.assertEqual(engine.my_cnt, 1)
        self.assertEqual(engine.count, 128)

    def test_remaining_rounds_are_computed_from_the_run_limit(self):
        engine = make_engine(state="exit")
        engine.update_count = lambda read=True: None
        engine.max_run_time = 3
        engine.my_cnt = 0
        engine.count = 0
        engine.init_time = time.time()

        any_fate_utils.FateUtils.end_of_university(engine)

        self.assertEqual(engine.my_cnt, 1)
        self.assertEqual(engine.states, ["restart"])

    def test_settled_state_is_written_even_when_recording_is_off(self):
        """没有录制权限（例如高级模式未授权）时状态也必须离开结算态，否则闸门永远不关。"""
        engine = make_engine()
        engine.record = False
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
        for name in ("record", "bveerelbcpgyqan", "YKItDYvq3FpnOYx"):
            setattr(engine, name, True)
        engine.recorder = Mock()
        engine.count = 7

        with patch.object(any_fate_utils, "time", Mock(sleep=Mock())):
            engine.restart_recording()

        engine.recorder.stop_recording.assert_called_once_with(delete_video=False)
        engine.recorder.start_recording.assert_called_once_with(8)
        self.assertEqual(engine.states, ["restart"])

    def test_any_fate_resets_per_run_flags(self):
        """跨轮回的标记必须逐轮清零：阮·梅其二/超验之镜决定后续录像与战斗权重。"""
        engine = make_engine(cls=AnyFateUniverse)
        engine.record = False
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

    def test_any_fate_resets_run_state_on_settlement(self):
        """结算时清掉角色缓存并重建地图状态；暂离计数留到新一局开始时复位。"""
        engine = make_engine(cls=AnyFateUniverse)
        engine.update_count = lambda read=True: None
        engine.count = 0
        engine.init_time = time.time()
        engine.silver_wolf_manager = Mock(silver_wolf_slot="2")
        engine.fail_count = 7
        engine.init_map = Mock()

        engine.end_of_university()

        self.assertIsNone(engine.silver_wolf_manager.silver_wolf_slot)
        self.assertEqual(engine.fail_count, 7)
        engine.init_map.assert_called_once_with()

    def test_any_fate_resets_fail_count_when_the_next_round_starts(self):
        """新一局开始时同一张地图的暂离计数与录像保留标记一起归零。"""
        engine = make_engine(cls=AnyFateUniverse)
        engine.record = False
        engine.fail_count = 7
        engine.keep_round_video = True
        engine.node_count = 5
        engine.now_area = []

        engine.restart_recording()

        self.assertEqual(engine.fail_count, 0)
        self.assertFalse(engine.keep_round_video)
        self.assertEqual(engine.node_count, 0)


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
            delete_video=True, battle_count=5, elapsed_time=600, first_plane_weight=3.5,
        )

    def test_iron_blood_keeps_recordings_above_the_kill_limit(self):
        engine = self.make_iron_blood(kill_count=20)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(
            delete_video=False, battle_count=20, elapsed_time=600, first_plane_weight=3.5,
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

        engine.recorder.stop_recording.assert_called_once_with(delete_video=True)

    def test_finger_snap_keeps_recordings_that_ran_long_enough(self):
        engine = self.make_finger_snap(countdown=15, ruanmei2=False)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(delete_video=False)

    def test_finger_snap_keeps_the_round_that_met_ruan_mei(self):
        """遇到「阮·梅（其二）」的一轮无论多短都保留，同时下一轮要能恢复正常裁剪。"""
        engine = self.make_finger_snap(countdown=5, ruanmei2=True)

        engine.stop_round_recording()

        engine.recorder.stop_recording.assert_called_once_with(delete_video=False)


if __name__ == "__main__":
    unittest.main()
