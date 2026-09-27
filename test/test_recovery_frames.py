"""重放真实 4K HUD：超时恢复必须复核当前画面，避免向祝福页发 Esc。"""

import hashlib
import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from test.test_simul_thread_lifecycle import load_methods
from tool.utils.image_tool import (
    find_image_by_name,
    load_all_images_from_directory,
    match_template_soft,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "test/fixtures/recovery"


class RecoveryFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_all_images_from_directory(str(ROOT / "resource/imgs"))

    def test_current_hud_controls_recovery_in_base_and_inherited_modes(self):
        sources = json.loads((SAMPLES / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(sources), 3)
        for filename, class_name in (("simul.py", "SimulatedUniverse"), ("any_fate.py", "AnyFateUniverse")):
            for source in sources:
                with self.subTest(mode=class_name, sample=source["file"]):
                    manager = Mock()
                    task = load_methods(filename, class_name, {"normal"}, {
                        "time": types.SimpleNamespace(time=Mock(return_value=100)),
                        "key_mouse_manager": manager, "CUS_LOGGER": Mock(),
                        "merge_text": "".join, "os": os,
                        "PATHS": {"image": "images"}, "factor": "测试角色",
                    })
                    task._stop = False
                    task.state = "run"
                    task.last_interact_time = 50
                    task.max_interact_time = 40
                    task.quan = task.bai_e = 1
                    task.floor_init = task.big_map_init = task.find = 1
                    task.floor = 2
                    task.debug = task.slow = task.mini_state = task.fail_count = 0
                    task.need_end = task.need_record = task.auto_attack_breakable = False
                    task.opt = {}
                    task.loaded_map_root = None
                    task.now_map, task.now_map_sim = "map", 0.99
                    task.is_pig_node = Mock(return_value=False)
                    task.switch_current_role = Mock()
                    task.navigate_battle = Mock(return_value=False)
                    task.click_text = Mock(return_value=True)
                    task.init_map = Mock()
                    task._abort_walk = Mock()
                    task.get_screen = Mock()
                    task.ts = Mock()
                    task.ts.find_with_box.return_value = ["战斗"]
                    task.run_static = Mock(return_value=("", 0))
                    task.update_state = Mock(side_effect=lambda state: setattr(task, "state", state))

                    sample_path = SAMPLES / source["file"]
                    self.assertEqual(hashlib.sha256(sample_path.read_bytes()).hexdigest(), source["sha256"])
                    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
                    x1, y1, x2, y2 = source["box"]
                    frame[y1:y2, x1:x2] = cv2.imread(str(sample_path))
                    vision = load_methods("tool/simul/utils.py", "UniverseUtils", {"check", "get_local", "is_run"}, {
                        "cv": cv2, "find_image_by_name": find_image_by_name,
                        "match_template_soft": match_template_soft, "CUS_LOGGER": Mock(),
                    })
                    vision.scx, vision.xx, vision.yy = 1, 1920, 1080
                    vision.cap_scale, vision.last_info = 2.0, ""
                    vision.screen = frame
                    vision.get_screen = Mock(return_value=frame)
                    task.check = vision.check
                    task.is_run = types.MethodType(vision.is_run.__func__, task)
                    self.assertEqual(task.normal(), int(source["running"]))
                    task._abort_walk.assert_called_once()
                    vision.get_screen.assert_called_once()
                    if source["running"]:
                        manager.press.assert_called_once_with("esc")
                        self.assertGreater(vision.tm, 0.98)
                    else:
                        manager.press.assert_not_called()
                        self.assertEqual(task.state, "no_run")


if __name__ == "__main__":
    unittest.main()
