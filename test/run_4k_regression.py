"""执行经过隔离审查的 4K 回归，避免发现并运行手动键鼠实验脚本。"""

import unittest

MODULES = (
    "test.test_capture_geometry",
    "test.test_resolution_scaling",
    "test.test_capture_and_template",
    "test.test_template_methods",
    "test.test_get_screen_guard",
    "test.test_diver_click_target",
    "test.test_passive_number",
    "test.test_action_count_samples",
    "test.test_minimap_tracking",
    "test.test_direction_safety",
    "test.test_align_angle",
    "test.test_key_mouse_release",
    "test.test_thread",
    "test.test_simul_thread_lifecycle",
    "test.test_diver_move_thread",
    "test.test_diver_shutdown",
    "test.test_recording_lifecycle",
    "test.test_window_recorder_shutdown",
    "test.test_config_paths",
    "test.test_4k_entrypoints",
    "test.test_recovery_frames",
)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
