import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

IronBloodUniverse = importlib.import_module("core.iron_blood.engine").IronBloodUniverse
SimulatedUniverse = importlib.import_module("core.simulated.engine").SimulatedUniverse


class SpecialMapTargetParsingTest(unittest.TestCase):
    def test_special_target_parser_ignores_green_start(self):
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        cv.circle(image, (10, 10), 1, (0, 255, 0), -1)
        cv.circle(image, (35, 35), 1, (29, 230, 181), -1)
        cv.circle(image, (65, 65), 1, (0, 242, 255), -1)
        cv.circle(image, (10, 65), 1, (36, 28, 237), -1)

        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.speed = False
        with patch.object(cv, "imread", return_value=image.copy()):
            targets = universe.get_target("unused.png", 0, 0, target_mode="special")

        self.assertEqual([1, 2, 3], sorted(target_type for _, target_type in targets))


class RecordedSpecialMapNavigationTest(unittest.TestCase):
    @staticmethod
    def make_universe(targets):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.target = set(targets)
        universe.find = True
        universe.now_map = "event_map"
        universe._stop = False
        universe.target_type = 2
        universe.target_loc = next(
            (target[0] for target in targets if target[1] == 2), None
        )
        universe.last_interact_time = 0
        universe.special_interaction_failures = {}
        universe.native_special_map_root = None
        universe.loaded_map_root = None
        universe.trust_annotated_attack_targets = False
        universe.get_path_with_big_map = Mock()
        universe.do_interaction = Mock(return_value=1)
        return universe

    def test_recorded_map_tracks_and_interacts(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction, ((40, 50), 3)})
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        universe.get_path_with_big_map.assert_called_once_with()
        universe.do_interaction.assert_called_once_with()
        fallback.assert_not_called()
        self.assertNotIn(interaction, universe.target)
        self.assertGreater(universe.last_interact_time, 0)

    def test_consumed_interaction_continues_remaining_big_map_route(self):
        universe = self.make_universe({((40, 50), 3)})
        universe.get_path_with_big_map.side_effect = lambda: setattr(
            universe, "target_type", 3
        )
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        fallback.assert_not_called()
        universe.get_path_with_big_map.assert_called_once_with()
        universe.do_interaction.assert_not_called()

    def test_path_waypoint_does_not_trigger_interaction(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction})
        universe.target_type = 0
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        universe.do_interaction.assert_not_called()
        self.assertIn(interaction, universe.target)

    def test_special_map_trusts_annotated_red_attack_target(self):
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        red_target = ((280, 623), 1)
        universe.target = {red_target}
        universe.now_loc = (273, 640)
        universe.last = (300, 640)
        universe.trust_annotated_attack_targets = True

        self.assertEqual(red_target, universe.get_recent_target())
        self.assertIn(red_target, universe.target)

    def test_special_red_navigation_temporarily_enables_trusted_mode(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction, ((8, 10), 1)})
        universe.target_type = 1
        observed = []
        universe.get_path_with_big_map.side_effect = lambda: observed.append(
            universe.trust_annotated_attack_targets
        )

        universe.navigate_recorded_special_map(Mock())

        self.assertEqual([True], observed)
        self.assertFalse(universe.trust_annotated_attack_targets)
        universe.do_interaction.assert_not_called()

    def test_special_red_target_clicks_once_without_using_skill(self):
        red_target = ((12, 34), 1)
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.target = {red_target}
        universe.target_loc = red_target[0]
        universe.target_type = 1
        universe.now_loc = red_target[0]
        universe.last = red_target[0]
        universe._stop = False
        universe.skill_num = 1
        universe.quan = 1
        universe.bai_e = 1
        universe.trust_annotated_attack_targets = True
        universe.last_interact_time = 0
        universe.get_loc = Mock(return_value=True)
        universe.get_screen = Mock(return_value=np.zeros((1080, 1920, 3), dtype=np.uint8))
        universe.get_recent_target = Mock(return_value=red_target)
        universe.update_direction_data = Mock(return_value=1)
        universe.check = Mock(return_value=True)
        universe.use_e = Mock()
        manager = Mock()

        with (
            patch("core.simulated.utils.key_mouse_manager", manager),
            patch("core.simulated.utils.sprint"),
            patch("core.simulated.utils.match_skill_numbers_in_region", return_value=None),
        ):
            universe.get_path_with_big_map()

        manager.click.assert_called_once_with(0.5, 0.5)
        universe.use_e.assert_not_called()
        universe.check.assert_not_called()
        self.assertNotIn(red_target, universe.target)

    def test_failed_interaction_is_removed_after_retry_limit(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction})
        universe.do_interaction.return_value = None
        fallback = Mock()

        for _ in range(3):
            universe.navigate_recorded_special_map(fallback)

        self.assertNotIn(interaction, universe.target)
        fallback.assert_called_once_with()

    def test_shop_return_resumes_remaining_big_map_route(self):
        interaction = ((12, 34), 2)
        endpoint = ((40, 50), 3)
        universe = self.make_universe({interaction, endpoint})
        universe.do_interaction.return_value = None
        fallback = Mock()

        for _ in range(3):
            universe.navigate_recorded_special_map(fallback)

        self.assertNotIn(interaction, universe.target)
        self.assertIn(endpoint, universe.target)
        fallback.assert_called_once_with()

        # The native fallback opens and finishes the shop state machine.  On
        # returning to map navigation, only the remaining mapped route exists.
        universe.target_loc = endpoint[0]
        universe.get_path_with_big_map.side_effect = lambda: setattr(
            universe, "target_type", 3
        )
        universe.navigate_recorded_special_map(fallback)

        self.assertEqual(4, universe.get_path_with_big_map.call_count)
        fallback.assert_called_once_with()

    def test_recording_switch_off_still_uses_loaded_map(self):
        universe = self.make_universe({((12, 34), 2)})
        universe.record_event_map_enabled = False
        universe.area = "事件"
        universe.record_map_contexts = {"event": ("maps", {})}
        universe.big_map_init = True
        universe.loaded_map_root = "maps"
        universe.need_record = False
        universe.navigate_recorded_special_map = Mock()
        fallback = Mock()

        self.assertFalse(universe.record_special_map_or_navigate(fallback))

        universe.navigate_recorded_special_map.assert_called_once_with(fallback)
        fallback.assert_not_called()

    def test_unknown_map_restores_and_stays_on_native_navigation(self):
        universe = self.make_universe(set())
        universe.record_event_map_enabled = False
        universe.area = "事件"
        universe.record_map_contexts = {"event": ("maps", {})}
        universe.big_map_init = False
        universe.big_map = "polluted special map"
        universe.mini_state = 9
        universe.first_mini = 0
        universe.need_record = False
        universe.map_data_load = Mock(return_value=(False, False, True))
        fallback = Mock()
        manager = Mock()

        with patch("core.iron_blood.engine.key_mouse_manager", manager):
            universe.record_special_map_or_navigate(fallback)
            universe.record_special_map_or_navigate(fallback)

        universe.map_data_load.assert_called_once_with(
            create=False,
            map_root="maps",
            image_maps={},
            target_mode="special",
        )
        self.assertEqual("maps", universe.native_special_map_root)
        self.assertIsNone(universe.big_map)
        self.assertFalse(universe.big_map_init)
        self.assertEqual(1, universe.mini_state)
        self.assertEqual(1, universe.first_mini)
        self.assertEqual(2, fallback.call_count)

    def test_new_room_clears_special_map_source(self):
        universe = self.make_universe(set())
        universe.native_special_map_root = "maps"
        universe.loaded_map_root = "maps"
        universe.node_count = 0

        with patch.object(SimulatedUniverse, "init_map") as native_init:
            universe.init_map()

        native_init.assert_called_once_with()
        self.assertIsNone(universe.native_special_map_root)
        self.assertIsNone(universe.loaded_map_root)

    def test_rest_area_does_not_reuse_previous_battle_map(self):
        universe = self.make_universe({((12, 34), 1)})
        universe.record_event_map_enabled = False
        universe.area = "休整"
        universe.record_map_contexts = {"rest": ("rest_maps", {})}
        universe.big_map_init = True
        universe.loaded_map_root = "battle_maps"
        universe.need_record = False
        universe.map_data_load = Mock(return_value=(True, False, True))
        universe.navigate_recorded_special_map = Mock()

        def reset_big_map():
            universe.big_map_init = False

        with patch.object(
            SimulatedUniverse, "init_map", side_effect=reset_big_map
        ) as native_init, patch("core.iron_blood.engine.key_mouse_manager", Mock()):
            universe.record_special_map_or_navigate(Mock())

        native_init.assert_called_once_with()
        universe.map_data_load.assert_called_once_with(
            create=False,
            map_root="rest_maps",
            image_maps={},
            target_mode="special",
        )

    @staticmethod
    def run_special_map_load(create, targets):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.debug = True
        universe.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        universe.first_save_map = True
        universe.pos_predictor = Mock()
        universe.pos_predictor.update_minimap_data.return_value = (0, 0)
        universe.get_blank_state = Mock(return_value=300)
        universe.get_screen = Mock(return_value=universe.screen)
        universe.click_text = Mock(return_value=False)
        universe._match_map_templates = Mock(return_value=("my_17682", 1.0))
        universe.get_target = Mock(return_value=set(targets))

        latest = ("map.jpg", 424.0, 588.8, 31, 207.0, 277.0, "target.jpg")
        with (
            patch("core.iron_blood.engine.find_latest_modified_file", return_value=latest),
            patch("core.iron_blood.engine.cv.imread", return_value=np.zeros((80, 98), dtype=np.uint8)),
            patch("core.iron_blood.engine.key_mouse_manager", Mock()),
        ):
            return universe.map_data_load(
                create=create,
                map_root="special_maps",
                image_maps={},
                target_mode="special",
            )

    def test_my_special_map_always_remains_in_recording_mode(self):
        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=False, targets=set()),
        )
        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=True, targets=set()),
        )

    def test_annotated_my_map_still_remains_in_recording_mode(self):
        interaction = {((12, 34), 2)}

        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=True, targets=interaction),
        )


class HertaInteractionTest(unittest.TestCase):
    @staticmethod
    def make_universe(text="黑塔", global_herta_match=False, quit_time=0):
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.check = Mock(return_value=True)
        universe.get_small_interaction_img = Mock(
            return_value=np.zeros((10, 10), dtype=np.uint8)
        )
        universe.get_screen = Mock()
        universe.tk = SimpleNamespace(interacts=["黑塔", "事件"])
        universe.ts = Mock()
        universe.ts.similar_list.return_value = text
        universe.ts.similar.return_value = global_herta_match
        universe.quit = quit_time
        universe.update_state = Mock()
        return universe

    def test_herta_crop_result_sets_cooldown_even_if_global_ocr_misses(self):
        universe = self.make_universe(global_herta_match=False)
        manager = Mock()

        with patch("core.simulated.engine.time.time", return_value=100), patch(
            "core.simulated.engine.key_mouse_manager", manager
        ):
            result = universe.do_interaction()

        self.assertEqual(1, result)
        self.assertEqual(100, universe.quit)
        manager.press.assert_called_once_with("f", force=True)

    def test_herta_during_cooldown_does_not_press_again(self):
        universe = self.make_universe(quit_time=90)
        manager = Mock()

        with patch("core.simulated.engine.time.time", return_value=100), patch(
            "core.simulated.engine.key_mouse_manager", manager
        ):
            result = universe.do_interaction()

        self.assertIsNone(result)
        manager.press.assert_not_called()
        universe.update_state.assert_called_once_with("run")


if __name__ == "__main__":
    unittest.main()
