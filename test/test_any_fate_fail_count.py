"""同一张地图的连续暂离计数：累计方式、复位时机与录像保留。"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse  # noqa: E402
from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402
from test.test_any_fate_away import AREA, make_engine  # noqa: E402


class FailCountTestBase(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.any_fate.engine.key_mouse_manager", self.manager))
        self.logger = Mock()
        self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", self.logger))

    def away(self, engine):
        engine.area = AREA
        engine.last_interact_time = 0.0
        self.assertEqual(engine.normal(), 1)


class SameMapCountingTest(FailCountTestBase):
    def test_same_map_timeouts_increment_and_do_not_end_the_run(self):
        """同一张地图连续暂离只累计次数，达到 3 次也不强制结束本局，而是保留录像。"""
        engine = make_engine()

        for expected in (1, 2, 3):
            self.away(engine)
            self.assertEqual(engine.fail_count, expected)
            self.assertFalse(engine.need_end)

        self.assertTrue(engine.keep_round_video)
        # 三次都是超时暂离，不存在提前结束的 exit 状态切换
        self.assertEqual([c.args for c in engine.update_state.call_args_list], [("ui",)] * 3)
        messages = [c.args[0] for c in self.logger.error.call_args_list]
        for expected in (1, 2, 3):
            self.assertTrue(any(
                f"当前第1位面，区域战斗，地图1，第{expected}次长时间无有效交互" in m
                for m in messages))

    def test_moving_to_the_next_map_restarts_the_counter(self):
        """换图后从 1 重新计数：离开当前地图的入口会先清零。"""
        engine = make_engine()
        engine.fail_count = 2

        engine.fail_count = 0
        self.away(engine)

        self.assertEqual(engine.fail_count, 1)

    def test_special_room_without_map_id_still_counts(self):
        """事件等特殊房间没有地图编号时也按同一张地图累计，直到换图/换位面。"""
        engine = make_engine()
        engine.now_map = -1

        self.away(engine)
        self.away(engine)
        self.assertEqual(engine.fail_count, 2)

        engine.fail_count = 0
        self.away(engine)
        self.assertEqual(engine.fail_count, 1)

    def test_need_end_does_not_increment_the_counter(self):
        engine = make_engine(last_interact_time=1000.5, need_end=True)

        self.assertEqual(engine.normal(), 1)

        self.assertEqual(engine.fail_count, 0)
        self.assertFalse(engine.keep_round_video)


class ResetTriggerTest(FailCountTestBase):

    def test_entering_new_plane_resets_the_counter(self):
        engine = make_engine()
        engine.fail_count = 2
        engine.try_analysis_map = Mock()

        engine.initing_map()

        self.assertEqual(engine.fail_count, 0)

    def test_new_round_resets_the_counter_and_video_flag(self):
        engine = make_engine()
        engine.record = False
        engine.fail_count = 2
        engine.keep_round_video = True
        engine.node_count = 5
        engine.now_area = []

        AnyFateUniverse.restart_recording(engine)

        self.assertEqual(engine.fail_count, 0)
        self.assertFalse(engine.keep_round_video)
        self.assertEqual(engine.node_count, 0)


class VideoRetentionTest(unittest.TestCase):
    def make_iron_blood(self, keep_round_video, kill_count=0):
        engine = IronBloodUniverse.__new__(IronBloodUniverse)
        engine.recorder = Mock()
        engine.opt = {}
        engine.debug = 0
        engine.del_record_time = 31
        engine.elapsed_time = 0
        engine.kill_count = kill_count
        engine.first_plane_weight = -5
        engine.keep_round_video = keep_round_video
        return engine

    def test_iron_blood_keeps_the_video_after_three_stuck_timeouts(self):
        engine = self.make_iron_blood(keep_round_video=True)

        engine.stop_round_recording()

        self.assertFalse(engine.recorder.stop_recording.call_args.args[0])

    def test_iron_blood_still_deletes_normal_low_kill_rounds(self):
        engine = self.make_iron_blood(keep_round_video=False)

        engine.stop_round_recording()

        self.assertTrue(engine.recorder.stop_recording.call_args.args[0])

    def make_finger_snap(self, keep_round_video, countdown=0):
        engine = FingerSnap.__new__(FingerSnap)
        engine.recorder = Mock()
        engine.del_record_time = 31
        engine.countdown = countdown
        engine.ruanmei2 = False
        engine.keep_round_video = keep_round_video
        return engine

    def test_finger_snap_keeps_the_video_after_three_stuck_timeouts(self):
        engine = self.make_finger_snap(keep_round_video=True)

        engine.stop_round_recording()

        self.assertFalse(engine.recorder.stop_recording.call_args.args[0])

    def test_finger_snap_still_deletes_normal_low_countdown_rounds(self):
        engine = self.make_finger_snap(keep_round_video=False)

        engine.stop_round_recording()

        self.assertTrue(engine.recorder.stop_recording.call_args.args[0])

    def test_finger_snap_keeps_the_video_when_ruanmei_appeared(self):
        engine = self.make_finger_snap(keep_round_video=False)
        engine.ruanmei2 = True

        engine.stop_round_recording()

        self.assertFalse(engine.recorder.stop_recording.call_args.args[0])

    def test_iron_blood_keeps_the_video_when_kill_threshold_is_reached(self):
        engine = self.make_iron_blood(keep_round_video=False, kill_count=31)

        engine.stop_round_recording()

        self.assertFalse(engine.recorder.stop_recording.call_args.args[0])

    def test_error_exit_keeps_the_video_even_without_kills(self):
        engine = self.make_iron_blood(keep_round_video=False)
        engine.keep_video_for_error = True

        engine.stop_round_recording()

        self.assertFalse(engine.recorder.stop_recording.call_args.args[0])

    def test_manual_stop_keeps_the_video_when_kills_exist(self):
        engine = self.make_iron_blood(keep_round_video=False, kill_count=3)

        self.assertFalse(engine.keep_video_reasons(manual_stop=True) == [])
        self.assertEqual(
            [reason for reason in engine.keep_video_reasons(manual_stop=True)
             if "手动停止" in reason],
            ["手动停止时已有击杀 3"],
        )


class ProgramStopVideoTest(unittest.TestCase):
    """程序结束时停止录像也遵守保留标记（铁血在本局击杀数为 0 时默认会删视频）。"""

    def stop_engine(self, keep_round_video, kill_count=0):
        engine = IronBloodUniverse.__new__(IronBloodUniverse)
        engine._stop = 0
        engine.record = True
        engine.bveerelbcpgyqan = True
        engine.kill_count = kill_count
        engine.keep_round_video = keep_round_video
        engine.recorder = Mock()
        engine.save_screen = Mock()
        engine.map_thread = object()
        return engine

    def run_stop(self, engine):
        with patch("core.any_fate.utils.CUS_LOGGER"), \
                patch("core.any_fate.utils.key_mouse_manager"):
            engine.stop()

    def test_program_stop_keeps_the_video_when_the_round_needs_review(self):
        engine = self.stop_engine(keep_round_video=True)

        self.run_stop(engine)

        self.assertFalse(engine.recorder.stop_recording.call_args.kwargs["delete_video"])

    def test_program_stop_still_deletes_normal_rounds_without_kills(self):
        engine = self.stop_engine(keep_round_video=False)

        self.run_stop(engine)

        self.assertTrue(engine.recorder.stop_recording.call_args.kwargs["delete_video"])


if __name__ == "__main__":
    unittest.main()
