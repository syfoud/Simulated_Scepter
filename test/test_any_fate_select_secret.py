"""
「秘闻」事件与事件选项选择的点击目标回归测试。

背景：select_secret / select_event 原来的 else 分支会盲点 `click(self.tx, self.ty)` 与
`click(0.1167, ty - 0.1139)`，而这两个坐标取自进入函数时的 `self.tx/self.ty`——它是上一次
check() 留下的位置（即使那次匹配失败也会写入），与当前界面元素无关，既可能误触别的控件，
也可能换算到游戏窗口之外、点到别的窗口上抢走游戏前台。

现在的行为（`select_secret` 的点击优先级）：
对话条右下角的金色 ▼（`arrow_dialog`）→「选择」栏里的白色 →（`arrow`）→ 命途选项卡
（命中则快速两击 + 固定偏移点「确定」，点完再 OCR 复核、没点中按文字位置补点，最长 0.5 s）
→ 都不在时退回点「秘闻」文字。
每个分支都点自己刚匹配到的位置，不再使用残留坐标。
- select_secret 的金色 ▼ 用 `MASK["dialog"]` 框定右侧对话区（120x120），
  不再只搜「模板大小 + 60」（114x106）；事件面板里的图标改用 `MASK["event_icon"]` 竖条
  （180x960），「确定」按钮改成 OCR 读文字后按文字位置点。
- select_event：选项文字不再整框 OCR，而是先认出**所有**星号（※，check() 只拿得到最高分的那个，
  一帧 3~4 条选项时会漏），再只 OCR 每条星号右侧的横条（`event_option_rows`）——说明文字因此
  不会被当成一条独立选项，一条选项的整块文字也正好落在同一个横条里，「确定」按钮的偏移就按
  整块底边算（`confirm_point`）。
- select_event：优选项没匹配上时只识别一次（没有战斗的事件本来就不存在优选项，重试只是白等），
  先记一条 warning 再在识别到的选项里选一条点击，避免卡在事件界面；确实一个都点不到时什么都不点。
"""

import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import find_image_by_name, load_all_images_from_directory

# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse
from core.simulated.engine import SimulatedUniverse

# 进入函数时 self.tx/self.ty 的残留值（旧实现会照这个坐标盲点）
STALE_POINT = (0.5000, 0.5000)
# 命途图标（选项卡左上角）、对话箭头的匹配位置
FATE_POINT = (0.2865, 0.6250)
ARROW_POINT = (0.3044145833333333, 0.15833333333333333)
# 对话条右下角金色 ▼（arrow_dialog）的匹配位置
DIALOG_POINT = (0.178125, 0.3250)
# 左侧图标列里的三个推进图标（arrow / arrow_1 / shop_herta）的匹配位置：只在比较点击落点时区分
ICON_POINT = (0.2865, 0.5000)
ARROW_1_POINT = (0.2865, 0.4800)
SHOP_HERTA_POINT = (0.2865, 0.4600)
# 选项卡 → 它下方「确定」按钮的手量固定偏移
CONFIRM_OFFSET = (0.1167, 0.1139)
# select_event 兜底时 OCR 里识别到的选项（raw_text, 屏幕文本框 [x1,x2,y1,y2]）
OPTION_TEXT = "把它放回族群"
OPTION_BOX = [1330, 1690, 640, 680]
# 兜底点击的落点：选项中心换算成键鼠管理器的比例坐标（以窗口右下角为原点，故取 1 - v）
OPTION_POINT = (1 - 1510 / 1920, 1 - 660 / 1080)
# click_event_option 用 find_text 拿到的选项文本框（四角顺序与真实现一致）
OPTION_OCR_BOX = [[1330, 640], [1690, 640], [1690, 680], [1330, 680]]
# 兜底/优选项点中选项后，「确定」按钮的固定偏移落点：x 恒为 0.1135（屏幕 x≈1702），
# y = 选项文字行底边 + 76 px（≈ 星号行 + 90）。这两个数现在直接写在 SimulatedUniverse.confirm_point 里，
# 测试里留一份同值常量，改 real 代码时这里要跟着改。
CONFIRM_FIXED_X = 0.1135
CONFIRM_TEXT_GAP = 76
CONFIRM_FIXED_POINT = (
    CONFIRM_FIXED_X,
    1 - (OPTION_BOX[3] + CONFIRM_TEXT_GAP) / 1080,
)
# 「确定」按钮的 OCR 文本框（logs/log_2026-10-15-21-11.txt 实测 [1676,1728,482,512]，
# 中心 (1702,497)）：固定偏移没点中时按这个框的中心补点。
CONFIRM_TEXT_BOX = [1676, 1728, 482, 512]
CONFIRM_TEXT_POINT = (1 - 1702 / 1920, 1 - 497 / 1080)
# logs/log_2026-10-15-21-11.txt（3/4 轮普通事件卡死那一帧）选项区的 OCR 原文：
# 被点中的选项折成两行（393~460）、「确定」按钮文字被读成 [1676,1728,482,512]（中心 1702,497），
# 后面跟着第二个选项的两行（564~640）。
WRAPPED_OPTION_LINES = [
    {"raw_text": "※ 开展一次*完美型男*挑战！", "box": [625, 1810, 393, 418]},
    {"raw_text": "花费40宇宙碎片。", "box": [657, 1875, 435, 460]},
    {"raw_text": "确定", "box": [1676, 1728, 482, 512]},
    {"raw_text": "※ 走开。", "box": [637, 1747, 564, 602]},
    {"raw_text": "小心有诈！", "box": [420, 1770, 611, 640]},
]
# 什么都不识别时的最终兜底：点左上角「事件」文字的固定落点（1 - x/xx, 1 - y/yy）
EVENT_LABEL_CLICK = (0.9479166666666666, 0.9564814814814815)

# 下面这几个区域/文字，真实现已内联进各自的函数（core/simulated/engine.py 的
# event_ui_label / read_event_name / confirm_text_box / event_option_rows），测试里留一份同值副本：
# 改真实现的数字时，这几行要跟着改。
EVENT_LABEL_BOX = [93, 230, 50, 100]  # 左上角界面标题（「事件」「奇物商店」「祝福强化」）
EVENT_NAME_BOX = [190, 800, 960, 1000]  # 左下角地图标签里的事件名
# 上边界是 110（不是老值 320）：面板纵向位置随事件浮动，320 会把浮动到靠上的首行选项判成「不在面板内」
EVENT_OPTION_BOX = [1320, 1850, 110, 1010]  # 右侧选项面板：点击点校验 + 星号横条右边界
CONFIRM_BOX = [1590, 1830, 240, 1070]  # 右侧竖条：只在这里找「确定」文字（覆盖 5 条选项）
CONFIRM_LABEL = "确定"
# 星号（※）在左侧图标列里的屏幕 x（实测模板左边界 1342 + 模板宽 50/2 ≈ 1367）；
# 横条 = [星号 x − 30, 选项面板右边] × [星号 y − 30, 星号 y + 68]（与 event_option_rows 同值；
# 左缘往回让 30 px 是因为整屏 OCR 会把 ※ 和选项文字并进同一个框）
STAR_X = 1367
STAR_BAND_GAP = (-30, 30, 20)
# 命途图标模板名：真实现里 AnyFateUniverse.extra_option_icon_names() 给出的就是这八个
FATE_ICON_NAMES = tuple(f"fate{i}" for i in range(1, 9))


class _FakeClock:
    """按固定步长前进的假时钟，保证 0.5 秒轮询窗口能确定性结束。"""

    def __init__(self, step=0.1):
        self.now = 1000.0
        self.step = step

    def time(self):
        self.now += self.step
        return self.now


class _StubEngine:
    """只提供内核方法所需接口的替身，check() 命中时顺带更新 tx/ty（与真实现一致）。"""

    EVENT_OPTION_BOX = EVENT_OPTION_BOX
    # 真实现里这几个已经内联进函数，测试留一份同值副本（见模块顶部的说明）
    EVENT_LABEL_BOX = EVENT_LABEL_BOX
    CONFIRM_BOX = CONFIRM_BOX
    CONFIRM_LABEL = CONFIRM_LABEL
    # 1080p 的空白画面：read_event_name 需要真实尺寸的截图来算缩放和切片
    SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def __init__(
        self,
        matched,
        text_results=None,
        event_name="",
        options=None,
        ui_label="",
        stars=None,
        fate_stars=None,
    ):
        self.tx, self.ty = STALE_POINT
        self.matched = matched
        self.event_prior = ["选择事件"]
        self.fate = "存护"
        # 真实现里 self.event 一开始并不存在（getattr 取空串），只有写日志时才读一次
        self.event = ""
        # select_event 记下「面板第一次认到选项」的时刻，用来等面板淡入（测淡入把它设成 None）。
        # 远早于当前时刻（替身时钟从 1000 s 起）表示「早就等满淡入窗口」，多数用例据此直接走兜底。
        self._option_shown_at = 0.0
        self.xx, self.yy = 1920, 1080
        self.scx = 1.0
        self.screen = self.SCREEN
        self.get_screen = Mock(return_value=self.SCREEN)
        self.check = Mock(side_effect=self._check)
        # 选项相关的方法默认用真实现，OCR 与认到的选项图标都由替身喂
        self.options = list(options) if options else []
        self.confirm_box = None
        self.bands = None
        self.stars = list(stars) if stars is not None else self._default_stars(self.options)
        # 命途图标（个别事件的优选项用它）：只在「※ 那遍没匹配到优选项」的补认里出现
        self.fate_stars = list(fate_stars) if fate_stars else []

        def _option_icons(names=None):
            # 真实现会把这一帧认到的选项图标留在 self._option_icons：select_event 用它判断
            # 「连选项图标都没有」才报「什么都没识别到」
            names = self.option_icon_names() if names is None else tuple(names)
            wants_fate = any(name.startswith("fate") for name in names)
            icons = list(self.stars) + (list(self.fate_stars) if wants_fate else [])
            self._option_icons = icons
            return icons

        self.event_option_icons = Mock(side_effect=_option_icons)
        self.get_local = SimulatedUniverse.get_local.__get__(self)
        self.event_option_rows = SimulatedUniverse.event_option_rows.__get__(self)
        self.pick_fallback_option = SimulatedUniverse.pick_fallback_option.__get__(self)
        # 优选项匹配用真实现（在识别到的选项行里匹配 event_prior），OCR 由 ts 打桩
        self.click_event_prior = SimulatedUniverse.click_event_prior.__get__(self)
        # 「确定」按钮的固定偏移用真实现：选项文字折行时要按整块底边算，不能只看被点那一行
        self.confirm_point = SimulatedUniverse.confirm_point.__get__(self)
        # 「确定」按钮的复核/补点用真实现：OCR 右侧竖条里的「确定」文字，按文字框中心点
        self.scaled_box = SimulatedUniverse.scaled_box.__get__(self)
        self.confirm_text_box = SimulatedUniverse.confirm_text_box.__get__(self)
        self.click_confirm_text = SimulatedUniverse.click_confirm_text.__get__(self)
        # 「确定」按钮的点击默认打桩（要测它时用 SimulatedUniverse 的真实现显式换回来）
        self.confirm_event = Mock(return_value=False)
        self.ts = Mock()
        self.ts.find_with_box = Mock(side_effect=self._ocr_in_box)
        # ocr_one_row 既被 read_event_name（左下角事件名）用，也被 event_ui_label（左上角界面标题）用
        self.ts.ocr_one_row = Mock(
            side_effect=lambda _img, box: ui_label if box == self.EVENT_LABEL_BOX else event_name
        )
        # select_event 里 click_text 只用来找「休息区」；选项匹配走 event_option_rows + click_event_prior
        results = text_results or {}
        self.click_text = Mock(side_effect=lambda *args, **kwargs: results.get("休息区", False))

    @staticmethod
    def _default_stars(options):
        """按「星号在选项文字行上方 16 px」造一个星号，让横条正好盖住这一条选项。"""
        if not options:
            return []
        top = min(res["box"][2] for res in options)
        return [{"x": STAR_X, "y": top + 16, "score": 0.99}]

    # 替身代表 any_fate 一系的内核：先只认星号，没命中优选项再补认八个命途图标。
    # 真实现里 option_icon_names 在 SimulatedUniverse、extra_option_icon_names 在 AnyFateUniverse。
    def option_icon_names(self):
        return ("star",)

    def extra_option_icon_names(self):
        return FATE_ICON_NAMES

    def _star_band(self, star):
        """与 event_option_rows 里同一条横条公式：改真实现的数字时这里要跟着改。"""
        gap, up, down = STAR_BAND_GAP
        return [
            int(star["x"] + gap),
            self.EVENT_OPTION_BOX[1],
            int(star["y"] - up),
            int(star["y"] + down),
        ]

    def _ocr_in_box(self, box=None, **kwargs):
        """让 ts.find_with_box 按区域分流：右侧竖条给「确定」文字，星号横条给这条选项的文字行。"""
        if box is not None and list(box) == self.scaled_box(self.CONFIRM_BOX):
            if self.confirm_box is None:
                return []
            return [{"raw_text": self.CONFIRM_LABEL, "box": list(self.confirm_box)}]
        if self.bands is not None:
            return list(self.bands.get(tuple(box), []))
        for star in self.stars:
            if box is not None and list(box) == self._star_band(star):
                return list(self.options)
        return []

    def stub_ocr(self, options=None, confirm_box=None, stars=None, bands=None, fate_stars=None):
        """给 ts.find_with_box 喂结果：选项横条（options）、右侧竖条（confirm_box），或按横条逐条指定。"""
        if options is not None:
            self.options = list(options)
            if stars is None:
                self.stars = self._default_stars(self.options)
        if stars is not None:
            self.stars = list(stars)
        if fate_stars is not None:
            self.fate_stars = list(fate_stars)
        # 与 __init__ 里那份桩一样：补认那一遍（names 里带命途图标）才会给出命途图标
        self.event_option_icons = Mock(
            side_effect=lambda names=None: list(self.stars)
            + (
                list(self.fate_stars)
                if any(
                    name.startswith("fate")
                    for name in (self.option_icon_names() if names is None else tuple(names))
                )
                else []
            )
        )
        self.confirm_box = confirm_box
        self.bands = {tuple(box): list(lines) for box, lines in bands.items()} if bands else None

    def _check(self, path, x=None, y=None, mask=None, **kwargs):
        if path in self.matched:
            self.tx, self.ty = self.matched[path]
            return True
        return False

    def click_event_option(self, event_name, row, from_prior=False):
        """兜底真正落点用真实现，只有 key_mouse_manager 被打桩。"""
        return SimulatedUniverse.click_event_option(self, event_name, row, from_prior=from_prior)

    def read_event_name(self, img=None):
        """事件名读取用真实现，OCR 由 ts.ocr_one_row 打桩。"""
        return SimulatedUniverse.read_event_name(self, img)

    def event_ui_label(self, img=None):
        """左上角界面标题读取用真实现，OCR 由 ts.ocr_one_row 打桩。"""
        return SimulatedUniverse.event_ui_label(self, img)

    def event_name_for_log(self, screen=None):
        """事件名惰性读取用真实现：没读过才走 read_event_name。"""
        return SimulatedUniverse.event_name_for_log(self, screen)


class SelectSecretTest(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.any_fate.engine.key_mouse_manager", self.manager))
        self.enterContext(patch("core.any_fate.engine.CUS_LOGGER"))
        # 命途路径的「确定」点击已合并到 SimulatedUniverse.confirm_event，它用的是那个模块的
        # 键鼠管理器与 logger——一并打桩，免得单测真的去点鼠标
        self.enterContext(patch("core.simulated.engine.key_mouse_manager", self.manager))
        self.enterContext(patch("core.simulated.engine.CUS_LOGGER"))
        self.clock = _FakeClock()
        self.enterContext(
            patch("core.any_fate.engine.time", types.SimpleNamespace(time=self.clock.time))
        )
        # 命途路径的「确定」点击也走 SimulatedUniverse.confirm_event，用的是它那个模块的 time
        self.enterContext(
            patch(
                "core.simulated.engine.time",
                types.SimpleNamespace(time=self.clock.time, sleep=Mock()),
            )
        )

    def _run(self, matched, confirm_box=None):
        engine = _StubEngine(matched)
        # 选项区没有文本；右侧竖条按需要返回「确定」文字
        engine.stub_ocr(confirm_box=confirm_box)
        # 「确定」按钮的点击在 confirm_event 里（固定偏移 + OCR 文字复核），用真实现
        engine.confirm_event = SimulatedUniverse.confirm_event.__get__(engine)
        AnyFateUniverse.select_secret(engine)
        return engine

    def _clicks(self):
        return [call.args for call in self.manager.click.call_args_list]

    def test_dialog_chevron_wins_over_bar_arrow_and_fate_icon(self):
        """点击优先级第一位是金色 ▼：它和「选择」栏箭头、命途选项卡同时在场时只点它。"""
        engine = self._run(
            {"arrow_dialog": DIALOG_POINT, "arrow": ARROW_POINT, "fate3": FATE_POINT}
        )

        self.assertEqual(self._clicks(), [DIALOG_POINT])
        self.assertEqual([call.args[0] for call in engine.check.call_args_list], ["arrow_dialog"])

    def test_bar_arrow_clicked_when_chevron_absent(self):
        """金色 ▼ 不在场时才点「选择」栏里的白色 →，并且不再往下扫命途选项卡。"""
        engine = self._run({"arrow": ARROW_POINT, "fate3": FATE_POINT})

        self.assertEqual(self._clicks(), [ARROW_POINT])
        self.assertEqual(
            [call.args[0] for call in engine.check.call_args_list], ["arrow_dialog", "arrow"]
        )

    def test_secret_text_is_clicked_as_last_resort(self):
        """两个对话推进图标都没匹配上时，退回点「秘闻」文字（点画面任意位置都会把剧情推下去）。"""
        engine = self._run({})

        self.manager.click.assert_not_called()
        engine.click_text.assert_called_once_with(text="秘闻", box=[197, 233, 887, 906])

    def test_fate_icon_clicked_then_fixed_offset_then_confirm(self):
        """命中命途选项卡：先点选项卡本体、再点固定偏移的「确定」，最后按 OCR 文字补点。"""
        self._run({"fate3": FATE_POINT}, confirm_box=CONFIRM_TEXT_BOX)

        self.assertEqual(
            self._clicks(),
            [
                FATE_POINT,
                (CONFIRM_OFFSET[0], FATE_POINT[1] - CONFIRM_OFFSET[1]),
                CONFIRM_TEXT_POINT,
            ],
        )

    def test_fate_icon_clicked_even_if_confirm_never_appears(self):
        """「确定」按钮一直不出现时只留下那两下快速点击，且 OCR 复核会结束。"""
        engine = self._run({"fate1": FATE_POINT})

        self.assertEqual(
            self._clicks(),
            [FATE_POINT, (CONFIRM_OFFSET[0], FATE_POINT[1] - CONFIRM_OFFSET[1])],
        )
        # 复核走的是右侧竖条的 OCR，不再有 confirm 图片匹配
        self.assertEqual(
            [call.kwargs["box"] for call in engine.ts.find_with_box.call_args_list],
            [CONFIRM_BOX],
        )
        self.assertEqual(
            [call.args[0] for call in engine.check.call_args_list].count("confirm"), 0
        )


class SelectEventTest(unittest.TestCase):
    """core/simulated/engine.py 的 select_event（any_fate 也会 super() 调到它）。"""

    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.simulated.engine.key_mouse_manager", self.manager))
        self.logger = Mock()
        self.enterContext(patch("core.simulated.engine.CUS_LOGGER", self.logger))
        self.clock = _FakeClock()
        self.engine_time = types.SimpleNamespace(time=self.clock.time, sleep=Mock())
        self.enterContext(patch("core.simulated.engine.time", self.engine_time))

    def _run(self, matched, text_results, event_name=""):
        engine = _StubEngine(matched, text_results, event_name=event_name)
        SimulatedUniverse.select_event(engine)
        return engine

    def _error_messages(self):
        return [call.args[0] for call in self.logger.error.call_args_list]

    def _warning_messages(self):
        return [call.args[0] for call in self.logger.warning.call_args_list]

    def _info_messages(self):
        return [call.args[0] for call in self.logger.info.call_args_list]

    def _debug_messages(self):
        return [call.args[0] for call in self.logger.debug.call_args_list]

    def _run_with_options(self, event_name="选择事件"):
        """兜底路径用真实现：OCR 在选项区域里识别到一个选项，但优选项一个都没命中。"""
        engine = _StubEngine(
            {},
            {"休息区": False},
            event_name=event_name,
            options=[{"raw_text": OPTION_TEXT, "box": OPTION_BOX}],
        )
        SimulatedUniverse.select_event(engine)
        return engine

    def test_prior_option_matched_inside_option_area_is_clicked(self):
        """优选项在识别到的选项行里命中时按 OCR 文本框中心点击（不再整屏找优选项文字）。"""
        engine = _StubEngine({}, {"休息区": False}, options=[{"raw_text": OPTION_TEXT, "box": OPTION_BOX}])
        engine.event_prior = [OPTION_TEXT]
        engine.click_event_prior = SimulatedUniverse.click_event_prior.__get__(engine)
        SimulatedUniverse.select_event(engine)

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1510 / 1920, 1 - 660 / 1080)],
        )
        # 优选项这条路也要把「确定」的固定偏移传下去（按命中选项的文本框算）
        self.assertEqual(engine.confirm_event.call_args.kwargs["point"], CONFIRM_FIXED_POINT)
        # 优选项命中了，不该落进「没有匹配到优选项」的兜底分支
        self.assertEqual(self._error_messages(), [])
        # click_text 只用来找「休息区」，没有拿它去点选项文字
        self.assertEqual(
            [call.kwargs["text"] for call in engine.click_text.call_args_list], ["休息区"]
        )

    def test_prior_option_picks_its_own_row_among_several(self):
        """一帧里有多条选项时，点的是命中优选项的那一条的中心（不是第一条、也不是最后一条）。"""
        engine = _StubEngine({}, {"休息区": False})
        engine.event_prior = ["选择事件"]
        stars = [{"x": STAR_X, "y": 424, "score": 0.99}, {"x": STAR_X, "y": 602, "score": 0.99}]
        engine.stub_ocr(
            stars=stars,
            bands={
                tuple(engine._star_band(stars[0])): [
                    {"raw_text": "离开。", "box": [1396, 1600, 410, 432]}
                ],
                tuple(engine._star_band(stars[1])): [
                    {"raw_text": "选择事件", "box": [1400, 1700, 588, 610]}
                ],
            },
        )
        SimulatedUniverse.select_event(engine)

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1550 / 1920, 1 - 599 / 1080)],
        )

    def test_empty_option_area_clicks_nothing_while_leaving_the_event(self):
        """选项区一个字都没有（选完选项正在进战斗）：不点、不刷三次 warning。"""
        self._run({}, {"休息区": True})

        self.manager.click.assert_not_called()
        self.assertEqual(self._error_messages(), [])
        self.assertFalse(
            any("一个都没匹配上" in call.args[0] for call in self.logger.warning.call_args_list)
        )
        self.assertTrue(any("本帧不点击" in msg for msg in self._debug_messages()))

    def test_dialogue_marker_clicked_before_the_push_icons(self):
        """顺序是金色▼在前（对话阶段），两者同帧命中时点▼，推进图标这一帧不再判定。"""
        engine = self._run({"arrow": ICON_POINT, "arrow_dialog": DIALOG_POINT}, {"休息区": False})

        self.assertEqual([call.args for call in self.manager.click.call_args_list], [DIALOG_POINT])
        self.assertEqual([call.args[0] for call in engine.check.call_args_list], ["arrow_dialog"])

    def test_push_icons_are_checked_in_the_old_json_order(self):
        """▼ 之后三个推进图标按删除前 JSON 的顺序判定：arrow → arrow_1 → shop_herta。"""
        engine = self._run(
            {"shop_herta": SHOP_HERTA_POINT, "arrow_1": ARROW_1_POINT}, {"休息区": False}
        )

        self.assertEqual([call.args for call in self.manager.click.call_args_list], [ARROW_1_POINT])
        self.assertEqual(
            [call.args[0] for call in engine.check.call_args_list],
            ["arrow_dialog", "arrow", "arrow_1"],
        )

    def test_option_icons_are_read_before_the_option_texts(self):
        """选项图标（星号 ※ 或命途图标）和选项文字绑定：先认出所有图标、再只 OCR 每个图标右侧的横条；图标本身不点。"""
        engine = _StubEngine(
            {}, {"休息区": False}, stars=[{"x": STAR_X, "y": 424, "score": 0.99}]
        )
        SimulatedUniverse.select_event(engine)

        # 两遍匹配：先只认 ※（names=("star",)），没命中优选项才补认命途图标（见 select_event）
        engine.event_option_icons.assert_called_once_with(("star",))
        # 认到图标但选项横条里没文字：这是原有行为（debug + 不点击），不该报「未识别到有效触发器」
        self.manager.click.assert_not_called()
        self.assertFalse(
            any("未识别到有效触发器" in msg for msg in self._warning_messages())
        )

    def test_nothing_recognized_logs_one_info(self):
        """整个 select_event 什么都没识别到（连星号都没有）时补一条 info，且同一状态不刷屏。"""
        engine = self._run({}, {})
        # 同一个引擎再跑一帧：状态没变，不该再打第二条
        SimulatedUniverse.select_event(engine)

        self.manager.click.assert_not_called()
        infos = [msg for msg in self._info_messages() if "救世主" in msg]
        self.assertEqual(len(infos), 1)

    def test_options_all_unmatched_falls_back_to_a_recognized_option(self):
        """没匹配到优选项（没有战斗的事件）：在识别到的选项里挑一个点，避免卡在事件界面。"""
        engine = self._run_with_options()

        self.assertEqual([call.args for call in self.manager.click.call_args_list], [OPTION_POINT])
        self.assertTrue(engine.confirm_event.called)

    def test_unmatched_prior_only_adds_the_fate_pass(self):
        """优选项没命中时只补认一遍命途图标：两遍都是「在已有整屏 OCR 结果里按框过滤」（forward=0），
        不重开整屏 OCR、不轮询重试（完美大挑战实测重开一轮要 0.7s / 1.4s）。"""
        engine = self._run_with_options()

        # 同一个星号横条在 ※ 与命途两遍里各过滤一次；两次都没 forward/re_screen → 没有重截屏、没有重 OCR
        band = engine._star_band(engine.stars[0])
        self.assertEqual(
            [call.kwargs["box"] for call in engine.ts.find_with_box.call_args_list],
            [band, band],
        )
        self.assertTrue(
            all(
                call.kwargs["forward"] is False and call.kwargs["re_screen"] is False
                for call in engine.ts.find_with_box.call_args_list
            )
        )
        self.assertFalse(self.engine_time.sleep.called)

    def test_option_matched_without_confirm_falls_back_to_option_then_confirm(self):
        """事件选项匹配上但「确认」一直没出现：同样挑一个识别到的选项，再点它的「确定」。"""
        engine = self._run_with_options()

        self.assertEqual([call.args for call in self.manager.click.call_args_list], [OPTION_POINT])
        self.assertTrue(engine.confirm_event.called)

    def test_rest_area_still_clicks_its_own_hit_point(self):
        """「休息区」命中时按老行为点它自己的固定位置，不落入兜底。"""
        engine = _StubEngine(
            {}, {"休息区": True}, options=[{"raw_text": "选择事件", "box": OPTION_BOX}]
        )
        engine.ts.find_text = Mock(return_value=OPTION_OCR_BOX)
        SimulatedUniverse.select_event(engine)

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1510 / 1920, 1 - 660 / 1080), (0.1667, 0.2592)],
        )
        # 没有落进「连续 3 次没匹配到优选项」的兜底分支
        self.assertEqual(self._error_messages(), [])

    def test_shop_screen_is_left_to_its_own_action(self):
        """左上角写着「奇物商店」时让路：不认选项、不点任何东西（04:42 误点奇物商店的回归）。"""
        for label in ("奇物商店", "奇物商", "奇物"):
            engine = _StubEngine(
                {},
                {"休息区": False},
                ui_label=label,
                options=[{"raw_text": OPTION_TEXT, "box": OPTION_BOX}],
            )
            SimulatedUniverse.select_event(engine)

            self.manager.click.assert_not_called()
            self.assertTrue(any(label[:2] in msg for msg in self._debug_messages()))

    def test_ui_label_is_reread_every_frame(self):
        """界面标题不能缓存：读出「奇物商店」让路后，切回事件界面必须继续处理（缓存会让它永远让路）。"""
        engine = _StubEngine({}, {"休息区": False}, ui_label="奇物商店")
        labels = ["奇物商店", "事件"]
        engine.ts.ocr_one_row = Mock(
            side_effect=lambda _img, box: labels.pop(0) if box == engine.EVENT_LABEL_BOX else ""
        )

        SimulatedUniverse.select_event(engine)
        self.manager.click.assert_not_called()
        self.assertTrue(any("奇物商店" in msg for msg in self._debug_messages()))

        self.logger.debug.reset_mock()
        SimulatedUniverse.select_event(engine)
        # 第二帧标题读到「事件」：不再让路，继续走到选项阶段
        self.assertTrue(
            any("选项列表区域没有识别到任何文本" in msg for msg in self._debug_messages()),
            self._debug_messages(),
        )

    def test_event_name_read_from_map_label_and_kept_in_self_event(self):
        """事件名从地图左下角读出来存进 self.event，供后续日志与兜底使用。"""
        engine = self._run_with_options(event_name="超验之镜")

        self.assertEqual(engine.event, "超验之镜")

    def test_event_name_is_not_read_while_only_advancing_dialog(self):
        """对话阶段这一帧只点金色 ▼ 就返回：界面标题与事件名都不读，一次 OCR 都不花。"""
        engine = _StubEngine(
            {"arrow_dialog": DIALOG_POINT}, {"休息区": False}, event_name="超验之镜"
        )
        SimulatedUniverse.select_event(engine)

        self.assertEqual(engine.ts.ocr_one_row.call_args_list, [])
        self.assertEqual(engine.event, "")

    def test_event_name_is_not_read_when_option_area_is_empty(self):
        """选项区一个字都没有（已离开事件界面）时没有任何日志要写事件名，不该花这次 OCR。"""
        engine = self._run({}, {"休息区": True})

        self.assertEqual(self._name_reads(engine), [])
        self.assertEqual(engine.event, "")

    def _name_reads(self, engine):
        """只数「读事件名」那次 OCR（左上角界面标题也是同一个 ocr_one_row）。"""
        return [
            call for call in engine.ts.ocr_one_row.call_args_list
            if call.args[1] == EVENT_NAME_BOX
        ]

    def test_event_name_is_not_read_when_preferred_option_hits(self):
        """优选项命中的正常路径没有任何日志要写事件名，不该花这次 OCR。"""
        engine = _StubEngine(
            {},
            {"休息区": False},
            event_name="超验之镜",
            options=[{"raw_text": "选择事件", "box": OPTION_BOX}],
        )
        SimulatedUniverse.select_event(engine)

        self.assertEqual(self._name_reads(engine), [])
        self.assertEqual(engine.event, "")

    def test_event_name_is_read_once_per_event_and_reused_by_later_logs(self):
        """兜底路径只读一次事件名：select_event 读到的名字被 click_event_option 复用，不再重读。"""
        engine = self._run_with_options(event_name="超验之镜")

        self.assertEqual(len(self._name_reads(engine)), 1)
        self.assertEqual(engine.event, "超验之镜")

    def test_event_name_reader_drops_ui_words_and_punctuation(self):
        """OCR 可能带上「事件/秘闻」字样或标点，读取时清掉，太短的当没读到。"""
        for raw, expected in [
            ("事件 超验之镜", "超验之镜"),
            ("秘闻·兽群·贪赞灾厄", "兽群·贪赞灾厄"),
            ("，超验之", "超验之"),
            ("事件", ""),
            ("", ""),
        ]:
            engine = _StubEngine({}, {}, event_name=raw)
            self.assertEqual(SimulatedUniverse.read_event_name(engine), expected, raw)

    def test_warning_log_carries_real_event_name(self):
        """兜底点击那条 warning 要带上真实事件名，而不是「未知事件」，而且不是 error。"""
        self._run_with_options(event_name="超验之镜")

        self.assertTrue(
            any("「超验之镜」选项列表里没有优选项命中" in msg for msg in self._warning_messages()),
            self._warning_messages(),
        )
        self.assertEqual(self._error_messages(), [])

    def test_fallback_skips_option_whose_text_sits_outside_option_area(self):
        """OCR 报出来的文本框若落在选项区域之外（例如左侧导航/顶部标签），兜底不点它，并留下放弃原因。"""
        engine = _StubEngine({}, {"休息区": False})
        engine.event_option_rows = Mock(
            return_value=[
                {"raw_text": OPTION_TEXT, "box": [200, 60, 460, 100], "lines": [], "icon": {}}
            ]
        )
        SimulatedUniverse.select_event(engine)

        self.manager.click.assert_not_called()
        self.assertTrue(
            any("兜底选项点击点不在选项面板内" in msg for msg in self._warning_messages()),
            self._warning_messages(),
        )
        # 「救世主」那条剧情文案只属于「连星号都没认到」的空状态，兜底放弃不再蹭它
        self.assertFalse(
            any("救世主" in msg for msg in self._info_messages()),
            self._info_messages(),
        )

    def test_top_option_row_is_clickable_when_the_panel_sits_high(self):
        """
        真实卡死帧（银河好人（其三））：首行文字框中心 y=278 比老上边界 320 高，也必须能点。
        选项面板的纵向位置随事件浮动；上边界写 320 时
        这一行会被判成「不在选项列表区域内」，而兜底又正好挑中它 → 每帧放弃点击，卡死在该事件。
        """
        engine = _StubEngine({}, {"休息区": False})
        engine.event_option_rows = Mock(
            return_value=[
                {
                    "raw_text": "米购买一个钻石盒。",
                    "box": [1357, 1591, 265, 292],
                    "lines": [],
                    "icon": {},
                }
            ]
        )
        SimulatedUniverse.select_event(engine)

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1474 / 1920, 1 - 278.5 / 1080)],
        )
        self.assertEqual(self._error_messages(), [])

    def test_fallback_waits_for_the_fading_option_panel_before_deciding(self):
        """
        面板是淡入的：命途图标比选项文字晚约 0.4 s 才画出来
        （虫巢录屏实测 27.10 s 优选项文字已可读，27.13 s fate6 才认得到）。
        面板刚出现的那一两帧先别兜底——那时补认还没有结果，兜底会挑中最长文字
        （虫巢那次挑中的是最后一行「止步于巢穴门口。」）。等满 1.5 s 再照旧兜底点击。
        窗口在 2026-10-24 由 0.8 s 放宽到 1.5 s：按 0.8 s 兜底仍会挑错，所以刚过 0.8 s 也要继续等。
        """
        engine = _StubEngine(
            {},
            {"休息区": False},
            event_name="银河好人（其三）",
            options=[{"raw_text": OPTION_TEXT, "box": OPTION_BOX}],
        )
        engine._option_shown_at = None  # 面板这一帧刚认到选项
        SimulatedUniverse.select_event(engine)

        self.manager.click.assert_not_called()
        self.assertTrue(
            any("本帧不点击" in msg for msg in self._debug_messages()),
            self._debug_messages(),
        )

        # 面板出现后 1.0 s（已过旧的 0.8 s、还没到 1.5 s）：继续等，不兜底。
        # self.clock 每被 time() 读一次前进 0.1 s，故把起点往前挪 0.9 s，到判定时正好过了 1.0 s。
        engine._option_shown_at = self.clock.now - 0.9
        SimulatedUniverse.select_event(engine)
        self.manager.click.assert_not_called()

        # 已经等满 1.5 s：照旧走兜底
        engine._option_shown_at = self.clock.now - 2.0
        SimulatedUniverse.select_event(engine)

        self.assertEqual([call.args for call in self.manager.click.call_args_list], [OPTION_POINT])


    def test_fate_icon_option_is_matched_after_the_star_pass_misses(self):
        """命途图标（「虫巢」的优选项用的是 fate6）只在 ※ 那遍没命中优选项时补认，认到的文字照常参与匹配。"""
        stars = [
            {"x": STAR_X, "y": 480, "score": 0.99, "icon": "star"},
            {"x": STAR_X, "y": 656, "score": 0.99, "icon": "star"},
        ]
        fate_icon = {"x": STAR_X, "y": 283, "score": 0.99, "icon": "fate6"}
        engine = _StubEngine({}, {"休息区": False}, event_name="虫巢", stars=stars)
        # 铁血战士的 event_prior 里有「绞杀它们」：以前这条优选项因为图标不是星号而永远认不到
        engine.event_prior = ["绞杀它们"]
        engine.stub_ocr(
            fate_stars=[fate_icon],
            bands={
                tuple(engine._star_band(fate_icon)): [
                    {"raw_text": "进入虫巢，绞杀它们！", "box": [1354, 1486, 283, 315]}
                ],
                tuple(engine._star_band(stars[0])): [
                    {"raw_text": "深入虫巢。", "box": [1354, 1486, 462, 494]}
                ],
                tuple(engine._star_band(stars[1])): [
                    {"raw_text": "止步于巢穴门口。", "box": [1354, 1584, 641, 672]}
                ],
            },
        )
        engine.confirm_event = Mock(return_value=True)

        SimulatedUniverse.select_event(engine)

        # 先只认 ※（两条，没命中优选项），再补认命途图标（第三条进来，命中「绞杀它们」）
        self.assertEqual(
            [call.args[0] for call in engine.event_option_icons.call_args_list],
            [("star",), ("star",) + FATE_ICON_NAMES],
        )
        # 命途图标那条选项照常走优选项路径：点选项文字的中心，再按整条文字底边点「确定」
        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1420 / 1920, 1 - 299 / 1080)],
        )
        self.assertEqual(
            engine.confirm_event.call_args.kwargs["point"],
            (0.1135, 1 - (315 + 76) / 1080),
        )

    def test_fate_icons_are_only_matched_when_no_prior_hits(self):
        """※ 那遍就命中优选项时不再补认命途图标——普通事件每帧省下 8 张模板（约 115 ms）。"""
        star = {"x": STAR_X, "y": 228, "score": 0.99, "icon": "star"}
        engine = _StubEngine({}, {"休息区": False}, event_name="购买事件", stars=[star])
        engine.event_prior = ["购买1个1星祝福"]
        engine.stub_ocr(
            bands={
                tuple(engine._star_band(star)): [
                    {"raw_text": "购买1个1星祝福。", "box": [1357, 1595, 211, 242]}
                ]
            },
        )
        engine.confirm_event = Mock(return_value=True)

        SimulatedUniverse.select_event(engine)

        self.assertEqual(len(engine.event_option_icons.call_args_list), 1)
        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [(1 - 1476 / 1920, 1 - 226.5 / 1080)],
        )


class ConfirmEventClickTest(unittest.TestCase):
    """选项点中后，还要点浮出的「确定」按钮，事件才会真的往下走（3/4 轮普通事件卡死的根因）。"""

    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.simulated.engine.key_mouse_manager", self.manager))
        self.enterContext(patch("core.simulated.engine.CUS_LOGGER"))
        self.clock = _FakeClock()
        self.enterContext(
            patch(
                "core.simulated.engine.time",
                types.SimpleNamespace(time=self.clock.time, sleep=Mock()),
            )
        )

    def _run(self, matched, confirm_box=None):
        """兜底路径用真实现（含真 confirm_event），OCR 与模板匹配都打桩。"""
        engine = _StubEngine(matched, {"休息区": False})
        engine.stub_ocr(
            options=[{"raw_text": OPTION_TEXT, "box": OPTION_BOX}], confirm_box=confirm_box
        )
        engine.confirm_event = SimulatedUniverse.confirm_event.__get__(engine)
        SimulatedUniverse.select_event(engine)
        return engine

    def test_fixed_offset_clicked_after_fallback_option(self):
        """兜底点中选项后，按「固定偏移」点一下「确定」；OCR 复核读不到文字就结束。"""
        engine = self._run({})

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [OPTION_POINT, CONFIRM_FIXED_POINT],
        )
        # 复核一次就够：选项横条只在 ※/命途两遍里各过滤一次，右侧竖条只查一次；没有轮询、也没有图片匹配
        self.assertEqual(
            [call.kwargs["box"] for call in engine.ts.find_with_box.call_args_list],
            [engine._star_band(engine.stars[0])] * 2 + [CONFIRM_BOX],
        )
        self.assertEqual(
            [call.args[0] for call in engine.check.call_args_list].count("confirm"), 0
        )

    def test_fixed_offset_miss_backfills_with_the_ocr_text_position(self):
        """固定偏移没点中（复核时还能读到「确定」）就按 OCR 文字框中心补点，不会逐帧点偏。"""
        engine = self._run({}, confirm_box=CONFIRM_TEXT_BOX)

        self.assertEqual(
            [call.args for call in self.manager.click.call_args_list],
            [OPTION_POINT, CONFIRM_FIXED_POINT, CONFIRM_TEXT_POINT],
        )
        # 补点位置取自实测帧的文字框 [1676,1728,482,512]（中心 1702,497），不再有 confirm 图片匹配
        self.assertEqual(
            [call.args[0] for call in engine.check.call_args_list].count("confirm"), 0
        )

    def test_confirm_point_uses_the_option_text_line(self):
        """「确定」位置按被点中那条选项「选项文字行」的底边 + 76 算"""
        engine = _StubEngine({})
        row = {
            "raw_text": "购买1个1星祝福。",
            "box": [1357, 1595, 390, 421],  # 星号行 407 → 选项文字行占 393~421
            "lines": [{"raw_text": "购买1个1星祝福。", "box": [1357, 1595, 390, 421]}],
            "icon": {"x": STAR_X, "y": 407, "score": 0.99},
        }
        row2 = {
            "raw_text": "强化2个随机祝福。",
            "box": [1357, 1595, 568, 599],  # 星号行 585
            "lines": [{"raw_text": "强化2个随机祝福。", "box": [1357, 1595, 568, 599]}],
            "icon": {"x": STAR_X, "y": 585, "score": 0.99},
        }

        point = SimulatedUniverse.confirm_point(engine, row)
        point2 = SimulatedUniverse.confirm_point(engine, row2)

        self.assertEqual(point[0], CONFIRM_FIXED_X)
        self.assertAlmostEqual((1 - point[1]) * 1080, 497, delta=2)
        self.assertAlmostEqual((1 - point2[1]) * 1080, 676, delta=2)
        # 说明行不再进横条，所以余量是「选项文字行底边 → 按钮中心」的 76（= 星号行 + 90 − 14）
        self.assertEqual(CONFIRM_TEXT_GAP, 76)

    def test_option_rows_drop_the_confirm_label_line(self):
        """横条里万一读进「确定」按钮文字，不能算成选项的一行（否则「确定」偏移会掉到按钮下方）。"""
        engine = _StubEngine({})
        star = {"x": STAR_X, "y": 424, "score": 0.99}
        lines = [
            {
                "raw_text": WRAPPED_OPTION_LINES[0]["raw_text"],
                "box": WRAPPED_OPTION_LINES[0]["box"],
            },
            {"raw_text": "花费40宇宙碎片。", "box": WRAPPED_OPTION_LINES[1]["box"]},
            {"raw_text": CONFIRM_LABEL, "box": CONFIRM_TEXT_BOX},
        ]
        engine.stub_ocr(stars=[star], bands={tuple(engine._star_band(star)): lines})

        rows = SimulatedUniverse.event_option_rows(engine)

        self.assertEqual(
            [line["raw_text"] for line in rows[0]["lines"]],
            [WRAPPED_OPTION_LINES[0]["raw_text"], "花费40宇宙碎片。"],
        )
        point = SimulatedUniverse.confirm_point(engine, rows[0])
        # 「确定」那一行被剔掉：底边取两行里更靠下的 460，+76 → 536；若把它算进来（底边 512）
        # 就会落到 588，比按钮中心低 91 px，点不到
        self.assertAlmostEqual((1 - point[1]) * 1080, 460 + CONFIRM_TEXT_GAP, delta=1)
        self.assertGreater(CONFIRM_TEXT_BOX[3] + CONFIRM_TEXT_GAP - 497, 80)

    def test_option_rows_are_read_per_star_band(self):
        """每条选项只 OCR 它自己星号右侧的横条：第一条的说明行归到第一条，不会变成独立选项。"""
        engine = _StubEngine({})
        stars = [{"x": STAR_X, "y": 424, "score": 0.99}, {"x": STAR_X, "y": 602, "score": 0.99}]
        lines_a = [
            {"raw_text": "购买1个1星祝福。", "box": [1396, 1750, 410, 432]},
            {"raw_text": "消耗80宇宙碎片。", "box": [1396, 1702, 451, 474]},
        ]
        lines_b = [
            {"raw_text": "强化2个随机祝福。", "box": [1396, 1760, 588, 610]},
            {"raw_text": "消耗180宇宙碎片。", "box": [1396, 1720, 629, 652]},
        ]
        engine.stub_ocr(
            stars=stars,
            bands={
                tuple(engine._star_band(stars[0])): lines_a,
                tuple(engine._star_band(stars[1])): lines_b,
            },
        )

        rows = SimulatedUniverse.event_option_rows(engine)

        self.assertEqual(
            [row["raw_text"] for row in rows], ["购买1个1星祝福。", "强化2个随机祝福。"]
        )
        self.assertEqual([row["lines"] for row in rows], [lines_a, lines_b])
        # 「确定」的偏移按整条（选项行 + 说明行）的底边算：474 + 36
        point = SimulatedUniverse.confirm_point(engine, rows[0])
        self.assertAlmostEqual((1 - point[1]) * 1080, 474 + CONFIRM_TEXT_GAP, delta=1)

    def test_all_option_icons_are_found_not_only_the_best_one(self):
        """check() 只拿得到最高分的那个图标：一帧 3~4 条选项时要靠多目标匹配把它们都认出来；
        ※ 那一遍只认星号，命途图标（「虫巢」优选项用的 fate6）等补认那一遍才认。"""
        star = find_image_by_name("star")
        fate = find_image_by_name("fate6")
        engine = _StubEngine({})
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for top in (212, 391):  # 实测两条选项的 ※ 左边界 x=1342、相差 178.5 px
            frame[top : top + star.shape[0], 1342 : 1342 + star.shape[1]] = star
        # 「虫巢」的优选项用的是命途图标：同一列第三个位置贴一张 fate6
        frame[570 : 570 + fate.shape[0], 1342 : 1342 + fate.shape[1]] = fate
        engine.screen = frame
        engine.get_screen = Mock(return_value=frame)

        stars = SimulatedUniverse.event_option_icons(engine)
        self.assertEqual([icon["icon"] for icon in stars], ["star", "star"])

        icons = SimulatedUniverse.event_option_icons(engine, ("star",) + FATE_ICON_NAMES)

        self.assertEqual([icon["icon"] for icon in icons], ["star", "star", "fate6"])
        for found, (top, template) in zip(icons, ((212, star), (391, star), (570, fate))):
            self.assertAlmostEqual(found["x"], 1342 + template.shape[1] / 2, delta=2)
            self.assertAlmostEqual(found["y"], top + template.shape[0] / 2, delta=2)
        # 认到的结果留在 self._option_icons 里，select_event 靠它判断「连选项图标都没有」
        self.assertEqual(engine._option_icons, icons)


if __name__ == "__main__":
    unittest.main()
