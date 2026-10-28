"""结算时切分录像的决策测试。

一局模拟宇宙结束后各内核都要切分录像，是否保留本局录像由各模式自己决定：铁血按击杀数、
弹指按倒计时判断，遇到「阮·梅（其二）」的一轮无论多短都保留。这里锁定四种内核共用的
stop_round_recording 钩子在各模式下传给录像器的参数。
"""

import unittest
from unittest.mock import Mock

from importing import load_img

# 内核在导入期就会读图像记忆切片，必须先预热图片缓存
load_img()

from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402
from core.simulated.engine import SimulatedUniverse  # noqa: E402


def make_engine(cls=SimulatedUniverse, state="exit"):
    """造一个只装了录像切分所需属性的假内核：object.__new__ 跳过 __init__ 的窗口与录像初始化。"""
    engine = object.__new__(cls)
    engine.state = state
    engine._stop = 0
    return engine


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
