"""「确认移动」之后清空区域名缓存的回归测试。

背景（logs/log_2026-10-26-07-33.txt 第 16:04 段）：重投界面里 init_map() 只在 new_node 为真
时才清空 self.area，而 new_node 已被上一个节点消费掉（日志「是否新节点: False」），区域名于是
停留在「战斗」；下一个节点实际是「事件虫群」，程序按「战斗」去寻路，四十秒没有有效交互后触发
暂离。

现在的行为：三个内核的 select_go 在点完「确认移动」之后清空 self.area，到达下一个节点时重新
识别区域名。清空必须排在 record_map_visit 之后——访问次数统计受「区域名不为空」保护，清早了
统计就断了。

同样的清空也补进了 finger_snap 的 initing_map：切换位面时不走重投界面，原来的区域名会残留到
新位面的第一个节点上。
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]

# 内核在导入期就会读图像记忆切片，需要先装载图像缓存
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse  # noqa: E402
from core.finger_snap.engine import FingerSnap  # noqa: E402
from core.iron_blood.engine import IronBloodUniverse  # noqa: E402

AREA = "战斗"
NOW_MAP = 24047
CLICK_POINT = (100, 200)
SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)


def click_text_side_effect(text=None, **kwargs):
    """只有「选择移动目标」与「确认移动」命中；「点击空白处关闭」不命中，表示没进入下一世对话。"""
    return text != "点击空白处关闭"


def make_key_mouse_manager():
    manager = Mock()
    manager.wait = Mock()
    manager.clean = Mock()
    manager.keyUp = Mock()
    manager.press = Mock()
    return manager


class AnyFateSelectGoTest(unittest.TestCase):
    def make_engine(self, click_effect=click_text_side_effect, new_node=False):
        engine = AnyFateUniverse.__new__(AnyFateUniverse)
        engine.area = AREA
        engine.now_map = NOW_MAP
        engine.new_node = new_node
        engine.next_node = {"cx": CLICK_POINT[0], "cy": CLICK_POINT[1], "name": "event"}
        engine.start_nodes = None
        engine.click_text = Mock(side_effect=click_effect)
        engine.try_analysis_map = Mock(return_value=True)
        engine.record_map_visit = Mock(return_value=277)
        self.key_mouse_manager = Mock()
        for name in ("wait", "clean", "keyUp", "press", "click"):
            setattr(self.key_mouse_manager, name, Mock())
        self.enterContext(
            patch("core.any_fate.engine.key_mouse_manager", self.key_mouse_manager))
        self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", Mock()))
        return engine

    def test_confirm_move_clears_area_name(self):
        engine = self.make_engine()

        engine.select_go()

        self.assertEqual(engine.area, "")
        self.assertIs(engine.new_node, True)
        engine.record_map_visit.assert_called_once_with(NOW_MAP)
        self.key_mouse_manager.click.assert_called_once_with(*CLICK_POINT)

    def test_next_life_dialog_keeps_area_name(self):
        """「下一世」对话里没有移动，区域名不清，否则会白跑一次区域识别。"""
        engine = self.make_engine(click_effect=lambda text=None, **kwargs: True)

        engine.select_go()

        self.assertEqual(engine.area, AREA)
        self.assertIs(engine.new_node, False)
        engine.record_map_visit.assert_not_called()


class IronBloodSelectGoTest(unittest.TestCase):
    def setUp(self):
        self.key_mouse_manager = make_key_mouse_manager()
        self.enterContext(
            patch("core.iron_blood.engine.key_mouse_manager", self.key_mouse_manager))
        self.enterContext(patch("core.iron_blood.engine.CUS_LOGGER", Mock()))
        self.enterContext(patch(
            "core.iron_blood.engine.time", SimpleNamespace(sleep=Mock())))
        self.enterContext(patch(
            "core.iron_blood.engine.match_numbers_in_region",
            Mock(return_value=[])))
        self.enterContext(patch(
            "core.iron_blood.engine.extract_number", Mock(return_value="40")))

    def make_engine(self):
        engine = IronBloodUniverse.__new__(IronBloodUniverse)
        engine.area = AREA
        engine.now_map = NOW_MAP
        engine.new_node = False
        # 被动效果参数 40 → 击杀数 5；二次校验读到的也是 40
        engine.kill_count = 5
        engine.max_limited = 0
        engine.plane_floor = 2
        engine.early_stop = False
        engine.boss_before_pause_count = 0
        engine.next_node = {"cx": CLICK_POINT[0], "cy": CLICK_POINT[1], "name": "event"}
        engine.start_nodes = None
        engine.screen = SCREEN
        engine.get_screen = Mock(return_value=SCREEN)
        engine.set_kill_num = Mock()
        engine.click_text = Mock(side_effect=click_text_side_effect)
        engine.try_analysis_map = Mock(return_value=True)
        engine.record_map_visit = Mock(return_value=277)
        return engine

    def test_confirm_move_clears_area_name(self):
        engine = self.make_engine()

        engine.select_go()

        self.assertEqual(engine.area, "")
        self.assertIs(engine.new_node, True)
        engine.record_map_visit.assert_called_once_with(NOW_MAP)
        self.key_mouse_manager.click.assert_called_once_with(*CLICK_POINT)


class FingerSnapSelectGoTest(unittest.TestCase):
    def setUp(self):
        self.key_mouse_manager = make_key_mouse_manager()
        self.enterContext(
            patch("core.finger_snap.engine.key_mouse_manager", self.key_mouse_manager))
        self.enterContext(patch("core.finger_snap.engine.CUS_LOGGER", Mock()))
        self.enterContext(patch(
            "core.finger_snap.engine.time", SimpleNamespace(sleep=Mock())))
        self.enterContext(patch(
            "core.finger_snap.engine.match_numbers_in_region",
            Mock(return_value=[])))
        self.enterContext(patch(
            "core.finger_snap.engine.extract_number", Mock(return_value="15")))

    def make_engine(self):
        engine = FingerSnap.__new__(FingerSnap)
        engine.area = AREA
        engine.now_map = NOW_MAP
        engine.new_node = False
        engine.countdown = 0
        engine._pending_target = object()
        engine._target_decided = True
        engine.countdown_agent = Mock()
        engine.countdown_agent.apply_path = Mock(
            return_value=SimpleNamespace(countdown=3))
        engine.next_node = {
            "idx": 1, "cx": CLICK_POINT[0], "cy": CLICK_POINT[1], "name": "event"}
        engine.start_nodes = None
        engine.screen = SCREEN
        engine.get_screen = Mock(return_value=SCREEN)
        engine.set_kill_num = Mock()
        engine.click_text = Mock(side_effect=click_text_side_effect)
        engine.try_analysis_map = Mock(return_value=True)
        engine.record_map_visit = Mock(return_value=277)
        return engine

    def test_confirm_move_clears_area_name(self):
        engine = self.make_engine()

        engine.select_go()

        self.assertEqual(engine.area, "")
        self.assertIs(engine.new_node, True)
        engine.record_map_visit.assert_called_once_with(NOW_MAP)
        self.key_mouse_manager.click.assert_called_once_with(*CLICK_POINT)


class FingerSnapInitingMapTest(unittest.TestCase):
    def setUp(self):
        self.key_mouse_manager = make_key_mouse_manager()
        self.enterContext(
            patch("core.finger_snap.engine.key_mouse_manager", self.key_mouse_manager))

    def make_engine(self):
        engine = FingerSnap.__new__(FingerSnap)
        engine.debug = True
        engine.area = AREA
        engine.plane_floor = -1
        engine.node_count = 5
        engine.new_node = False
        engine.click_text = Mock(side_effect=click_text_side_effect)
        engine.try_analysis_map = Mock(return_value=True)
        engine.save_screen = Mock()
        return engine

    def test_entering_plane_clears_area_name(self):
        engine = self.make_engine()

        engine.initing_map()

        self.assertEqual(engine.area, "")
        self.assertEqual(engine.plane_floor, 1)
        self.assertEqual(engine.node_count, 0)
        self.assertIs(engine.new_node, True)


if __name__ == "__main__":
    unittest.main()
