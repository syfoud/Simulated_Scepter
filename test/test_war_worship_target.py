import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

analysis_map = importlib.import_module("tool.utils.analysis_map")
engine_module = importlib.import_module("core.iron_blood.engine")
IronBloodUniverse = engine_module.IronBloodUniverse

START = (100.0, 500.0)
NODE_SIZE = (50, 50)


def make_match(name, cx, cy, marker=None):
    """构造 match_multiple_targets 风格的匹配结果，可选直接挂上角标。"""
    match = {'name': name, 'location': (cx - NODE_SIZE[0] / 2, cy - NODE_SIZE[1] / 2),
             'size': NODE_SIZE, 'similarity': 0.9}
    if marker:
        match['corner_marker'] = {'name': marker, 'location': (cx + 10, cy + 10), 'size': (17, 14),
                                  'similarity': 0.95}
    return match


class WarWorshipTargetTest(unittest.TestCase):
    """「毁灭·战争崇拜」替换祝福扑满信标的目标选择：路径优先，但跳过精英与走不进去的区域。"""

    def select_target(self, matches):
        """用真实的 select_doing 跑一遍（只 mock OCR 文本与鼠标），返回被点击的节点坐标或 None。"""
        nodes, edges, start_idx = analysis_map.build_rightward_graph(matches, start=START, plane=2, battle_weight=1.2)
        path, _, _ = analysis_map.max_weight_path(nodes, edges, start_idx)

        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.nodes = nodes
        universe.edges = edges
        universe.path = path
        universe.steps = analysis_map.compute_all_max_steps(nodes, edges, start_idx)
        universe.start_nodes = path[0]
        universe.ts = Mock(find_with_box=Mock(return_value=["效果文本"]))
        universe.click_text = Mock(return_value=False)
        universe.abandon_confirm = Mock()
        universe.try_analysis_map = Mock()

        manager = Mock()
        with patch.object(engine_module, "merge_text", Mock(return_value="毁灭·战争崇拜")), \
                patch.object(engine_module, "key_mouse_manager", manager):
            universe.select_doing()

        # 生产代码用 click_point 传 1920x1080 像素坐标（节点 cx/cy 取整），
        # 所以「有没有点」与落点都要在 click_point 上断言。
        if not manager.click_point.called:
            self.assertTrue(universe.abandon_confirm.called)
            return None
        self.assertEqual(1, manager.click_point.call_count)
        return manager.click_point.call_args.args

    def test_path_battle_with_blessing_pig_is_replaced(self):
        """最佳路径上的战斗格带祝福扑满：替换它（路径优先的行为保持不变）。"""
        clicked = self.select_target([make_match('battle', 190, 500, 'pig1'), make_match('head', 280, 500)])
        self.assertEqual((190, 500), clicked)

    def test_path_elite_with_blessing_pig_is_skipped(self):
        """精英区域带祝福扑满也不替换：没有其它候选时放弃。"""
        clicked = self.select_target([make_match('elite', 190, 500, 'pig2'), make_match('head', 280, 500)])
        self.assertIsNone(clicked)

    def test_curiosity_pig_is_skipped(self):
        """奇物扑满（金 pig3/pig4）不替换。"""
        clicked = self.select_target([make_match('battle', 190, 500, 'pig3'), make_match('head', 280, 500)])
        self.assertIsNone(clicked)

    def test_unreachable_pig_is_ignored(self):
        """兜底跳过走不进去的祝福扑满：cx190 那格与起点纵向差 200，超出行走限制。"""
        matches = [make_match('battle', 190, 500), make_match('battle', 280, 500), make_match('head', 370, 500),
                   make_match('battle', 190, 300, 'pig1'),
                   make_match('adventure', 190, 620), make_match('bugbattle', 280, 700, 'pig2')]
        clicked = self.select_target(matches)
        self.assertEqual((280, 700), clicked)

    def test_fallback_keeps_leftmost_order(self):
        """兜底排序保持原样：两个可达候选里取最靠左的那个。"""
        matches = [make_match('battle', 190, 500), make_match('battle', 280, 500), make_match('head', 370, 500),
                   make_match('adventure', 190, 620), make_match('adventure', 280, 700),
                   make_match('bugbattle', 360, 780, 'pig1'), make_match('battle', 370, 700, 'pig2')]
        clicked = self.select_target(matches)
        self.assertEqual((360, 780), clicked)

    def test_abandon_without_blessing_pig(self):
        """全图没有可替换的祝福扑满时放弃。"""
        matches = [make_match('battle', 190, 500, 'pig4'), make_match('head', 280, 500),
                   make_match('bugbattle', 190, 620, 'reinforce1')]
        clicked = self.select_target(matches)
        self.assertIsNone(clicked)


if __name__ == "__main__":
    unittest.main()
