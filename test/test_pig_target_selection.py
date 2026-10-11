"""「毁灭·战争崇拜」扑满信标替换目标的选择规则。"""

import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tool.utils.analysis_map import (
    build_rightward_graph,
    max_weight_path,
    select_pig_target,
)
from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

IronBloodUniverse = importlib.import_module("core.iron_blood.engine").IronBloodUniverse


def make_start(idx, cx, cy):
    """构造起点节点，orig 为 None，与 build_rightward_graph 一致。"""
    return {'idx': idx, 'name': 'start', 'cx': float(cx), 'cy': float(cy), 'w': 50, 'h': 50,
            'weight': 0.0, 'similarity': 0.0, 'orig': None}


def make_node(idx, name, cx, cy, marker=None):
    """构造地图节点；marker 为角标模板名，None 表示无角标。"""
    match = {'name': name, 'location': (cx, cy), 'size': (20, 20), 'similarity': 0.9}
    if marker is not None:
        match['corner_marker'] = {'name': marker, 'location': (cx + 8, cy + 8),
                                  'size': (20, 20), 'similarity': 0.9, 'node_idx': idx}
    return {'idx': idx, 'name': name, 'cx': float(cx), 'cy': float(cy), 'w': 20, 'h': 20,
            'weight': 1.0, 'similarity': 0.9, 'orig': match}


def make_match(name, cx, cy, marker=None, size=70):
    """构造 match_multiple_targets 的输出项，用于走真实建图流程。"""
    match = {'name': name, 'location': (cx - size / 2, cy - size / 2), 'size': (size, size),
             'similarity': 0.9}
    if marker is not None:
        match['corner_marker'] = {'name': marker, 'location': (cx + 10, cy + 10),
                                  'size': (20, 20), 'similarity': 0.9, 'node_idx': None}
    return match


class SelectPigTargetTests(unittest.TestCase):
    """select_pig_target 的挑选顺序。"""

    def test_path_pig_wins(self):
        start = make_start(0, 0, 500)
        near = make_node(1, 'battle', 100, 500, 'pig1')
        far = make_node(2, 'battle', 300, 500, 'pig2')
        side = make_node(3, 'bugbattle', 200, 400, 'pig2')
        nodes = [start, near, far, side]
        edges = {0: [1, 3], 1: [2], 2: [], 3: [2]}

        target = select_pig_target(nodes, edges, 0, [start, near, far])

        # 最佳路径上离起点最近的祝福扑满优先，绕路分支上的信标不参与
        self.assertIs(target, near)

    def test_fallback_prefers_battle_area(self):
        start = make_start(0, 0, 500)
        elite = make_node(1, 'elite', 100, 400, 'pig1')
        bugbattle = make_node(2, 'bugbattle', 150, 400, 'pig2')
        battle = make_node(3, 'battle', 400, 500, 'pig1')
        plain = make_node(4, 'event', 200, 500)
        nodes = [start, elite, bugbattle, battle, plain]
        edges = {0: [1, 2, 3, 4], 1: [], 2: [], 3: [], 4: []}

        target = select_pig_target(nodes, edges, 0, [start, plain])

        # 最佳路径无可替换信标：战斗格优先于更近的战斗·虫群格，
        # 精英格即使带祝福扑满也不替换
        self.assertIs(target, battle)

    def test_fallback_prefers_nearer_same_rank(self):
        start = make_start(0, 0, 500)
        bugbattle = make_node(1, 'bugbattle', 80, 500, 'pig1')
        battle_far = make_node(2, 'battle', 500, 500, 'pig1')
        battle_near = make_node(3, 'battle', 200, 400, 'pig2')
        plain = make_node(4, 'event', 300, 500)
        nodes = [start, bugbattle, battle_far, battle_near, plain]
        edges = {0: [1, 2, 3, 4], 1: [], 2: [], 3: [], 4: []}

        target = select_pig_target(nodes, edges, 0, [start, plain])

        # 同级取离起点最近的
        self.assertIs(target, battle_near)

    def test_unreachable_pig_is_ignored(self):
        start = make_start(0, 0, 500)
        unreachable = make_node(1, 'battle', 100, 100, 'pig1')
        plain = make_node(2, 'event', 300, 500)
        reachable = make_node(3, 'battle', 500, 500, 'pig2')
        nodes = [start, unreachable, plain, reachable]
        edges = {0: [2, 3], 1: [], 2: [], 3: []}

        target = select_pig_target(nodes, edges, 0, [start, plain])

        # 永远走不进去的区域即使更靠左也不参与
        self.assertIs(target, reachable)

    def test_only_unreachable_pig_returns_none(self):
        start = make_start(0, 0, 500)
        plain = make_node(1, 'event', 300, 500)
        unreachable = make_node(2, 'battle', 250, 100, 'pig1')
        nodes = [start, plain, unreachable]
        edges = {0: [1], 1: [], 2: []}

        target = select_pig_target(nodes, edges, 0, [start, plain])

        self.assertIsNone(target)

    def test_unreplaceable_path_nodes_fall_back(self):
        start = make_start(0, 0, 500)
        elite = make_node(1, 'elite', 100, 500, 'pig1')
        treasure = make_node(2, 'battle', 200, 500, 'pig4')
        battle = make_node(3, 'battle', 500, 400, 'pig2')
        nodes = [start, elite, treasure, battle]
        edges = {0: [1, 3], 1: [2], 2: [], 3: []}

        target = select_pig_target(nodes, edges, 0, [start, elite, treasure])

        # 最佳路径上的精英格与奇物扑满都不可替换，按区域优先级改用战斗格
        self.assertIs(target, battle)

    def test_blessing_pig_templates_are_replaceable(self):
        for marker in ('pig1', 'pig2'):
            with self.subTest(marker=marker):
                start = make_start(0, 0, 500)
                pig = make_node(1, 'battle', 300, 500, marker)
                plain = make_node(2, 'event', 100, 500)
                nodes = [start, pig, plain]
                edges = {0: [1, 2], 1: [], 2: []}

                target = select_pig_target(nodes, edges, 0, [start, plain])

                self.assertIs(target, pig)

    def test_treasure_pig_templates_are_not_replaced(self):
        for marker in ('pig3', 'pig4'):
            with self.subTest(marker=marker):
                start = make_start(0, 0, 500)
                pig = make_node(1, 'battle', 300, 500, marker)
                plain = make_node(2, 'event', 100, 500)
                nodes = [start, pig, plain]
                edges = {0: [1, 2], 1: [], 2: []}

                target = select_pig_target(nodes, edges, 0, [start, plain])

                self.assertIsNone(target)

    def test_other_corner_marker_is_not_pig(self):
        start = make_start(0, 0, 500)
        marked = make_node(1, 'battle', 300, 500, 'reinforce1')
        plain = make_node(2, 'event', 100, 500)
        nodes = [start, marked, plain]
        edges = {0: [1, 2], 1: [], 2: []}

        target = select_pig_target(nodes, edges, 0, [start, plain])

        self.assertIsNone(target)


class PigTargetGraphTests(unittest.TestCase):
    """走真实建图流程，确认不可达区域不会成为替换目标。"""

    def test_unreachable_area_is_not_replaced(self):
        # 起点在最下排；最上排的战斗格水平位置在起点右侧，但垂直偏移超出单步限制
        matches = [make_match('battle', 240, 100, marker='pig1'),
                   make_match('event', 240, 500)]
        nodes, edges, start_idx = build_rightward_graph(matches, start=(100, 500))
        path, _, _ = max_weight_path(nodes, edges, start_idx)
        top = next(n for n in nodes if n['name'] == 'battle')
        start = next(n for n in nodes if n['idx'] == start_idx)

        # 旧实现只看 cx >= start_cx，会把这个走不到的战斗格当成可替换目标
        self.assertGreater(top['cx'], start['cx'])
        self.assertEqual([n['name'] for n in path], ['start', 'event'])
        self.assertIsNone(select_pig_target(nodes, edges, start_idx, path))

    def test_reachable_off_path_area_is_replaced(self):
        # 上排战斗·虫群格带祝福扑满信标且可达，但下排两个战斗格权重更高，最佳路径不经过它
        matches = [make_match('battle', 240, 500),
                   make_match('event', 240, 420),
                   make_match('battle', 380, 500),
                   make_match('bugbattle', 380, 420, marker='pig2')]
        nodes, edges, start_idx = build_rightward_graph(matches, start=(100, 500))
        path, _, _ = max_weight_path(nodes, edges, start_idx)
        pig = next(n for n in nodes if n['name'] == 'bugbattle')

        self.assertEqual([n['name'] for n in path], ['start', 'battle', 'battle'])
        self.assertIs(select_pig_target(nodes, edges, start_idx, path), pig)


class IsPigNodeTests(unittest.TestCase):
    """is_pig_node（祝福扑满切人策略）复用同一判定。"""

    def test_only_blessing_pig_counts(self):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.start_nodes = make_node(0, 'battle', 100, 500, 'pig2')

        self.assertTrue(universe.is_pig_node())

        universe.start_nodes = make_node(0, 'battle', 100, 500, 'pig3')
        self.assertFalse(universe.is_pig_node())


class WarWorshipSelectDoingTests(unittest.TestCase):
    """select_doing 的战争崇拜分支使用新的挑选规则。"""

    @staticmethod
    def make_universe(nodes, edges, path, start):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.ts = Mock()
        universe.ts.find_with_box.return_value = [{'raw_text': '战争崇拜', 'box': [0, 100, 0, 30]}]
        universe.nodes = nodes
        universe.edges = edges
        universe.path = path
        universe.start_nodes = start
        universe.try_analysis_map = Mock()
        universe.click_text = Mock(return_value=False)
        universe.abandon_confirm = Mock()
        return universe

    def test_clicks_selected_pig_area(self):
        start = make_start(0, 0, 500)
        pig = make_node(1, 'battle', 120, 480, 'pig2')
        plain = make_node(2, 'event', 300, 500)
        universe = self.make_universe([start, pig, plain], {0: [1, 2], 1: [], 2: []},
                                      [start, plain], start)
        manager = Mock()

        with patch("core.iron_blood.engine.key_mouse_manager", manager):
            universe.select_doing()

        universe.try_analysis_map.assert_called_once_with(mode=2, path_mode=1)
        manager.click.assert_called_once_with(120, 480)
        universe.click_text.assert_any_call(text="确认目标", box=[1635, 1735, 968, 996])
        universe.abandon_confirm.assert_not_called()

    def test_abandons_when_no_pig_area(self):
        start = make_start(0, 0, 500)
        plain = make_node(1, 'event', 300, 500)
        battle = make_node(2, 'battle', 500, 500)
        universe = self.make_universe([start, plain, battle], {0: [1, 2], 1: [], 2: []},
                                      [start, plain], start)
        manager = Mock()

        with patch("core.iron_blood.engine.key_mouse_manager", manager):
            universe.select_doing()

        manager.click.assert_not_called()
        universe.abandon_confirm.assert_called_once_with(confirm=True)


if __name__ == "__main__":
    unittest.main()
