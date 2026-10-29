"""弹指一挥作弊选项窗的回归测试（issue #297）。

窗口是一张可滚动的骰面效果列表：每行以「【命途·效果名】」标题开头、后面跟一行说明
文字，底部是「取消」「确认」。列表只能用滚轮滚（拖拽松手后有惯性，按截图坐标点会点
到别的行），并且点完必须看到该行的紫色高亮才允许确认。

本测试纯打桩，不连游戏、不真点击/真滚轮、不真 sleep、不依赖真实屏幕：
`ts.find_with_box` 按区域返回 OCR 结果，`click_text` 只记录文字点击（判断窗口还在不在
时只 OCR 标题、不点击），键鼠的 click_point/scroll_point/press 全部记录下来（坐标一律是
1920x1080 像素坐标，原点在客户区左上角）。断言锁定：

- 点「作弊」按钮成功才记 `cheat_target` / `_cheat_requested_effect`（只是请求，作弊还没落地）；
  `cheat()` 确认之后才记回显用的 `_pending_cheat_effect`；点失败什么都不记。
- 点了「作弊」按钮到作弊落地之间，骰面还是旧效果：这段空窗期不核对回显、不重新决策，
  超时（窗口一直没弹出）才清掉这次请求。
- 回显一致时直接点「确认效果」；回显不一致且还有作弊次数时按同一目标重选，没有次数
  时解锁并按实际效果重新决策。
- 列表只认「【」开头的标题行（说明文字在 OCR 这一步就被丢掉），全程不用 drag。
- 选中高亮没看到就重试（最多 5 次），还不行就报错收场，绝不确认没选中的骰面。
- `cheat()` 的重复触发、选不中、确认失败、没有 locked_effect 各条收场路径。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from importing import load_img

# core.finger_snap.engine 在导入期会读取灰度模板，必须先载入图像缓存。
load_img()

from core.finger_snap.engine import FingerSnap
from tool.countdown_evaluator import EFFECT_NAMES, EFFECT_NOTHING, EFFECT_SELECT

XX, YY = 1920, 1080

# 引擎里写死的各个区域框（1920x1080 基准）
LIST_BOX = [420, 1500, 240, 960]       # 作弊列表区域
TITLE_BOX = [923, 996, 230, 270]       # 只用来判断窗口还开着的标题条
BUTTON_BOX = [1261, 1321, 761, 792]    # 掷骰界面上的「作弊」按钮
CONFIRM_BOX = [900, 1520, 700, 1030]   # 作弊窗底部按钮区域
CONFIRM_EFFECT_BOX = [1584, 1687, 961, 994]  # 「确认效果」按钮
EFFECT_BOX = [1339, 1576, 429, 464]    # 当前骰面效果文本


def line(text, box):
    """一行 OCR 结果：raw_text + 屏幕像素框 [左,右,上,下]。"""
    return {"raw_text": text, "box": list(box)}


def center(box):
    return (box[0] + box[1]) / 2, (box[2] + box[3]) / 2


# 作弊窗里的固定文字
DIALOG_TITLE = line("作弊", [940, 985, 240, 268])
DICE_BUTTON = line("作弊", BUTTON_BOX)
CONFIRM = line("确认", [1168, 1223, 811, 841])
# 提示文字里也带「确认」二字，必须在框内挑最下面那个真按钮
CONFIRM_HINT = line("点击「确认」按钮", [950, 1400, 720, 750])
CIHUAI_TITLE = line("【丰饶·慈怀】", [470, 700, 900, 926])
# 说明文字里也带着「慈怀」，但引擎只认「【」开头的行标题
CIHUAI_DESC = line("选择1个区域，为其附加【慈怀】效果", [560, 1440, 910, 937])
GUIXIN_TITLE = line("【丰饶·归心】", [470, 700, 690, 716])
OTHER_TITLE = line("【丰饶·对症】", [470, 700, 780, 806])


def observed_line(text):
    """当前骰面效果的 OCR 行；text=None 表示认不出。"""
    return line(text, [1400, 1500, 440, 460]) if text else None


class FakeAgent:
    """替身决策模型：记录同步/推荐/应用了什么，不跑真实的 DP/MC 演算。"""

    def __init__(self, locked_effect, action="keep"):
        self.locked_effect = locked_effect
        self.ready = True
        self.decision_mode = "mc"
        self.action = action
        self.synced = []
        self.recommended = []
        self.applied = []
        self.state = SimpleNamespace(cheat_rem=0, reroll_rem=0)

    def sync_facts(self, **kwargs):
        self.synced.append(kwargs)
        self.state = SimpleNamespace(
            cheat_rem=kwargs.get("cheat", 0),
            reroll_rem=kwargs.get("reroll", 0))

    def recommend_effect(self, observed):
        self.recommended.append(observed)
        return SimpleNamespace(
            action=self.action, alternatives=[], expected_countdown=0.0)

    def apply_effect_action(self, observed, action):
        self.applied.append(action)
        if action != "keep":
            self.locked_effect = int(action[1])


class StubFingerSnap(FingerSnap):
    """绕过 __init__ 与游戏连接，OCR/截图/键鼠全部打桩。

    列表内容是一屏静态行（引擎自己负责丢掉说明文字、按关键字选行）；
    点「作弊」按钮改由 click_text 桩的副作用模拟，点列表行/确认按钮改由
    键鼠桩的副作用模拟。
    """

    def __init__(self, list_lines=None, observed_text="丰饶慈怀", dialog_open=False,
                 button_ok=True, select_works=True, select_works_after=0,
                 confirm_visible=True, confirm_closes=True,
                 locked_effect=EFFECT_SELECT, cheat_count=1, action="keep"):
        self.xx, self.yy = XX, YY
        self.screen = np.zeros((YY, XX, 3), dtype=np.uint8)
        self.nodes = [{"idx": 0}]
        self.plane_floor = 2
        self.countdown = 15
        self.mini_state = 0
        self._stop = False
        self.cheat_target = None
        self._cheat_count = cheat_count
        self._reroll_count = 0
        self._pending_cheat_effect = None
        self._cheat_confirmed_effect = None
        self._cheat_requested_effect = None
        self._cheat_requested_at = 0.0
        self._target_decided = False
        self.list_lines = list(list_lines) if list_lines is not None else [CIHUAI_TITLE]
        self.observed_text = observed_text
        self.dialog_open = dialog_open
        self.button_ok = button_ok
        self.select_works = select_works
        self.select_works_after = select_works_after
        self.confirm_visible = confirm_visible
        self.confirm_closes = confirm_closes
        self.select_attempts = 0
        self.selected_box = None
        self.clicks = []
        self.scrolls = []
        self.presses = []
        self.click_text_calls = []
        self.check = Mock(return_value=True)
        self.init_map = Mock()
        self._log_decision = Mock(return_value=False)
        self.countdown_agent = FakeAgent(locked_effect, action)
        self.ts = Mock()
        self.ts.find_with_box = Mock(side_effect=self._ocr)

    # ---- OCR 打桩 ----

    def _window_lines(self):
        return [DIALOG_TITLE, CONFIRM] + list(self.list_lines)

    def _ocr(self, box=None, **kwargs):
        box = box or [0, self.xx, 0, self.yy]
        if box == LIST_BOX:
            items = self._window_lines()
        elif box == CONFIRM_BOX:
            items = [CONFIRM_HINT, CONFIRM] if self.confirm_visible else []
        elif box == BUTTON_BOX:
            items = [DICE_BUTTON] if self.button_ok else []
        elif box == EFFECT_BOX:
            observed = observed_line(self.observed_text)
            items = [observed] if observed else []
        else:
            items = []
        return [dict(item) for item in items
                if box[0] <= item["box"][0] and item["box"][1] <= box[1]
                and box[2] <= item["box"][2] and item["box"][3] <= box[3]]

    # ---- 截图打桩 ----

    def get_screen(self):
        """造一帧假画面：被选中那一行铺上紫色高亮（选中判定的唯一依据）。

        高亮区域和引擎 ``cheat_option_selected`` 的字面量一致（1920x1080 像素）：
        左右 [470, 1450]，上下为标题 y-8 ~ y+88。
        """
        screen = np.zeros((self.yy, self.xx, 3), dtype=np.uint8)
        if self.selected_box is not None:
            title_top = int(self.selected_box[2])
            screen[max(title_top - 8, 0):max(title_top + 88, 0), 470:1450] = (200, 80, 120)
        self.screen = screen
        return screen

    # ---- 文字点击打桩 ----

    def click_text(self, text, box=None, click=True, allow_fail=False, **kwargs):
        """记录 click_text；「作弊」标题判断只 OCR 不点击，「作弊」按钮点击后开窗。"""
        box = list(box) if box is not None else None
        self.click_text_calls.append(
            {"text": text, "box": box, "click": click, "allow_fail": allow_fail})
        if text == "作弊" and box == TITLE_BOX:
            return self.dialog_open
        if text == "作弊" and box == BUTTON_BOX:
            if not self.button_ok:
                return False
            self.dialog_open = True
            return True
        if text == "确认效果" and box == CONFIRM_EFFECT_BOX:
            return True
        return False

    # ---- 键鼠打桩 ----

    def install_pointer(self, key_mouse_manager):
        # 生产代码只调 1920x1080 像素入参的 pointer 接口，替身挂在同一层，
        # 记录的坐标就是引擎实际传的像素坐标；旧的 click/scroll 已是内部实现，不再打桩。
        key_mouse_manager.click_point.side_effect = self._click
        key_mouse_manager.scroll_point.side_effect = self._scroll
        key_mouse_manager.press.side_effect = self._press

    def _near(self, point, box, tolerance=1.0):
        """点击坐标是否落在 box 中心；两边都是 1920x1080 像素坐标，直接比。"""
        cx, cy = center(box)
        return abs(point[0] - cx) <= tolerance and abs(point[1] - cy) <= tolerance

    def _click(self, x, y):
        self.clicks.append((x, y))
        if self._near((x, y), BUTTON_BOX):
            self.dialog_open = True
            return
        if not self.dialog_open:
            return
        if self._near((x, y), CONFIRM["box"]):
            if self.confirm_closes:
                self.dialog_open = False
            return
        for item in self.list_lines:
            if not self._near((x, y), item["box"]):
                continue
            # 点在列表某一行上：游戏真的选中了才会有高亮
            self.select_attempts += 1
            if self.select_works and self.select_attempts > self.select_works_after:
                self.selected_box = item["box"]
            return

    def _scroll(self, x, y, direct=1):
        # 列表滚动落点也是 1920x1080 像素坐标，原样记下来供断言「滚在列表区域中心」
        self.scrolls.append((direct, round(x), round(y)))

    def _press(self, key, *args, **kwargs):
        self.presses.append(key)
        if key == "esc":
            self.dialog_open = False


class FingerSnapCheatSelectTest(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        # 作弊窗助手在 core.any_fate.engine，弹指自己的 calculated_roll/cheat 在
        # core.finger_snap.engine，两边引用同一个 manager，断言不分家。
        self.enterContext(patch("core.any_fate.engine.key_mouse_manager", self.manager))
        self.enterContext(patch("core.finger_snap.engine.key_mouse_manager", self.manager))
        self.af_logger = self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", Mock()))
        self.fs_logger = self.enterContext(patch("core.finger_snap.engine.CUS_LOGGER", Mock()))
        # 等列表刷新/等窗口收起的 sleep 全部跳过
        self.enterContext(patch("core.any_fate.engine.time", SimpleNamespace(sleep=Mock())))
        # 引擎用 time.time() 判断「刚点过作弊按钮」的等待窗口，这里给个固定时钟
        self.clock = Mock(return_value=1000.0)
        self.enterContext(patch("core.finger_snap.engine.time",
                                SimpleNamespace(sleep=Mock(), time=self.clock)))
        self.roll_count = self.enterContext(patch(
            "core.any_fate.engine.match_roll_count_in_region", Mock(return_value=None)))
        self.cheat_count = self.enterContext(patch(
            "core.any_fate.engine.match_cheat_count_in_region", Mock(return_value=None)))
        self.locked_roll_count = self.enterContext(patch(
            "core.any_fate.engine.match_locked_roll_count_in_region", Mock(return_value=None)))
        self.engine = None

    def tearDown(self):
        # 整张列表只能用滚轮滚，任何用例都不许出现拖拽（新旧两套接口都查）。
        self.manager.drag_point.assert_not_called()
        self.manager.drag.assert_not_called()

    # ---- 构造与断言辅助 ----

    def make_engine(self, list_lines=None, **kwargs):
        engine = StubFingerSnap(list_lines, **kwargs)
        engine.install_pointer(self.manager)
        self.engine = engine
        return engine

    def assertClicks(self, engine, *boxes):
        # 点击必须落在识别到的文字中心：记录的坐标就是引擎传入的 1920x1080 像素坐标
        expected = [center(box) for box in boxes]
        self.assertEqual(len(engine.clicks), len(expected),
                         msg=f"点击次数不对：{engine.clicks}")
        for clicked, want in zip(engine.clicks, expected):
            self.assertAlmostEqual(clicked[0], want[0], places=6)
            self.assertAlmostEqual(clicked[1], want[1], places=6)

    def _joined(self, logger, level):
        return " ".join(str(call.args[0]) for call in getattr(logger, level).call_args_list
                        if call.args)

    def warnings(self):
        return self._joined(self.fs_logger, "warning") + " " + \
            self._joined(self.af_logger, "warning")

    def errors(self):
        return self._joined(self.fs_logger, "error") + " " + \
            self._joined(self.af_logger, "error")

    def debugs(self):
        return self._joined(self.fs_logger, "debug") + " " + \
            self._joined(self.af_logger, "debug")

    def click_text_texts(self, engine):
        return [call["text"] for call in engine.click_text_calls]

    # ---- 作弊动作：点「作弊」按钮后的记账 ----

    def test_cheat_action_clicks_button_and_records_requested_target(self):
        """点「作弊」按钮成功后只记「已请求」，并同步作弊次数；回显的 pending 要等确认才记。"""
        engine = self.make_engine(observed_text="丰饶慈怀",
                                  action=("cheat", EFFECT_SELECT), cheat_count=2)
        engine.calculated_roll()
        # click_text 是文字点击桩，不走 key_mouse_manager.click
        self.assertClicks(engine)
        self.assertEqual(len(engine.click_text_calls), 1)
        call = engine.click_text_calls[0]
        self.assertEqual(call["text"], "作弊")
        self.assertEqual(call["box"], BUTTON_BOX)
        self.assertTrue(call["allow_fail"])
        self.assertEqual(engine.cheat_target, EFFECT_NAMES[EFFECT_SELECT])
        # 这一刻作弊还没落地（窗口没弹、行没选、确认没点），所以只记请求
        self.assertEqual(engine._cheat_requested_effect, EFFECT_SELECT)
        self.assertEqual(engine._cheat_requested_at, self.clock.return_value)
        self.assertIsNone(engine._pending_cheat_effect)
        self.assertEqual(engine.countdown_agent.applied, [("cheat", EFFECT_SELECT)])
        self.assertEqual(engine.countdown_agent.synced[-1]["cheat"], 2)
        self.assertEqual(engine._cheat_count, 2)

    def test_cheat_button_miss_leaves_no_target_and_no_pending(self):
        """「作弊」按钮没点到就不许记账，否则会留下一个永远回显不到的目标。"""
        engine = self.make_engine(observed_text="丰饶慈怀",
                                  action=("cheat", EFFECT_SELECT), button_ok=False)
        engine.calculated_roll()
        self.assertIn("没点到「作弊」按钮", self.warnings())
        self.assertEqual(self.click_text_texts(engine), ["作弊"])
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._pending_cheat_effect)
        self.assertIsNone(engine._cheat_confirmed_effect)
        self.assertEqual(engine.countdown_agent.applied, [])

    # ---- 回显核对 ----

    def test_echo_match_confirms_without_redoing_the_decision(self):
        engine = self.make_engine(observed_text="丰饶慈怀")
        engine._pending_cheat_effect = EFFECT_SELECT
        engine.calculated_roll()
        self.assertClicks(engine)
        self.assertEqual(self.click_text_texts(engine), ["确认效果"])
        self.assertEqual(engine.click_text_calls[0]["box"], CONFIRM_EFFECT_BOX)
        self.assertIsNone(engine._pending_cheat_effect)
        engine.init_map.assert_called_once()
        self.assertEqual(engine.mini_state, 1)
        self.assertEqual(engine.countdown_agent.recommended, [])
        self.assertEqual(engine.countdown_agent.applied, [])

    def test_echo_mismatch_with_cheat_left_reselects_the_same_target(self):
        """还有作弊次数：保留 pending，把 locked_effect 锁回目标、重新点「作弊」。"""
        engine = self.make_engine(observed_text="丰饶可憎", cheat_count=2)
        engine._pending_cheat_effect = EFFECT_SELECT
        engine.calculated_roll()
        self.assertIn("回显不一致", self.warnings())
        self.assertIn("重新选择", self.warnings())
        # 这一轮不选行：只点「作弊」按钮把窗口叫回来，选行交给 cheat()
        self.assertClicks(engine)
        self.assertEqual(self.click_text_texts(engine), ["作弊"])
        self.assertEqual(engine.click_text_calls[0]["box"], BUTTON_BOX)
        self.assertEqual(engine.countdown_agent.locked_effect, EFFECT_SELECT)
        self.assertEqual(engine._pending_cheat_effect, EFFECT_SELECT)
        self.assertIsNone(engine._cheat_confirmed_effect)
        # 重选又是一次「已请求」：下次 calculated_roll 不能拿旧骰面核对回显
        self.assertEqual(engine._cheat_requested_effect, EFFECT_SELECT)
        self.assertEqual(engine._cheat_requested_at, self.clock.return_value)
        self.assertEqual(engine.countdown_agent.recommended, [])
        self.assertEqual(engine.countdown_agent.applied, [])

    def test_echo_mismatch_without_cheat_left_unlocks_and_rededecides(self):
        """没有作弊次数了：清 pending、解锁，按实际认出的效果重新决策。"""
        engine = self.make_engine(observed_text="丰饶可憎", cheat_count=0)
        engine._pending_cheat_effect = EFFECT_SELECT
        engine.calculated_roll()
        self.assertIn("回显不一致", self.warnings())
        self.assertIn("取消锁定并按实际效果重新决策", self.warnings())
        self.assertEqual(self.click_text_texts(engine), ["确认效果"])
        self.assertEqual(engine.click_text_calls[0]["box"], CONFIRM_EFFECT_BOX)
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._pending_cheat_effect)
        self.assertIsNone(engine.countdown_agent.locked_effect)
        self.assertEqual(engine.countdown_agent.recommended, [EFFECT_NOTHING])
        self.assertEqual(engine.countdown_agent.applied, ["keep"])
        self.assertEqual(engine.mini_state, 1)

    def test_pending_echo_waits_without_clicking_when_effect_is_unreadable(self):
        engine = self.make_engine(observed_text=None)
        engine._pending_cheat_effect = EFFECT_SELECT
        engine.calculated_roll()
        self.assertIn("等待作弊效果", self.warnings())
        self.assertEqual(engine.click_text_calls, [])
        self.assertEqual(engine.countdown_agent.recommended, [])
        self.assertEqual(engine.countdown_agent.applied, [])
        self.assertEqual(engine._pending_cheat_effect, EFFECT_SELECT)

    # ---- 点了「作弊」按钮、作弊还没落地这段空窗期 ----

    def test_calculated_roll_waits_while_the_cheat_request_is_in_flight(self):
        """刚点过「作弊」按钮时骰面还是旧效果，不许拿去核对回显，也不许重新决策。"""
        engine = self.make_engine(observed_text="丰饶慈怀")
        engine._cheat_requested_effect = EFFECT_SELECT
        engine._cheat_requested_at = self.clock.return_value
        engine.calculated_roll()
        self.assertIn("等作弊窗弹出", self.debugs())
        self.assertEqual(engine.click_text_calls, [])
        self.assertEqual(engine.countdown_agent.synced, [])
        self.assertEqual(engine.countdown_agent.recommended, [])
        self.assertEqual(engine.countdown_agent.applied, [])
        self.roll_count.assert_not_called()
        self.assertEqual(engine._cheat_requested_effect, EFFECT_SELECT)

    def test_calculated_roll_drops_a_cheat_request_that_never_landed(self):
        """作弊窗一直没弹出（比如点击被吞了）：超时后清掉请求，照常重新决策。"""
        engine = self.make_engine(observed_text="丰饶慈怀")
        engine._cheat_requested_effect = EFFECT_SELECT
        engine._cheat_requested_at = self.clock.return_value - 10
        engine.calculated_roll()
        self.assertIn("一直没打开", self.warnings())
        self.assertIsNone(engine._cheat_requested_effect)
        self.assertEqual(len(engine.countdown_agent.synced), 1)
        self.assertEqual(engine.countdown_agent.recommended, [EFFECT_SELECT])

    # ---- 选行 ----

    def test_cheat_selects_the_title_row_and_confirms(self):
        """列表里同时有标题行和带「慈怀」的说明文字，只能点标题行。"""
        engine = self.make_engine([CIHUAI_TITLE, CIHUAI_DESC], dialog_open=True)
        engine.cheat()
        self.assertClicks(engine, CIHUAI_TITLE["box"], CONFIRM["box"])
        self.assertEqual(engine.select_attempts, 1)
        self.assertEqual(engine._cheat_confirmed_effect, EFFECT_SELECT)
        # 确认成功才算作弊落地：这时才记回显用的 pending，并清掉「已请求」
        self.assertEqual(engine._pending_cheat_effect, EFFECT_SELECT)
        self.assertIsNone(engine._cheat_requested_effect)
        self.assertIsNone(engine.cheat_target)
        self.assertIn("已在作弊界面选择", self.debugs())
        self.assertEqual(engine.presses, [])
        self.assertEqual(engine.scrolls, [])

    def test_cheat_option_entries_only_keeps_title_rows(self):
        engine = self.make_engine([CIHUAI_DESC, CIHUAI_TITLE], dialog_open=True)
        entries = engine.cheat_option_entries()
        self.assertEqual(entries, [{"raw_text": CIHUAI_TITLE["raw_text"],
                                    "box": CIHUAI_TITLE["box"]}])

    def test_find_cheat_option_filters_empty_keywords_and_keeps_first_match(self):
        engine = self.make_engine([GUIXIN_TITLE, CIHUAI_TITLE], dialog_open=True)
        # 空关键字直接返回 None，连 OCR 都不做
        self.assertIsNone(engine.find_cheat_option(()))
        self.assertIsNone(engine.find_cheat_option(("",)))
        engine.ts.find_with_box.reset_mock()
        self.assertIsNone(engine.find_cheat_option(("慈怀偏了",)))
        found = engine.find_cheat_option(("", "慈怀"))
        self.assertEqual(found["raw_text"], CIHUAI_TITLE["raw_text"])
        self.assertEqual(found["box"], CIHUAI_TITLE["box"])

    def test_click_option_outside_the_list_is_refused(self):
        engine = self.make_engine(dialog_open=True)
        outside = line("【丰饶·慈怀】", [470, 700, 40, 66])
        self.assertIsNone(engine.click_cheat_option(outside))
        self.assertClicks(engine)
        self.assertIn("不在作弊界面选项列表区域内", self.errors())

    def test_retries_until_the_highlight_appears_then_selects(self):
        """第一次点完没看到高亮，同一屏再点一次；看到高亮才返回。"""
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True,
                                  select_works_after=1)
        engine.cheat()
        self.assertEqual(engine.select_attempts, 2)
        self.assertClicks(engine, CIHUAI_TITLE["box"], CIHUAI_TITLE["box"],
                          CONFIRM["box"])
        self.assertIn("未检测到高亮", self.warnings())
        self.assertEqual(engine._cheat_confirmed_effect, EFFECT_SELECT)

    def test_keeps_clicking_until_five_tries_run_out(self):
        """高亮一直出不来：一屏最多点 5 次就报错收场，然后关窗放弃，绝不确认。"""
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True, select_works=False)
        engine.cheat()
        self.assertEqual(engine.select_attempts, 5)
        self.assertClicks(engine, *([CIHUAI_TITLE["box"]] * 5))
        self.assertIn("未检测到高亮", self.warnings())
        self.assertIn("重试五次仍未点击成功", self.errors())
        self.assertIn("没选中目标效果", self.errors())
        self.assertEqual(engine.presses, ["esc"])
        self.assertIsNone(engine._cheat_confirmed_effect)

    def test_cheat_option_selected_needs_the_purple_highlight(self):
        engine = self.make_engine(dialog_open=True)
        self.assertFalse(engine.cheat_option_selected(CIHUAI_TITLE))
        engine.selected_box = CIHUAI_TITLE["box"]
        self.assertTrue(engine.cheat_option_selected(CIHUAI_TITLE))
        # 没被选中的另一行不能认成选中
        self.assertFalse(engine.cheat_option_selected(GUIXIN_TITLE))

    # ---- cheat() 的收场路径 ----

    def test_duplicate_trigger_is_ignored_after_confirm(self):
        engine = self.make_engine(dialog_open=True)
        engine._cheat_confirmed_effect = EFFECT_SELECT
        engine.cheat()
        self.assertClicks(engine)
        self.assertEqual(engine.presses, [])
        self.assertEqual(engine.scrolls, [])
        engine.ts.find_with_box.assert_not_called()
        self.assertIsNone(engine.cheat_target)
        self.assertIn("忽略重复触发", self.debugs())

    def test_cheat_without_the_target_row_cancels_with_esc(self):
        engine = self.make_engine([OTHER_TITLE], dialog_open=True)
        engine.cheat()
        self.assertClicks(engine)
        self.assertEqual(engine.presses, ["esc"])
        # 扫 3 轮，每轮往下滚 15 格，落点是列表区域的中心
        self.assertEqual(len(engine.scrolls), 3)
        list_center = center(LIST_BOX)
        for direct, px, py in engine.scrolls:
            self.assertEqual(direct, -15)
            self.assertAlmostEqual(px, list_center[0], places=6)
            self.assertAlmostEqual(py, list_center[1], places=6)
        self.assertIn("没选中目标效果", self.errors())
        self.assertIsNone(engine._pending_cheat_effect)
        self.assertIsNone(engine._cheat_requested_effect)
        self.assertIsNone(engine.countdown_agent.locked_effect)
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._cheat_confirmed_effect)

    def test_cheat_confirm_failure_does_not_mark_confirmed(self):
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True,
                                  confirm_visible=False)
        engine.cheat()
        self.assertClicks(engine, CIHUAI_TITLE["box"])
        self.assertIn("未能成功确认", self.warnings())
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._cheat_confirmed_effect)
        # 行点过了、次数可能已经扣了：仍按目标效果等回显，但请求窗口要关掉
        self.assertEqual(engine._pending_cheat_effect, EFFECT_SELECT)
        self.assertIsNone(engine._cheat_requested_effect)
        self.assertEqual(engine.presses, [])

    def test_cheat_confirm_retried_but_still_open_is_not_marked_confirmed(self):
        """点满两轮「确认」窗还开着：既不能当成功，也不能把目标丢掉。"""
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True,
                                  confirm_closes=False)
        engine.cheat()
        self.assertClicks(engine, CIHUAI_TITLE["box"], CONFIRM["box"], CONFIRM["box"])
        self.assertIn("未能成功确认", self.warnings())
        self.assertIn("作弊选项窗未正常关闭", self.warnings())
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._cheat_confirmed_effect)
        self.assertEqual(engine._pending_cheat_effect, EFFECT_SELECT)
        self.assertIsNone(engine._cheat_requested_effect)

    def test_cheat_without_locked_effect_just_closes_the_window(self):
        engine = self.make_engine(dialog_open=True, locked_effect=None)
        engine.cheat()
        self.assertClicks(engine)
        self.assertEqual(engine.presses, ["esc"])
        self.assertIn("没有待应用的模型效果", self.errors())
        self.assertIsNone(engine.cheat_target)
        self.assertIsNone(engine._cheat_requested_effect)
        engine.ts.find_with_box.assert_not_called()

    # ---- 确认按钮 ----

    def test_confirm_clicks_the_lowest_confirm_line(self):
        """框里有提示文字和真按钮，必须挑最下面那个（真按钮在窗口底部）。"""
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True)
        self.assertTrue(engine.confirm_cheat_dialog())
        self.assertClicks(engine, CONFIRM["box"])
        self.assertFalse(engine.dialog_open)

    def test_confirm_returns_true_when_the_window_is_already_closed(self):
        engine = self.make_engine(dialog_open=False)
        self.assertTrue(engine.confirm_cheat_dialog())
        self.assertClicks(engine)
        self.assertIn("作弊选项窗已关闭", self.debugs())
        engine.ts.find_with_box.assert_not_called()

    # ---- 不拖拽 + calculated_roll 不再有作弊窗守卫 ----

    def test_the_list_only_uses_the_wheel_never_drag(self):
        # 目标在第一屏：一个滚轮操作都不发
        engine = self.make_engine([CIHUAI_TITLE], dialog_open=True)
        engine.cheat()
        self.manager.drag.assert_not_called()
        self.assertEqual(engine.scrolls, [])
        # 目标不在第一屏：只往下滚，仍然不拖
        engine = self.make_engine([OTHER_TITLE], dialog_open=True)
        engine.cheat()
        self.manager.drag.assert_not_called()
        self.assertEqual(len(engine.scrolls), 3)

    def test_calculated_roll_has_no_cheat_dialog_guard(self):
        """作弊窗开着也照常同步事实并决策（守卫已删除，靠状态机认不到文本避免抢跑）。"""
        engine = self.make_engine(observed_text="丰饶慈怀", dialog_open=True)
        engine.calculated_roll()
        self.assertEqual(len(engine.countdown_agent.synced), 1)
        self.assertEqual(engine.countdown_agent.recommended, [EFFECT_SELECT])
        self.assertEqual(self.click_text_texts(engine), ["确认效果"])

    def test_locked_cheat_syncs_zero_cheat_and_the_centered_reroll_count(self):
        """没解锁作弊（居中位置认到重投次数）：作弊次数按 0 同步，重投次数照常读。"""
        self.locked_roll_count.return_value = 3
        engine = self.make_engine(observed_text="丰饶慈怀")

        engine.calculated_roll()

        self.assertEqual(engine._reroll_count, 3)
        self.assertEqual(engine._cheat_count, 0)
        self.assertEqual(engine.countdown_agent.synced[-1]["reroll"], 3)
        self.assertEqual(engine.countdown_agent.synced[-1]["cheat"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
