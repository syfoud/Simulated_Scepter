"""开局节点图未渲染完就识别导致「假账」的回归测试。

实测（复现脚本与数据见 dsh/_work/exp/）：底部「进入位面」按钮出现的瞬间，
节点图仍在逐个生成节点，此时识别会漏掉还没出现的节点，期望值随之偏低
（按钮刚出现时 0 个匹配、期望 0.0；约 0.3 秒后只有 8/13 个节点、期望 3.5；
渲染稳定后是 13 个节点、期望 8.5）。旧实现把第一次非 0 的识别结果直接
当成开局期望，于是本应继续打的开局被判成「期望过低」而提前退出，
kill_record.txt 里就留下了一条用时偏短的记录，也就是「假账」。

回归点：
1. 每一轮识别都必须重新截图，不能复用上一轮留下的旧画面；
2. 只有连续多次识别结果一致（节点图渲染稳定）才采信期望值；
3. 等待期内始终没稳定时不采信期望值，也不能据此提前退出；
4. 识别失败时用负数状态码记下原因，识别成功才把真实期望（含 0）写进
   kill_record.txt 的「开局期望」条目。
"""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from importing import load_img

# core.iron_blood.engine 在导入期会读取灰度模板，必须先预热图片缓存。
load_img()

from core.any_fate import engine as any_fate_engine
from core.iron_blood import engine as iron_blood_engine
from core.iron_blood.engine import IronBloodUniverse
from core.simulated.engine import SimulatedUniverse

EMPTY = "empty"      # 节点图还没出现
PARTIAL = "partial"  # 节点图正在逐个生成节点
STABLE = "stable"    # 节点图已经渲染完成
NO_BOSS = "noboss"   # 匹配到图标但首领节点还没出现


def make_matches(count, boss=True):
    """构造 count 个节点图标：最右侧是首领节点，其余在事件与奖励之间交替。"""
    names = ["event" if i % 2 else "reward" for i in range(count - 1)]
    names += ["head" if boss else "battle"]
    return [
        {"name": name, "location": (400 + i * 60, 300 + (i % 3) * 60), "similarity": 0.9}
        for i, name in enumerate(names)
    ]


# 节点数 8 对应「缺节点的图」（期望 4.0），13 对应稳定图（期望 6.5）
FRAME_MATCHES = {
    EMPTY: [],
    PARTIAL: make_matches(8),
    STABLE: make_matches(13),
    NO_BOSS: make_matches(8, boss=False),
}


def fake_build_graph(matches, **kwargs):
    """按匹配结果造出带权重的节点，权重之和即为期望值。"""
    nodes = [
        {"idx": i, "name": m["name"], "cx": float(m["location"][0]),
         "cy": float(m["location"][1]), "weight": 0.5, "similarity": m["similarity"]}
        for i, m in enumerate(matches)
    ]
    return nodes, {}, 0


def fake_max_weight_path(nodes, edges, start_idx):
    return list(nodes), round(sum(n["weight"] for n in nodes), 3), len(nodes) - 1


class FakeClock:
    """按固定步长前进的假时钟，让识别等待不必真的等到超时。"""

    def __init__(self, step=0.2):
        self.now = 0.0
        self.step = step

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, self.step)

    def strftime(self, fmt, *args):
        return time.strftime(fmt, *args)

    def localtime(self, *args):
        return time.localtime(*args)


def make_engine(frames):
    """构造只替换抓屏/点击的最小铁血战士实例，识别逻辑全部走真实实现。"""
    engine = object.__new__(IronBloodUniverse)
    engine.frames = list(frames)
    engine.refreshed = 0
    engine.saved = []
    engine.screen = "stale"  # 复用缓存截图会读到这一帧
    engine.opt = {"battle_weight": 1.2}
    engine.plane_floor = 1
    engine.chaoyan_seen = False
    engine.current_role = 1
    engine.debug = False
    engine.fail_match_count = 0
    engine.expectation_weight = 0
    engine.nodes = None
    engine.edges = None
    engine.path = None

    def get_screen():
        index = min(engine.refreshed, len(engine.frames) - 1)
        engine.refreshed += 1
        engine.screen = engine.frames[index]
        return engine.screen

    engine.get_screen = get_screen
    engine.click_text = lambda **kwargs: False
    engine.save_screen = lambda **kwargs: engine.saved.append(kwargs)
    return engine


def analysis_patches(clock=None, max_weight_path=None):
    """识图流水线的打桩补丁：模板匹配、建图、寻路与时钟全部替换成可控实现。"""
    return [
        patch.object(any_fate_engine, "match_multiple_targets",
                     side_effect=lambda image, mode=1: list(FRAME_MATCHES[image])),
        patch.object(any_fate_engine, "detect_corner_markers", return_value=[]),
        patch.object(any_fate_engine, "build_rightward_graph",
                     side_effect=fake_build_graph),
        patch.object(any_fate_engine, "max_weight_path",
                     side_effect=max_weight_path or fake_max_weight_path),
        patch.object(any_fate_engine, "evaluate_best_single_replacement",
                     return_value=(None, 0.0, None, None, 0.0, 0.0)),
        patch.object(any_fate_engine, "compute_all_max_steps", return_value={}),
        patch.object(any_fate_engine, "CUS_LOGGER"),
        patch.object(any_fate_engine, "time", clock or FakeClock()),
    ]


class MapReadyTest(unittest.TestCase):
    def patch_analysis(self, clock=None):
        """打桩识图、建图与时钟，返回（识图桩，日志桩）。"""
        for patcher in analysis_patches(clock):
            self.enterContext(patcher)
        return any_fate_engine.match_multiple_targets, any_fate_engine.CUS_LOGGER

    def test_partial_map_is_not_trusted_until_stable(self):
        """缺节点的图给出的低期望必须被丢弃，只采信渲染稳定后的结果。"""
        engine = make_engine([PARTIAL, STABLE, STABLE, STABLE])
        self.patch_analysis(FakeClock())

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_OK,
                         engine.analyze_map_until_stable(1, 1))
        # 第一次识别到的 PARTIAL 图期望只有 4.0，稳定图是 6.5
        self.assertEqual(6.5, engine.expectation_weight)
        # 等渲染稳定用了 4 次匹配，完整识别复用稳定帧、不再重新截图
        self.assertEqual(4, engine.refreshed)

    def test_every_round_captures_a_fresh_screen(self):
        """每一轮识别都必须重新截图，不能复用上一轮留下的旧画面。"""
        engine = make_engine([PARTIAL, STABLE, STABLE, STABLE])
        matcher, _ = self.patch_analysis(FakeClock())

        engine.analyze_map_until_stable(1, 1)

        # 等渲染稳定匹配 4 次；完整识别复用稳定帧的匹配结果，不重复匹配
        self.assertEqual([PARTIAL, STABLE, STABLE, STABLE],
                         [call.args[0] for call in matcher.call_args_list])
        self.assertNotIn("stale", [call.args[0] for call in matcher.call_args_list])
        self.assertEqual(4, engine.refreshed)

    def test_corner_detection_runs_only_once(self):
        """等渲染期间只做便宜的图标匹配，昂贵的角标检测只对稳定的图做一次。"""
        engine = make_engine([PARTIAL, STABLE, STABLE, STABLE])
        self.patch_analysis(FakeClock())

        engine.analyze_map_until_stable(1, 1)

        self.assertEqual(1, any_fate_engine.detect_corner_markers.call_count)
        # 完整识别跑在判定稳定的那张画面上，而不是又截一张更新的画面
        self.assertEqual(STABLE, any_fate_engine.detect_corner_markers.call_args.args[0])

    def test_unstable_map_is_never_trusted(self):
        """等待期内一直没稳定时不采信期望值，也不留下可用于退出判断的读数。"""
        clock = FakeClock()
        engine = make_engine([PARTIAL, STABLE] * 200)
        self.patch_analysis(clock)
        logger = any_fate_engine.CUS_LOGGER

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_TIMEOUT,
                         engine.analyze_map_until_stable(1, 1))
        self.assertEqual(0, engine.expectation_weight)
        self.assertEqual(1, logger.warning.call_count)
        self.assertLessEqual(clock.now, 11)  # 等待上限 10 秒，允许一次循环的额外步进

    def test_empty_map_is_waited_for_without_debug_dumps(self):
        """节点图还没出现时继续等待，且不反复写 bigmaperror 调试截图。"""
        engine = make_engine([EMPTY, EMPTY, STABLE, STABLE, STABLE])
        self.patch_analysis(FakeClock())

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_OK,
                         engine.analyze_map_until_stable(1, 1))

        # 节点图还没出现时一直等（前两次匹配为空），稳定后再完整识别一次
        self.assertEqual(5, engine.refreshed)
        self.assertEqual(6.5, engine.expectation_weight)
        self.assertEqual(0, engine.fail_match_count)
        self.assertEqual([], engine.saved)


class AnalysisStatusTest(unittest.TestCase):
    """识别失败时返回负数状态码，便于事后分辨失败原因。"""

    def analyze(self, engine, max_weight_path=None):
        for patcher in analysis_patches(max_weight_path=max_weight_path):
            self.enterContext(patcher)
        return engine.analyze_map_until_stable(1, 1)

    def test_success_reports_ok(self):
        engine = make_engine([STABLE] * 5)

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_OK, self.analyze(engine))

    def test_never_stable_reports_timeout(self):
        """每一轮都能识图，但画面一直在变，等不到稳定。"""
        engine = make_engine([PARTIAL, STABLE] * 200)

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_TIMEOUT, self.analyze(engine))

    def test_no_icon_reports_no_match(self):
        engine = make_engine([EMPTY] * 200)

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_NO_MATCH, self.analyze(engine))

    def test_missing_boss_reports_no_boss(self):
        engine = make_engine([NO_BOSS] * 200)

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_NO_BOSS, self.analyze(engine))

    def test_no_valid_path_reports_no_path(self):
        engine = make_engine([STABLE] * 200)

        self.assertEqual(
            IronBloodUniverse.MAP_ANALYSIS_NO_PATH,
            self.analyze(engine, max_weight_path=lambda *args, **kwargs: ([], 0.0, None)))


class InitingMapTest(unittest.TestCase):
    """「进入位面」后的开局期望识别：先点击再识别，只有确认成功才参与退出判断。"""

    def run_initing_map(self, confirmed, weight=0.0, render_ok=True, early_stop=True):
        engine = object.__new__(IronBloodUniverse)
        engine.plane_floor = -1
        engine.early_stop = early_stop
        engine.gwypzmgzcndqlp = True
        engine.first_plane_min_weight = 8.0
        engine.first_plane_weight = 0
        engine.need_end = False
        engine.expectation_weight = 0
        engine.third_plane_pause_count = 0
        engine.kill_count = 0
        engine.node_count = 3
        engine.new_node = False
        engine.clicks = []
        engine.events = []
        engine.captured = None
        engine.stable_frame = ("stable-image", "stable-matches")

        def click_text(**kwargs):
            engine.clicks.append(kwargs.get("text"))
            if kwargs.get("text") == "进入位面":
                engine.events.append("click")
            return kwargs.get("text") == "振翅"

        def wait_map_rendered(mode):
            engine.events.append("wait")
            if render_ok:
                return engine.MAP_ANALYSIS_OK, engine.stable_frame
            return engine.MAP_ANALYSIS_TIMEOUT, None

        def analyze_map_until_stable(mode, path_mode, captured=None):
            engine.events.append("analyze")
            engine.captured = captured
            if confirmed:
                engine.expectation_weight = weight
                return engine.MAP_ANALYSIS_OK
            return engine.MAP_ANALYSIS_TIMEOUT

        engine.click_text = click_text
        engine.wait_map_rendered = wait_map_rendered
        engine.analyze_map_until_stable = analyze_map_until_stable
        with patch.object(iron_blood_engine, "key_mouse_manager"), \
                patch.object(iron_blood_engine, "CUS_LOGGER"):
            engine.initing_map()
        return engine

    def test_clicks_before_expensive_analysis(self):
        """点「进入位面」不必等识别结果，耗时的识别挪到游戏播入场动画期间做。"""
        engine = self.run_initing_map(True, 6.5)

        self.assertEqual(["wait", "click", "analyze"], engine.events)
        self.assertEqual(engine.stable_frame, engine.captured)

    def test_unstable_map_skips_analysis_and_never_stops_the_run(self):
        """先点击后识别时，节点图没稳定同样不采信期望值、不提前退出。"""
        engine = self.run_initing_map(True, 6.5, render_ok=False)

        self.assertNotIn("analyze", engine.events)
        self.assertEqual(1, engine.clicks.count("进入位面"))
        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_TIMEOUT, engine.first_plane_weight)
        self.assertFalse(engine.need_end)

    def test_confirmed_low_expectation_still_stops_the_run(self):
        engine = self.run_initing_map(True, 6.5)

        self.assertEqual(6.5, engine.first_plane_weight)
        self.assertTrue(engine.need_end)
        self.assertEqual(1, engine.clicks.count("进入位面"))

    def test_confirmed_good_expectation_keeps_the_run(self):
        engine = self.run_initing_map(True, 8.5)

        self.assertEqual(8.5, engine.first_plane_weight)
        self.assertFalse(engine.need_end)

    def test_expectation_is_recorded_even_when_early_stop_is_off(self):
        """记录开局期望与「是否据此提前退出」解耦：关掉提前退出也照样留下读数。"""
        engine = self.run_initing_map(True, 6.5, early_stop=False)

        self.assertEqual(6.5, engine.first_plane_weight)
        self.assertFalse(engine.need_end)

    def test_unconfirmed_expectation_never_stops_the_run(self):
        """识别没确认成功时不得提前退出，这正是「假账」要根治的地方。"""
        engine = self.run_initing_map(False)

        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_TIMEOUT, engine.first_plane_weight)
        self.assertFalse(engine.need_end)
        self.assertEqual(1, engine.clicks.count("进入位面"))


class RecordLineTest(unittest.TestCase):
    """kill_record.txt 一定会写「开局期望」：确认识别写真实值（含 0），失败/未识别写负数原因码。"""

    def write_record(self, weight, restart_first=False):
        engine = object.__new__(IronBloodUniverse)
        engine.plane_floor = 1
        engine.kill_count = 3
        engine.count = 447
        engine.run_start_time = 1700000000.0
        engine.first_plane_weight = weight
        engine.need_end = True
        engine.record = False  # 关掉录像分支，只验证每局计数的重置
        engine.stop = lambda: None
        clock = FakeClock()
        clock.now = engine.run_start_time + 23.0
        self.last_engine = engine  # 供用例在记录写完后继续断言引擎状态
        with TemporaryDirectory() as backup:
            with patch.object(iron_blood_engine, "PATHS", {"backup": backup}), \
                    patch.object(iron_blood_engine, "time", clock), \
                    patch.object(SimulatedUniverse, "end_of_university", lambda self: None), \
                    patch.object(IronBloodUniverse, "init_map", lambda self: None), \
                    patch.object(iron_blood_engine, "CUS_LOGGER") as logger:
                if restart_first:
                    engine.restart_recording()
                engine.end_of_university()
                # 写文件失败会被 end_of_university 吞掉并记 error，这里显式暴露
                self.assertFalse(logger.error.called)
            return Path(backup, "kill_record.txt").read_text(encoding="utf-8")

    def test_confirmed_expectation_is_written(self):
        line = self.write_record(3.5)

        self.assertIn("开局期望:3.50", line)
        self.assertIn("用时:0分23秒", line)

    def test_confirmed_zero_expectation_is_still_written(self):
        """确认识别到的 0 期望是真读数，照常写入记录；旧实现会漏掉这一条。"""
        line = self.write_record(0)

        self.assertIn("开局期望:0.00", line)

    def test_failure_reason_is_written_as_negative_weight(self):
        """识别失败时把原因码写成负数，便于事后分辨失败类型；负数原因码不留小数。"""
        line = self.write_record(IronBloodUniverse.MAP_ANALYSIS_NO_MATCH)

        self.assertIn("开局期望:-2", line)

    def test_restart_before_the_record_writes_no_init_code(self):
        """开局期望只在本局内有效，进入下一轮回时立刻重置为 -5。

        结算界面同时含「来自黑塔的分析报告」和「点击空白」两个 trigger，识别先后顺序
        在小概率下会让 end_of_university 根本执行不到，所以重置放在 restart_recording。
        """
        line = self.write_record(3.5, restart_first=True)

        self.assertIn("开局期望:-5", line)

    def test_expectation_is_cleared_when_next_round_starts(self):
        """本局记录写完后读数仍然保留，等下一轮开始时才重置为「还没做开局识别」。"""
        self.write_record(3.5)

        self.assertEqual(3.5, self.last_engine.first_plane_weight)
        self.last_engine.restart_recording()
        self.assertEqual(IronBloodUniverse.MAP_ANALYSIS_NO_INIT,
                         self.last_engine.first_plane_weight)

    def test_run_without_analysis_records_no_init_code(self):
        """已经在模拟宇宙里直接开局时走不到识别流程，记录里写 -5，而不是少一个字段。"""
        line = self.write_record(IronBloodUniverse.MAP_ANALYSIS_NO_INIT)

        self.assertIn("开局期望:-5", line)
        self.assertIn("用时:0分23秒", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
