"""小地图识别失败时 get_loc 与整图重定位的行为。

战斗、黑屏、加载动画等状态下小地图不可用，位置模板匹配只能得到错误峰值。此处的约束是：
- 朝向箭头识别失败即视为分析失败，本次不写入 now_loc / pos_predictor.position；
- 失败后重新截图再识别一次，跳过淡出、弹窗遮挡这类瞬时失效；
- 连续失败达到阈值后，等小地图恢复可用的那一帧做整图重定位，相邻两帧结果一致才提交坐标；
- 主页标志（动作脚本「可能处于模拟宇宙中」的触发器）也识别不到时返回 False（调用方据此返回主循环），
  并输出一条 warning。
"""

import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
# core.simulated.utils 在 import 时就会读模板图，必须先载入资源图
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

import core.simulated.utils as simulated_utils  # 必须在资源图载入之后导入
from tool.utils.mminimap import PositionPredict  # 必须在资源图载入之后导入

SimulatedUniverse = importlib.import_module("core.simulated.engine").SimulatedUniverse

# get_loc 的起始坐标，测试断言它在失败路径上保持原值
NOW_LOC = (100.0, 200.0)
# 位置预测器缓存的搜索中心
PREDICTOR_POS = (400.0, 500.0)
# 窗口搜索（原有逻辑）返回的坐标
MATCHED_LOC = (1.0, 2.0)
# 整图重定位确认后的坐标
CANDIDATE_LOC = (700.0, 800.0)
# 等价于动作脚本「可能处于模拟宇宙中」触发器的识别参数
BIG_WORLD_ARGS = dict(threshold=0.98, fresh=True)


def make_universe(directions=(None, None), big_world=False, positions=(MATCHED_LOC,), fail_count=0,
                  relocate_results=((None, False),)):
    """构造只具备 get_loc 所需属性的实例。

    directions：每次朝向识别的结果，None 表示蓝色箭头缺失；positions：每次窗口位置匹配的结果；
    relocate_results：每次整图重定位的返回值 (position, gave_up)，position 为 None 表示仍在等待确认。
    """
    universe = SimulatedUniverse.__new__(SimulatedUniverse)
    universe.now_loc = NOW_LOC
    universe.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
    universe.minimap_fail_count = fail_count
    universe.pos_predictor = Mock()
    universe.pos_predictor.position = PREDICTOR_POS
    universe.pos_predictor.scale = 1.0
    universe.pos_predictor.update_minimap_data.side_effect = [(0.0, direction) for direction in directions]
    universe.pos_predictor.update_position.side_effect = [(position, 0.9) for position in positions]
    universe.pos_predictor.relocate.side_effect = list(relocate_results)
    universe.check = Mock(return_value=big_world)
    universe.get_screen = Mock()
    universe.update_state = Mock()
    return universe


class GetLocMinimapFailureTest(unittest.TestCase):
    def test_failure_outside_universe_warns_and_returns_false(self):
        """两次识别都失败且不在模拟宇宙中：不改缓存、返回 False、只记一条 warning。"""
        universe = make_universe(directions=[None, None], big_world=False)

        with patch("core.simulated.utils.time.sleep"), patch.object(simulated_utils.CUS_LOGGER, "warning") as warning:
            result = universe.get_loc(False)

        self.assertFalse(result)
        self.assertEqual(NOW_LOC, universe.now_loc)
        self.assertEqual(1, universe.minimap_fail_count)
        universe.pos_predictor.update_position.assert_not_called()
        universe.check.assert_called_once_with("big_world", 1801, 941, **BIG_WORLD_ARGS)
        self.assertEqual(1, warning.call_count)
        self.assertIn("小地图识别失败", warning.call_args[0][0])

    def test_failure_retries_with_new_screenshot(self):
        """首次识别失败后重新截图再识别一次；两次都失败才进入失败分支。"""
        universe = make_universe(directions=[None, None], big_world=True)

        with patch("core.simulated.utils.time.sleep") as sleep, patch.object(simulated_utils.CUS_LOGGER, "warning"):
            result = universe.get_loc(False)

        self.assertTrue(result)
        universe.get_screen.assert_called_once_with()
        self.assertEqual(2, universe.pos_predictor.update_minimap_data.call_count)
        self.assertEqual(1, universe.minimap_fail_count)
        self.assertEqual(NOW_LOC, universe.now_loc)

    def test_failure_inside_universe_keeps_position_without_warning(self):
        """分析失败但仍在模拟宇宙中（例如瞬时遮挡）：不改缓存、返回 True、不记 warning。"""
        universe = make_universe(directions=[None, None], big_world=True)

        with patch("core.simulated.utils.time.sleep"), patch.object(simulated_utils.CUS_LOGGER, "warning") as warning:
            result = universe.get_loc(False)

        self.assertTrue(result)
        self.assertEqual(NOW_LOC, universe.now_loc)
        universe.pos_predictor.update_position.assert_not_called()
        universe.check.assert_called_once_with("big_world", 1801, 941, **BIG_WORLD_ARGS)
        warning.assert_not_called()

    def test_retry_success_uses_new_screenshot(self):
        """重新截图后识别成功：按原逻辑更新坐标，且不累计失败次数。"""
        universe = make_universe(directions=[None, 90.0], positions=[MATCHED_LOC])

        with patch("core.simulated.utils.time.sleep"), patch.object(simulated_utils.CUS_LOGGER, "warning") as warning:
            result = universe.get_loc(False)

        self.assertTrue(result)
        self.assertEqual(MATCHED_LOC, universe.now_loc)
        self.assertEqual(0, universe.minimap_fail_count)
        universe.get_screen.assert_called_once_with()
        universe.pos_predictor.update_position.assert_called_once_with(universe.screen)
        universe.check.assert_not_called()
        warning.assert_not_called()

    def test_success_updates_position(self):
        """朝向箭头识别正常时走原逻辑：更新 now_loc 并返回 True。"""
        universe = make_universe(directions=[90.0], big_world=True)

        with patch.object(simulated_utils.CUS_LOGGER, "warning") as warning:
            result = universe.get_loc(False)

        self.assertTrue(result)
        self.assertEqual(MATCHED_LOC, universe.now_loc)
        universe.pos_predictor.update_position.assert_called_once_with(universe.screen)
        universe.pos_predictor.update_minimap_data.assert_called_once()
        universe.check.assert_not_called()
        warning.assert_not_called()

    def test_refresh_skips_minimap_analysis_outside_universe(self):
        """fresh=True 时先按主页标志判断是否在模拟宇宙内，不在则直接返回，不做小地图分析。"""
        universe = make_universe(directions=[None], big_world=False)

        result = universe.get_loc(True)

        self.assertFalse(result)
        universe.get_screen.assert_called_once_with()
        universe.update_state.assert_called_once_with("no_run")
        universe.pos_predictor.update_minimap_data.assert_not_called()
        self.assertEqual(NOW_LOC, universe.now_loc)


class GetLocRelocateTest(unittest.TestCase):
    def test_pending_relocation_keeps_position(self):
        """连续失败达到阈值后交给预测器整图重定位；候选尚未确认时保持旧坐标与失败计数。"""
        universe = make_universe(directions=[90.0], fail_count=3, relocate_results=[(None, False)])

        with patch.object(simulated_utils.CUS_LOGGER, "warning") as warning, \
                patch.object(simulated_utils.CUS_LOGGER, "info") as info:
            result = universe.get_loc(False)

        self.assertTrue(result)
        universe.pos_predictor.relocate.assert_called_once_with(universe.screen)
        universe.pos_predictor.update_position.assert_not_called()
        self.assertEqual(NOW_LOC, universe.now_loc)
        self.assertEqual(3, universe.minimap_fail_count)
        warning.assert_not_called()
        info.assert_not_called()

    def test_confirmed_relocation_commits_position(self):
        """整图重定位两帧一致后提交坐标，并清空失败计数。"""
        universe = make_universe(directions=[90.0, 90.0], fail_count=3,
                                 relocate_results=[(None, False), (CANDIDATE_LOC, False)])

        with patch.object(simulated_utils.CUS_LOGGER, "warning") as warning, \
                patch.object(simulated_utils.CUS_LOGGER, "info") as info:
            self.assertTrue(universe.get_loc(False))
            self.assertEqual(NOW_LOC, universe.now_loc)
            self.assertTrue(universe.get_loc(False))

        self.assertEqual(CANDIDATE_LOC, universe.now_loc)
        self.assertEqual(0, universe.minimap_fail_count)
        warning.assert_not_called()
        self.assertEqual(1, info.call_count)
        self.assertIn("整图重定位成功", info.call_args[0][0])

    def test_gave_up_relocation_resets_failure_count(self):
        """整图重定位放弃时保留上次可信坐标，并清空失败计数等下一轮重来。"""
        universe = make_universe(directions=[90.0], fail_count=3, relocate_results=[(None, True)])

        with patch.object(simulated_utils.CUS_LOGGER, "warning") as warning:
            result = universe.get_loc(False)

        self.assertTrue(result)
        self.assertEqual(NOW_LOC, universe.now_loc)
        self.assertEqual(0, universe.minimap_fail_count)
        self.assertEqual(1, warning.call_count)
        self.assertIn("整图重定位连续不一致", warning.call_args[0][0])


class PositionPredictRelocateTest(unittest.TestCase):
    """整图重定位本身的状态机：是否整图搜索、候选何时提交、何时放弃。"""

    def make_predictor(self, positions):
        """构造只保留重定位所需属性的预测器，避免真的做模板匹配。"""
        predictor = PositionPredict.__new__(PositionPredict)
        predictor.position = PREDICTOR_POS
        predictor.relocate_candidate = None
        predictor.relocate_mismatch = 0
        predictor.searched_positions = []

        def fake_update_position(image, update=True):
            predictor.searched_positions.append(predictor.position)
            return positions.pop(0), 0.5

        predictor.update_position = fake_update_position
        return predictor

    def test_first_frame_only_records_candidate(self):
        """第一帧：搜索中心清零做整图匹配，结果只作候选，搜索中心恢复原值。"""
        predictor = self.make_predictor([CANDIDATE_LOC])

        with patch.object(simulated_utils.CUS_LOGGER, "debug"):
            position, gave_up = predictor.relocate(np.zeros((1080, 1920, 3), dtype=np.uint8))

        self.assertIsNone(position)
        self.assertFalse(gave_up)
        self.assertEqual([(0, 0)], predictor.searched_positions)
        self.assertEqual(PREDICTOR_POS, predictor.position)
        self.assertEqual(CANDIDATE_LOC, predictor.relocate_candidate)

    def test_second_consistent_frame_commits_position(self):
        """第二帧结果与候选一致：提交为当前坐标并清空候选。"""
        predictor = self.make_predictor([CANDIDATE_LOC, CANDIDATE_LOC])

        with patch.object(simulated_utils.CUS_LOGGER, "debug"):
            predictor.relocate(np.zeros((1080, 1920, 3), dtype=np.uint8))
            position, gave_up = predictor.relocate(np.zeros((1080, 1920, 3), dtype=np.uint8))

        self.assertEqual(CANDIDATE_LOC, position)
        self.assertFalse(gave_up)
        self.assertEqual(CANDIDATE_LOC, predictor.position)
        self.assertIsNone(predictor.relocate_candidate)
        self.assertEqual(0, predictor.relocate_mismatch)

    def test_repeated_mismatch_gives_up(self):
        """连续 4 次结果互相印证不上：放弃重定位，保留原搜索中心。"""
        predictor = self.make_predictor([(100.0, 100.0), (500.0, 100.0), (900.0, 100.0), (1300.0, 100.0),
                                         (1700.0, 100.0)])

        with patch.object(simulated_utils.CUS_LOGGER, "debug"):
            results = [predictor.relocate(np.zeros((1080, 1920, 3), dtype=np.uint8)) for _ in range(5)]

        self.assertEqual([(None, False)] * 4 + [(None, True)], results)
        self.assertEqual(PREDICTOR_POS, predictor.position)
        self.assertIsNone(predictor.relocate_candidate)
        self.assertEqual(0, predictor.relocate_mismatch)

    def test_set_now_map_clears_candidate(self):
        """换图后上一张地图的候选坐标不再适用。"""
        predictor = self.make_predictor([CANDIDATE_LOC])

        with patch.object(simulated_utils.CUS_LOGGER, "debug"), patch.object(simulated_utils.CUS_LOGGER, "info"):
            predictor.relocate(np.zeros((1080, 1920, 3), dtype=np.uint8))
            predictor.set_now_map(1)

        self.assertIsNone(predictor.relocate_candidate)
        self.assertEqual(0, predictor.relocate_mismatch)


if __name__ == "__main__":
    unittest.main()
