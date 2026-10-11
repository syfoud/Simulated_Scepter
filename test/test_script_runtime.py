"""隔离游戏设备，以业务内核原有主循环验证脚本的寻路与战斗推进。"""

import ast
import copy
import json
import os
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from core.common.engine import StateKernel
from route import PATHS
from tool.action_script import run_script
from tool.public_ocr import merge_text
from tool.utils.Error import NormalEndError

ROOT = Path(__file__).resolve().parents[1]


def script_fixture(kernel_id, path):
    """加载实际业务方法及继承链，替换窗口、地图与键鼠设备边界。"""
    manager = Mock()
    namespace = {"StateKernel": StateKernel, "key_mouse_manager": manager,
                 "CUS_LOGGER": Mock(), "time": SimpleNamespace(time=lambda: 100, sleep=Mock()),
                 "os": os, "PATHS": PATHS, "random": random, "factor": "测试",
                 "merge_text": merge_text, "NormalEndError": NormalEndError,
                 "set_forground": Mock()}
    definitions = [
        ("simulated/utils.py", "UniverseUtils", {"is_run"}),
        ("simulated/engine.py", "SimulatedUniverse", {"start", "route", "normal", "auto_battle"}),
        ("any_fate/engine.py", "AnyFateUniverse", {"normal"}),
        ("iron_blood/engine.py", "IronBloodUniverse", set()),
        ("finger_snap/engine.py", "FingerSnap", set()),
    ]
    for filename, name, methods in definitions:
        source = ROOT / "core" / filename
        tree = ast.parse(source.read_text(encoding="utf-8"))
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
        node.body = [node for node in node.body if isinstance(node, ast.FunctionDef) and node.name in methods] or [ast.Pass()]
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, str(source), "exec"), namespace)
    classes = {"Simulated": "SimulatedUniverse", "AnyFate": "AnyFateUniverse",
               "IronBlood": "IronBloodUniverse", "FingerSnap": "FingerSnap"}
    engine = namespace[classes[kernel_id]]()
    engine._stop = False
    engine.record = engine._show_map = False
    engine.init_map = Mock()
    engine.last_interact_time = engine.attack_time = 100
    engine.floor_init = engine.big_map_init = engine.find = engine.mini_state = 1
    engine.floor, engine.debug, engine.slow, engine.f_time = 1, 1, False, 0
    engine.quan = engine.bai_e = False
    engine.need_end = engine.need_record = engine.auto_attack_breakable = False
    engine.opt, engine.loaded_map_root, engine.max_interact_time = {}, None, 60
    engine.fate = "丰饶" if kernel_id == "FingerSnap" else "毁灭"
    engine.is_pig_node = Mock(return_value=False)
    engine.switch_current_role = Mock()
    engine.ts = Mock()
    engine.ts.find_with_box.side_effect = lambda box, **_: (
        [{"raw_text": "战斗", "box": box}] if box == [55, 164, 12, 40] else [])
    phases = ["big_world"]
    frame = np.full((24, 24, 3), 100, dtype=np.uint8)

    def screen():
        if engine.get_screen.call_count > 12:
            raise AssertionError("big_world 重复命中，业务主循环没有推进")
        return frame

    engine.get_screen = Mock(side_effect=screen)
    engine.check = Mock(side_effect=lambda photo, *_args, **_kwargs: photo == phases[-1])

    def navigate():
        if engine.state != "run":
            raise AssertionError("寻路必须由 run 状态进入")
        phases.append("battle_ready")
        return True

    engine.navigate_battle = engine.get_direc_only_minimap = Mock(side_effect=navigate)

    def stop():
        engine._stop = True
        manager.stop()

    engine.stop = Mock(side_effect=stop)

    def window():
        if engine.state == "battle":
            engine.stop()
        return 1, "崩坏：星穹铁道"

    namespace["get_hwnd_and_text"] = window
    source = "simulated/actions/universe.json" if kernel_id == "Simulated" else "any_fate/actions/insect.json"
    events = json.loads((ROOT / "core" / source).read_text(encoding="utf-8"))
    event = copy.deepcopy(next(event for event in events if event["trigger"].get("photo") == "big_world"))
    data = [{"name": "进入战斗", "trigger": {"photo": "battle_ready", "pos": {"x": 0.5, "y": 0.5}},
             "actions": ["auto_battle"]}, event]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return engine, manager, phases


class ScriptRuntimeTests(unittest.TestCase):
    def test_business_start_route_and_normal_advance_big_world_to_navigation_and_battle(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("tool.action_script.get_global_stop_flag", return_value=False):
            path = Path(temporary) / "selected.json"
            for kernel_id in ("Simulated", "AnyFate", "IronBlood", "FingerSnap"):
                with self.subTest(kernel_id=kernel_id):
                    engine, manager, phases = script_fixture(kernel_id, path)
                    with patch("core.common.engine.key_mouse_manager", manager):
                        run_script(engine, str(path))
                    self.assertEqual(phases, ["big_world", "battle_ready"])
                    self.assertEqual(engine.state, "battle")
                    self.assertEqual(engine.action_history, ["可能处于模拟宇宙中", "进入战斗"])
                    self.assertEqual(engine.default_json_path, str(path))
                    self.assertTrue(engine._stop)
                    manager.start.assert_called_once()
                    manager.press.assert_any_call("v")
                    manager.stop.assert_called_once()
                    engine.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
