"""无地图寻路按区域记录并恢复初始镜头角度的回归测试。"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse  # noqa: E402
from core.any_fate.utils import FateUtils  # noqa: E402


class InitialAngleRestoreTest(unittest.TestCase):
    def make_utils(self, mini_state):
        utils = FateUtils.__new__(FateUtils)
        utils.mini_state = mini_state
        utils.stop_move = 1
        utils.ready = 0
        utils.is_find_end = 0
        utils.has_target = False
        return utils

    def test_restore_uses_camera_rotation_and_wraps_shortest_turn(self):
        utils = self.make_utils(1)
        utils.pos_predictor = Mock(update_minimap_data=Mock(return_value=(1, 0.7)))
        utils.get_screen = Mock(return_value="frame")
        manager = Mock()

        with (
            patch("core.any_fate.utils.key_mouse_manager", manager),
            patch("core.any_fate.utils.CUS_LOGGER", Mock()),
        ):
            utils.restore_initial_angle(359)

        manager.turn.assert_called_once_with(-2)
        manager.wait.assert_called_once_with()

    def test_unfound_text_restores_area_angle(self):
        utils = self.make_utils(1)
        utils.move_direct_to_text = Mock(return_value=False)
        utils.restore_initial_angle = Mock()

        with patch("core.any_fate.utils.CUS_LOGGER", Mock()):
            utils.move_direct_thread(initial_angle=359)

        utils.restore_initial_angle.assert_called_once_with(359)
        self.assertFalse(utils.has_target)

    def test_unfound_end_restores_area_angle(self):
        utils = self.make_utils(3)
        utils.move_to_end = Mock(return_value=0)
        utils.restore_initial_angle = Mock()

        with patch("core.any_fate.utils.CUS_LOGGER", Mock()):
            utils.move_direct_thread(device=1, initial_angle=359)

        utils.move_to_end.assert_called_once_with(mode=2, device=1)
        utils.restore_initial_angle.assert_called_once_with(359)
        self.assertFalse(utils.has_target)

    def test_found_end_keeps_target_without_restoring_angle(self):
        utils = self.make_utils(3)
        utils.move_to_end = Mock(return_value=1)
        utils.restore_initial_angle = Mock()

        with patch("core.any_fate.utils.CUS_LOGGER", Mock()):
            utils.move_direct_thread(device=1, initial_angle=359)

        self.assertTrue(utils.has_target)
        utils.restore_initial_angle.assert_not_called()

    def test_init_map_clears_area_angle(self):
        utils = self.make_utils(1)
        utils.initial_angle = 359
        utils.backup_map = Mock()
        utils.big_map = object()
        utils.big_map_init = True

        utils.init_map()

        self.assertIsNone(utils.initial_angle)
        self.assertIsNone(utils.big_map)

    def test_path_reuses_angle_until_next_map_initialization(self):
        utils = self.make_utils(0)
        utils.debug = False
        utils.initial_angle = None
        utils._stop = True
        utils.first_mini = 1
        utils.should_update_map = False
        utils.target_type = -1
        utils.pos_predictor = Mock(update_minimap_data=Mock(return_value=(359, 0.7)))
        utils.get_screen = Mock(return_value="frame")
        utils.move_to_red_point = Mock(return_value=False)
        utils.check = Mock(return_value=False)
        utils.is_run = Mock(return_value=False)
        utils.update_state = Mock()

        class ImmediateThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                utils.ready = 1

        manager = Mock()
        with (
            patch("core.any_fate.utils.ThreadWithException", ImmediateThread),
            patch("core.any_fate.utils.key_mouse_manager", manager),
            patch("core.any_fate.utils.CUS_LOGGER", Mock()),
        ):
            utils.get_path_only_minimap()
            self.assertEqual(359, utils.initial_angle)
            utils.get_path_only_minimap()

        self.assertEqual(359, utils.initial_angle)
        utils.pos_predictor.update_minimap_data.assert_called_once_with("frame")

    def test_manual_leave_selection_clears_area_angle(self):
        """动作脚本识别到「暂离」后走统一退出方法：清初始角度并点暂离按钮。"""
        universe = AnyFateUniverse.__new__(AnyFateUniverse)
        universe.initial_angle = 359
        universe.state = "run"
        universe.area = "战斗"
        universe.need_away = True
        universe.need_end = False
        universe.fail_count = 0
        universe.plane_floor = 1
        universe.now_map = -1
        universe.click_text = Mock(return_value=True)
        universe.update_state = Mock()
        universe.init_map = Mock()
        manager = Mock()

        for module in ("core.any_fate.utils", "core.any_fate.engine"):
            self.enterContext(patch(f"{module}.key_mouse_manager", manager))

        universe.leave_universe()

        self.assertIsNone(universe.initial_angle)
        self.assertFalse(universe.need_away)
        self.assertEqual(universe.area, "")
        manager.click_point.assert_called_once_with(1359, 811)


if __name__ == "__main__":
    unittest.main()
