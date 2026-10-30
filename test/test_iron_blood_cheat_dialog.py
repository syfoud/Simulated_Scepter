"""
铁血战士重投界面（``calculated_roll``）与作弊选项窗的回归测试。

背景（日志 log_2026-10-20-18-54.txt，23:32:31~23:32:50 连续 4 次失败、第 5 次成功）：
点掷骰界面右下角的「作弊」按钮后，背景的「确认效果」仍然识别得到，于是「重投界面」状态在作弊
选项窗开着时照样触发，跑到 ``calculated_roll`` 里读上一轮的骰面效果、再派发点击；而旧的 ``cheat()``
是盲拖 ``drag(0.5, 0.4, 0.5, 0.8)`` + 盲点 ``click(571, 622)`` + 固定框点「确认」，从不看窗口还在不在。
窗口被误点关掉之后，后面的操作全落在空白页面上，作弊白白失败。

当前生产契约（``core/iron_blood/engine.py`` 的 ``calculated_roll``）：
- 先探窗口顶部的「作弊」标题（``click_text(text="作弊", box=[923,996,230,270], click=False,
  allow_fail=True)``）：命中就说明作弊选项窗还开着，debug「作弊选项窗还开着，先不处理重投界面」
  并直接返回，不读效果文本、不做决策；单独「打开作弊窗」的助手已经没有了；
- 重投界面先读当前效果文本（``ts.find_with_box(box=[1339,1576,429,464], forward=True, re_screen=False)``），
  文本里已经带「肉体」就完全不做决策动作，直接点「确认效果」；
- 否则用 ``check("zero")`` 分别判断「作弊」与「重投」两个按钮是否可用；
- 要做决策就调 ``evaluate_best_single_replacement``（第三位面 t=0.3、其它 t=0.2），再看替换节点；
- 决定作弊时**先**把 ``self.cheat_target`` 写成 ``"肉体帝侯"``，**再**点一次「作弊」按钮
  ``box=[1261,1321,761,792]``，点完立即 ``return``（不点「确认效果」、不 ``init_map``、``mini_state`` 不变）；
  点按钮失败只 warning「没点到「作弊」按钮」，仍然 ``return``；
- 决定重投时点一次「重投」``box=[1599,1657,760,795]`` 后 ``return``；
- 什么决策都不做才点「确认效果」``box=[1584,1687,961,994]``，再 ``init_map()``、``mini_state = 1``。

作弊选项窗的选行/确认由公共 ``AnyFateUniverse.cheat()`` 负责（点「作弊」按钮、开窗都在各模式
``calculated_roll`` 里完成）；这里用替身锁定它「先滚到目标行、看到高亮、再确认，找不到就 esc 退出，
绝不再用旧的盲拖 + 盲点」。

替身不需要游戏：OCR 结果由 ``ts.find_with_box`` 按区域返回，键鼠操作被记录下来。
"""

import types
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from importing import load_img

# core.iron_blood.engine 在导入期会读取灰度模板，必须先预热图片缓存。
load_img()

from core.any_fate import engine as any_fate_engine
from core.iron_blood import engine as iron_blood_engine
from core.iron_blood.engine import IronBloodUniverse


def center(box):
    return (box[0] + box[1]) / 2, (box[2] + box[3]) / 2


def line(text, box):
    return {"raw_text": text, "box": list(box)}


# 重投界面上的固定区域：当前效果文本、快速投掷、作弊、重投、确认效果（均为 1920x1080 基准）
EFFECT_BOX = [1339, 1576, 429, 464]
FAST_ROLL_BOX = [1700, 1823, 80, 117]
CHEAT_BUTTON_BOX = [1261, 1321, 761, 792]
REDO_BOX = [1599, 1657, 760, 795]
CONFIRM_EFFECT_BOX = [1584, 1687, 961, 994]

# 作弊选项窗里的固定文字：标题、底部「确认」，以及列表里的两行（目标是带「肉体」的肉体帝侯）
TITLE = line("作弊", [940, 985, 240, 268])
CONFIRM = line("确认", [1168, 1223, 811, 841])
FLESH_TITLE = line("【毁灭·肉体帝侯】", [470, 700, 828, 854])
FLESH_DESC = line("选择1个区域，为其附加【肉体帝侯】效果", [560, 1440, 860, 887])
SELF_DESTRUCT_TITLE = line("【毁灭·精神自毁】", [470, 700, 690, 716])


class CalculatedRollTest(unittest.TestCase):
    """``calculated_roll`` 的分支：读效果 → 决策 → 点按钮或点「确认效果」。"""

    def setUp(self):
        self.manager = self.enterContext(patch.object(iron_blood_engine, "key_mouse_manager", Mock()))
        self.logger = self.enterContext(patch.object(iron_blood_engine, "CUS_LOGGER", Mock()))
        self.any_fate_logger = self.enterContext(patch.object(any_fate_engine, "CUS_LOGGER", Mock()))
        # 重投/作弊次数都由 any_fate 的 read_action_counts 统一读，所以补丁打在那边
        self.roll_count = self.enterContext(
            patch.object(any_fate_engine, "match_roll_count_in_region", Mock(return_value=1)))
        self.cheat_count = self.enterContext(
            patch.object(any_fate_engine, "match_cheat_count_in_region", Mock(return_value=2)))
        self.locked_roll_count = self.enterContext(
            patch.object(any_fate_engine, "match_locked_roll_count_in_region", Mock(return_value=None)))
        self.find_image = self.enterContext(
            patch.object(iron_blood_engine, "find_image_by_name", Mock(return_value="inmap.png")))
        # 默认给一个「只有当前节点」的路径：任何测试都不该意外走进决策分支还点下去
        self.evaluate = self.enterContext(patch.object(
            iron_blood_engine, "evaluate_best_single_replacement",
            Mock(return_value=([{"idx": 0}], 0.0, 0, 0, 0.0, 0.0))))

    @staticmethod
    def _check(fast_rolled, cheating, redo):
        """按引擎的调用方式返回 check() 结果：命中 zero 模板表示「该按钮不可用」。"""
        def check(path, x=0.0, y=0.0, **kwargs):
            if path == "fast_roll":
                return fast_rolled
            if path == "zero":
                # check 的 x/y 是 1920x1080 像素坐标（原点客户区左上角）：
                # 「作弊」按钮点 (1335, 721)，「重投」按钮点 (1671, 722)。
                # 用精确点位而不是「随便什么点」断言生产代码真的在对应的按钮上取样。
                if (x, y) == (1335, 721):
                    return not cheating
                if (x, y) == (1671, 722):
                    return not redo
                raise AssertionError(f"未预料的「zero」点位：{x}, {y}")
            raise AssertionError(f"未预料的 check 调用：{path}")
        return check

    def make_engine(self, plane_floor=2, effect="毁灭精神自毁", fast_rolled=True,
                    cheating=False, redo=False, cheat_window_open=False):
        engine = object.__new__(IronBloodUniverse)
        engine.xx, engine.yy = 1920, 1080
        engine.nodes = {"0": {"idx": 0}}
        engine.edges = {"0": []}
        engine.start_nodes = {"idx": 0}
        engine.plane_floor = plane_floor
        engine.screen = "screen"
        engine.mini_state = 0
        engine.replace_idx = None
        engine.cheat_target = None
        engine.ts = Mock()
        engine.ts.find_with_box = Mock(return_value=[line(effect, EFFECT_BOX)])
        engine.check = Mock(side_effect=self._check(fast_rolled, cheating, redo))
        engine.cheat_window_open = cheat_window_open
        engine.click_text = Mock(side_effect=self._click_text(engine))
        engine.click_target = Mock()
        engine.init_map = Mock()
        return engine

    @staticmethod
    def _click_text(engine):
        """开头「作弊窗开着吗」的探测（click=False）按 cheat_window_open 回话，
        其它按钮一律当作点到了。"""
        def click_text(text, **kwargs):
            if text == "作弊" and kwargs.get("click") is False:
                return engine.cheat_window_open
            return True
        return click_text

    def click_text_calls(self, engine):
        """去掉开头那次只识别不点击的作弊窗探测，只看真正点按钮的调用。"""
        return [item for item in engine.click_text.call_args_list
                if item.kwargs.get("click", True)]

    def assertClickedText(self, engine, **expected):
        self.assertEqual(self.click_text_calls(engine), [call(**expected)])

    def stub_best_path(self, best_path, replace_idx):
        """让 evaluate_best_single_replacement 返回指定路径/替换节点。"""
        self.evaluate.return_value = (best_path, 1.0, 1, replace_idx, 0.5, 0.4)

    def debug_log(self):
        # 次数日志是 any_fate 的 read_action_counts 写的，两个 logger 的 debug 都要看
        return str(self.logger.debug.call_args_list) + str(self.any_fate_logger.debug.call_args_list)

    # ---- 提前返回：还没有地图 ----

    def test_steps_back_to_the_map_when_there_is_no_map_yet(self):
        """还没进地图（nodes 为 None）：点「inmap」回地图，不读效果、不点任何按钮。"""
        engine = self.make_engine()
        engine.nodes = None
        engine.calculated_roll()
        engine.click_target.assert_called_once_with("inmap.png", 0.9, flag=False, click=True)
        self.assertIn("inmap", str(self.find_image.call_args))
        self.manager.wait.assert_called_once()
        self.assertEqual(self.click_text_calls(engine), [])
        engine.ts.find_with_box.assert_not_called()
        engine.init_map.assert_not_called()
        self.assertEqual(engine.mini_state, 0)
        self.roll_count.assert_not_called()

    def test_steps_back_to_the_map_when_the_plane_is_unknown(self):
        """plane_floor == -1 同样回地图：不能拿不存在的位面做决策。"""
        engine = self.make_engine(plane_floor=-1)
        engine.calculated_roll()
        engine.click_target.assert_called_once()
        self.assertEqual(self.click_text_calls(engine), [])
        engine.init_map.assert_not_called()
        self.roll_count.assert_not_called()

    # ---- 提前返回：作弊窗还开着 ----

    def test_does_nothing_while_the_cheat_window_is_open(self):
        """点完「作弊」后窗口弹着的这段时间「重投界面」又触发：什么都不做。

        这时背景的「确认效果」照样认得到，真跑下去会再点一次「作弊」，
        那一下落到已经打开的列表上，可能选中别的骰面。
        """
        engine = self.make_engine(plane_floor=2, cheating=True, cheat_window_open=True)
        self.stub_best_path([{"idx": 0}, {"idx": 1}], replace_idx=1)
        engine.calculated_roll()
        self.assertIn("作弊选项窗还开着", self.debug_log())
        self.assertEqual(self.click_text_calls(engine), [])
        self.roll_count.assert_not_called()
        self.evaluate.assert_not_called()
        engine.init_map.assert_not_called()
        self.assertEqual(engine.mini_state, 0)

    # ---- 正常路径 ----

    def test_normal_screen_confirms_the_effect(self):
        """既不作弊也不重投：点一次「确认效果」、初始化地图、状态切回 1。"""
        engine = self.make_engine(cheating=False, redo=False)
        engine.calculated_roll()
        self.roll_count.assert_called_once_with("screen", save_unmatched=False)
        self.cheat_count.assert_called_once_with("screen", save_unmatched=False)
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)
        self.evaluate.assert_not_called()

    def test_locked_cheat_does_not_click_the_missing_cheat_button(self):
        """没解锁作弊（次数读成 0）：那个「作弊」按钮根本不存在，不能去点，
        也不要因为「zero」模板认不到就当作弊，直接按没有作弊走下去。"""
        self.roll_count.return_value = None
        self.cheat_count.return_value = None
        self.locked_roll_count.return_value = 3
        engine = self.make_engine(cheating=True, redo=False)

        engine.calculated_roll()

        self.assertNotIn("作弊", [item.kwargs.get("text")
                                  for item in self.click_text_calls(engine)])
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        self.assertIsNone(engine.cheat_target)
        self.assertEqual(engine.mini_state, 1)
        self.assertIn("尚未解锁作弊功能", str(self.any_fate_logger.warning.call_args_list))
        self.assertIn("当前重投次数", self.debug_log())
        # 居中点位认到了就说明那两个点位本来就是空白，不该再回去落两张空样本
        self.assertEqual(self.roll_count.call_count, 1)
        self.assertEqual(self.cheat_count.call_count, 1)

    def test_effect_with_flesh_skips_the_decision(self):
        """当前效果文本里已带「肉体」：不做决策（不评估、不点作弊/重投），直接确认效果。"""
        engine = self.make_engine(effect="毁灭肉体帝侯", cheating=True, redo=True)
        engine.calculated_roll()
        engine.ts.find_with_box.assert_called_once_with(
            box=EFFECT_BOX, forward=True, re_screen=False)
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        self.evaluate.assert_not_called()
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)

    def test_plane_floor_one_does_not_read_the_effect(self):
        """第一位面不读当前效果文本（第二位面、第三位面才读），直接确认。"""
        engine = self.make_engine(plane_floor=1, cheating=True)
        engine.calculated_roll()
        engine.ts.find_with_box.assert_not_called()
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        self.evaluate.assert_not_called()
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)

    def test_fast_roll_button_is_clicked_before_the_effect_is_confirmed(self):
        """「快速投掷」还没点过时先点它，顺序必须早于「确认效果」。"""
        engine = self.make_engine(plane_floor=1, fast_rolled=False)
        engine.calculated_roll()
        self.assertEqual(self.click_text_calls(engine), [
            call(text="快速投掷", box=FAST_ROLL_BOX),
            call(text="确认效果", box=CONFIRM_EFFECT_BOX),
        ])

    def test_roll_and_cheat_counts_are_logged(self):
        """重投/作弊次数从当前画面读出来，识别到就写日志。"""
        self.roll_count.return_value = 3
        self.cheat_count.return_value = 4
        engine = self.make_engine(plane_floor=1)
        engine.calculated_roll()
        logged = self.debug_log()
        self.assertIn("当前重投次数: 3", logged)
        self.assertIn("当前作弊次数: 4", logged)

    def test_missing_counts_are_not_logged(self):
        """识别不到次数（None）时不更新、不写日志，也不能崩。"""
        self.roll_count.return_value = None
        self.cheat_count.return_value = None
        engine = self.make_engine(plane_floor=1)
        engine.calculated_roll()
        logged = self.debug_log()
        self.assertNotIn("当前重投次数", logged)
        self.assertNotIn("当前作弊次数", logged)
        self.assertEqual(engine.mini_state, 1)

    # ---- 作弊分支 ----

    def test_cheat_branch_writes_target_then_clicks_cheat_once_and_returns(self):
        """作弊分支：先写 cheat_target 再点一次「作弊」，点完立刻返回，不再点「确认效果」。"""
        engine = self.make_engine(plane_floor=2, cheating=True)
        self.stub_best_path([{"idx": 0}, {"idx": 1}], replace_idx=1)
        seen_targets = []
        def click_text(text, **kwargs):
            if text == "作弊" and kwargs.get("click") is False:
                return False
            seen_targets.append(engine.cheat_target)
            return True
        engine.click_text = Mock(side_effect=click_text)
        engine.calculated_roll()
        # 点「作弊」那一刻 cheat_target 已经是「肉体帝侯」——cheat() 才知道要选哪一行
        self.assertEqual(seen_targets, ["肉体帝侯"])
        self.assertClickedText(engine, text="作弊", box=CHEAT_BUTTON_BOX, allow_fail=True)
        self.assertEqual(engine.cheat_target, "肉体帝侯")
        self.evaluate.assert_called_once_with(engine.nodes, engine.edges, 0, t=0.2)
        engine.init_map.assert_not_called()
        self.assertEqual(engine.mini_state, 0)

    def test_cheat_button_failure_warns_and_still_returns(self):
        """点「作弊」失败只警告，仍然返回等下一轮，绝不能顺手点「确认效果」把作弊界面顶掉。"""
        engine = self.make_engine(plane_floor=2, cheating=True)
        self.stub_best_path([{"idx": 0}, {"idx": 1}], replace_idx=1)
        engine.click_text = Mock(return_value=False)
        engine.calculated_roll()
        self.assertClickedText(engine, text="作弊", box=CHEAT_BUTTON_BOX, allow_fail=True)
        self.assertIn("没点到「作弊」按钮", str(self.logger.warning.call_args))
        engine.init_map.assert_not_called()
        self.assertEqual(engine.mini_state, 0)
        self.assertEqual(engine.cheat_target, "肉体帝侯")

    def test_plane_floor_three_cheats_with_its_own_temperature(self):
        """第三位面恒走作弊分支（不要求 best_path[1] 命中替换节点），t=0.3。"""
        engine = self.make_engine(plane_floor=3, cheating=True)
        self.stub_best_path([{"idx": 0}, {"idx": 9}], replace_idx=1)
        engine.calculated_roll()
        self.evaluate.assert_called_once_with(engine.nodes, engine.edges, 0, t=0.3)
        self.assertClickedText(engine, text="作弊", box=CHEAT_BUTTON_BOX, allow_fail=True)

    # ---- 重投分支 ----

    def test_redo_branch_clicks_redo_and_returns(self):
        """作弊不可用、重投可用：点一次「重投」后返回，不点「确认效果」。"""
        engine = self.make_engine(plane_floor=2, cheating=False, redo=True)
        self.stub_best_path([{"idx": 0}, {"idx": 1}], replace_idx=1)
        engine.calculated_roll()
        self.assertClickedText(engine, text="重投", box=REDO_BOX)
        self.assertIsNone(engine.cheat_target)
        engine.init_map.assert_not_called()
        self.assertEqual(engine.mini_state, 0)

    # ---- 决策条件不满足时回落到确认效果 ----

    def test_single_node_best_path_falls_through_to_confirm(self):
        """最佳路径只有一个节点（没有可替换的下一步）：不点作弊/重投，正常确认。"""
        engine = self.make_engine(plane_floor=2, cheating=True)
        self.stub_best_path([{"idx": 0}], replace_idx=1)
        engine.calculated_roll()
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)

    def test_best_path_not_using_the_replacement_falls_through_to_confirm(self):
        """替换节点不在最佳路径第二步（第二位面）时不做动作，回落到确认效果。"""
        engine = self.make_engine(plane_floor=2, cheating=True)
        self.stub_best_path([{"idx": 0}, {"idx": 9}], replace_idx=1)
        engine.calculated_roll()
        self.assertClickedText(engine, text="确认效果", box=CONFIRM_EFFECT_BOX)
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)


class _StubIronBloodCheatEngine(IronBloodUniverse):
    """只保留 ``cheat()`` 走到的真实实现，OCR 与键鼠全部打桩。

    列表内容按帧给：每次区域 OCR 列表就换下一帧，模拟列表还在滑动；点行/点「确认」/esc 由键鼠桩的
    副作用作用到替身自己身上，所以断言覆盖得到「选不中就一直重试、最后 esc 退出」这条路。
    """

    def __init__(self, list_frames, dialog_open=False, select_works=True,
                 cheat_target="肉体帝侯"):
        self.xx, self.yy = 1920, 1080
        self.screen = None
        self._stop = False
        self.dialog_open = dialog_open
        self.select_works = select_works
        self.select_attempts = 0
        self.selected_box = None
        self.cheat_target = cheat_target
        self.frames = [list(frame) for frame in list_frames]
        self.frame_index = 0
        self.clicks = []
        self.scrolls = []
        self.presses = []
        self.ts = Mock()
        self.ts.find_with_box = Mock(side_effect=self._ocr)

    def click_text(self, text, delay=0, box=None, after_delay=0, click=True, find_all=False,
                   warning=True, ocr_line=True, need_fresh=True, allow_fail=False):
        """只做识别，不做点击（作弊流程里 click_text 一律 click=False）。"""
        if click:
            raise AssertionError("作弊流程不允许 click_text 直接点击")
        return text in "".join(item["raw_text"] for item in self._ocr(box))

    def get_screen(self):
        """画一帧假画面：被选中的那一行铺上紫色高亮。

        高亮区域用引擎 ``cheat_option_selected`` 里同一套 1920x1080 像素字面量：
        左右 [470, 1450]，上下为标题 y-8 ~ y+88。
        """
        screen = np.zeros((self.yy, self.xx, 3), dtype=np.uint8)
        if self.selected_box is not None:
            title_top = int(self.selected_box[2])
            screen[max(title_top - 8, 0):max(title_top + 88, 0), 470:1450] = (200, 80, 120)
        self.screen = screen
        return screen

    def _window_lines(self):
        if not self.dialog_open:
            return []
        return [TITLE, CONFIRM] + list(
            self.frames[min(self.frame_index, len(self.frames) - 1)])

    def _ocr(self, box=None, **kwargs):
        if box is None:
            box = [0, self.xx, 0, self.yy]
        lines = self._window_lines()
        if box == [420, 1500, 240, 960]:
            # 先取当前帧再推进，否则 frame 0 永远用不到，「还在滑动的坐标不能用」就断言不出来
            lines = list(self._window_lines())
            self.frame_index += 1
        return [item for item in lines
                if box[0] <= item["box"][0] and item["box"][1] <= box[1]
                and box[2] <= item["box"][2] and item["box"][3] <= box[3]]

    def _near(self, point, box, tolerance=1.0):
        """点击坐标是否落在 box 中心；两边都是 1920x1080 像素坐标，直接比。"""
        cx, cy = center(box)
        return abs(point[0] - cx) <= tolerance and abs(point[1] - cy) <= tolerance

    def _click(self, x, y):
        self.clicks.append((round(x, 6), round(y, 6)))
        if not self.dialog_open:
            return
        for item in self._window_lines():
            if not self._near((x, y), item["box"]):
                continue
            if item is CONFIRM:
                self.dialog_open = False
            elif item is TITLE:
                pass
            else:
                self.select_attempts += 1
                if self.select_works:
                    self.selected_box = item["box"]
            return

    def _scroll(self, x, y, direct=1):
        # 列表滚动落点也是 1920x1080 像素坐标，原样记下来供断言「滚在列表区域中心」
        self.scrolls.append((direct, round(x), round(y)))

    def _press(self, key, *args, **kwargs):
        self.presses.append(key)
        if key == "esc":
            self.dialog_open = False


class CheatFlowTest(unittest.TestCase):
    """``cheat()``：窗口已由 ``calculated_roll`` 打开，这里只滚列表、选目标行、确认或 esc 退出。"""

    def setUp(self):
        self.manager = Mock()
        # 生产代码只走 1920x1080 像素入参的 pointer 接口；旧的比例接口 click/scroll/drag
        # 现在只作为 click_point 等的内部实现，测试替身跟着迁移，断言仍然对得上传参。
        self.manager.click_point = Mock(side_effect=lambda x, y, **kwargs: self.engine._click(x, y))
        self.manager.scroll_point = Mock(
            side_effect=lambda x, y, direct=1: self.engine._scroll(x, y, direct))
        self.manager.press = Mock(side_effect=lambda key, *a, **k: self.engine._press(key))
        self.enterContext(patch("core.any_fate.engine.key_mouse_manager", self.manager))
        self.logger = self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", Mock()))
        # 等列表停稳要 sleep，测试里不能真等
        self.enterContext(patch("core.any_fate.engine.time", types.SimpleNamespace(sleep=Mock())))

    def make_engine(self, list_frames, **kwargs):
        self.engine = _StubIronBloodCheatEngine(list_frames, **kwargs)
        return self.engine

    def assertClicked(self, *boxes):
        """点击必须落在识别到的文字中心：替身记录的坐标就是 1920x1080 像素坐标。"""
        self.assertEqual(len(self.engine.clicks), len(boxes))
        for clicked, box in zip(self.engine.clicks, boxes):
            expected = center(box)
            self.assertAlmostEqual(clicked[0], expected[0], places=6)
            self.assertAlmostEqual(clicked[1], expected[1], places=6)

    def test_selects_the_target_row_then_confirms(self):
        """列表里还有别的毁灭系效果，也只能点「肉体帝侯」那一行，再点「确认」。"""
        engine = self.make_engine(
            [[SELF_DESTRUCT_TITLE, FLESH_TITLE, FLESH_DESC]] * 4, dialog_open=True)
        engine.cheat()
        self.assertClicked(FLESH_TITLE["box"], CONFIRM["box"])
        self.assertFalse(engine.dialog_open)
        self.assertIsNone(engine.cheat_target)

    def test_scrolls_the_list_until_the_target_row_shows_up(self):
        """目标行不在当前屏：滚动列表（不是盲拖），滚到目标行再点。"""
        frames = [
            [SELF_DESTRUCT_TITLE],
            [FLESH_TITLE, FLESH_DESC],
            [FLESH_TITLE, FLESH_DESC],
        ]
        engine = self.make_engine(frames, dialog_open=True)
        engine.cheat()
        self.assertEqual(self.manager.scroll_point.call_count, 2)
        self.manager.drag_point.assert_not_called()
        self.assertClicked(FLESH_TITLE["box"], CONFIRM["box"])
        self.assertIsNone(engine.cheat_target)

    def test_scrolls_down_once_before_the_first_recognition(self):
        """目标一定在列表靠后的位置：进列表后先滚一屏，第一屏不做 OCR。"""
        engine = self.make_engine([[FLESH_TITLE]] * 4, dialog_open=True)
        engine.cheat()
        # 只有 skip_first_ocr 那一次滚动；第一屏就认到了目标，循环里不再滚
        self.assertEqual(self.manager.scroll_point.call_count, 1)
        self.assertEqual(self.manager.scroll_point.call_args.kwargs["direct"], -15)
        self.assertIn("跳过首次识别", str(self.logger.debug.call_args_list))
        self.assertClicked(FLESH_TITLE["box"], CONFIRM["box"])

    def test_never_uses_the_old_blind_drag_and_fixed_click(self):
        """旧的盲拖 + 盲点 (571, 622) 就是把窗点关掉的元凶：所有点击必须落在识别到的文字中心。"""
        engine = self.make_engine([[FLESH_TITLE]] * 4, dialog_open=True)
        engine.cheat()
        # 拖拽接口不许出现：列表只靠滚轮滚
        self.manager.drag_point.assert_not_called()
        self.assertClicked(FLESH_TITLE["box"], CONFIRM["box"])

    def test_escapes_without_confirming_when_the_target_row_is_missing(self):
        """列表里没有目标行：滚完三屏就 esc 退出，绝不能点「确认」浪费一次作弊。"""
        engine = self.make_engine([[SELF_DESTRUCT_TITLE]] * 10, dialog_open=True)
        engine.cheat()
        self.assertEqual(engine.clicks, [])
        self.assertEqual(engine.presses, ["esc"])
        self.assertFalse(engine.dialog_open)
        self.assertIsNone(engine.cheat_target)
        self.assertIn("没有找到目标骰面效果", str(self.logger.warning.call_args))

    def test_gives_up_after_five_failed_clicks_then_escapes(self):
        """点了行却看不到选中高亮：同一屏最多点五次，点不到就报错收场，不能确认。

        这里锁的是「重试有上限、失败只 esc 不确认」。
        """
        engine = self.make_engine([[FLESH_TITLE]] * 4, dialog_open=True, select_works=False)
        engine.cheat()
        self.assertEqual(len(engine.clicks), 5)
        for clicked in engine.clicks:
            expected = center(FLESH_TITLE["box"])
            self.assertAlmostEqual(clicked[0], expected[0], places=6)
            self.assertAlmostEqual(clicked[1], expected[1], places=6)
        self.assertEqual(engine.presses, ["esc"])
        self.assertIsNone(engine.cheat_target)
        self.assertEqual(
            len([c for c in self.logger.warning.call_args_list if "未检测到高亮" in str(c)]), 5)
        self.assertIn("重试五次仍未点击成功", str(self.logger.error.call_args))
        self.assertIn("没有找到目标骰面效果", str(self.logger.warning.call_args))

    def test_escapes_when_there_is_no_target_left(self):
        """cheat_target 为空（已作弊过/还没决策）：不选任何行，直接 esc 关窗。"""
        engine = self.make_engine([[FLESH_TITLE]] * 4, dialog_open=True, cheat_target=None)
        engine.cheat()
        self.assertEqual(engine.clicks, [])
        self.assertEqual(engine.presses, ["esc"])
        self.assertIsNone(engine.cheat_target)


if __name__ == "__main__":
    unittest.main()
