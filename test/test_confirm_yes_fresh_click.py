"""
「确认」按钮点击位置的回归测试（bug 1：铁血战士作弊窗被乱点关掉）。

背景：``confirm_yes`` 原来先用 ``click_text(text="确认", click=False)`` 识别一下，然后直接点
``self.tx / self.ty``。``click_text`` 只返回 True/False，从不写 self.tx/self.ty——那是上一次
``check()`` 留下的残留坐标。于是「识别到的是这一帧的确认按钮，点下去的却是上一次残留的东西」，
日志 log_2026-10-20-18-54.txt 里 23:32:34,537 那一下点的就是 (0.60546875, 0.2375)
（屏幕约 758,824），而这一帧 OCR 到的「确认」文字在 [1169, 1223, 811, 841]，按钮中心约 (1196, 826)。
这一下点在作弊选项窗的列表上，把作弊流程打断了。

当前生产契约（``core/simulated/engine.py`` 的 ``confirm_yes``）：
- 先做作弊窗守卫：``click_text(text="作弊", box=[923,996,230,270], click=False, allow_fail=True)``
  命中就 debug「当前处于作弊选项窗，跳过点击「确认」」并返回 0，**连 OCR 都不做**；
- 点击位置只取**这一刻重新截图**后区域 OCR 到的「确认」文字块
  （``find_with_box(box=[232,1690,154,928], forward=True, re_screen=True)``：只给 ``forward`` 用的是
  缓存帧，那就又变成「点上一帧的画面」）；
- 弹窗标题里也可能带「确认」（如「确认丢弃祝福「X」？」），按钮永远在标题下面，所以取最靠下的
  那一块文字（OCR 顺序不保证，不用「第一个」）；
- 这一帧没认到「确认」文字就 warning「没识别到弹窗的「确认」文字，等下一帧重试」、什么都不点；
- 找到按钮后只点击一次并 ``wait()``，不做点击后的二次识别或补点；
- 所有路径都返回 0。

这里的替身不需要游戏：OCR 结果由 ts.find_with_box 按「缓存帧 / 新截图」分别返回，键鼠操作被记录，
断言的是「点到的是不是这一刻画面上那块文字的中心」。
"""

import unittest
from unittest.mock import Mock, patch

from importing import load_img

# core.simulated.engine 在导入期会读图像记忆切片，需要先装载图像缓存（同其它内核测试）。
load_img()

from core.simulated.engine import SimulatedUniverse


def center(box):
    return (box[0] + box[1]) / 2, (box[2] + box[3]) / 2


def line(text, box):
    return {"raw_text": text, "box": list(box)}


# 日志里真实出现过的两行：弹窗标题、弹窗底部「确认」按钮（标题也含「确认」两个字）
TITLE = line("确认丢弃祝福「无根据颂歌」？", [788, 1117, 512, 539])
CONFIRM = line("确认", [1169, 1223, 811, 841])
# 缓存帧（上一次截图）里的「确认」：位置明显不同，用来抓「用了旧画面」
CONFIRM_CACHED = line("确认", [300, 354, 611, 641])
# 弹窗「确认」文字的识别区域（1920x1080 基准）与作弊窗标题区域
CONFIRM_AREA_BOX = [232, 1690, 154, 928]
CHEAT_TITLE_BOX = [923, 996, 230, 270]

# 老实现点的残留坐标（23:32:34,537 那次 click 的镜像比例 0.60546875,0.2375，换算成像素约为 758,824）
STALE_X, STALE_Y = 758, 824


class _StubConfirmEngine(SimulatedUniverse):
    """只保留 confirm_yes / click_confirm_text 的真实实现，截图、OCR 与键鼠全部打桩。"""

    def __init__(self, rows, cached_rows=None, cheat_window=False):
        self.xx, self.yy = 1920, 1080
        # self.screen 是上一次截图的缓存（forward=True 读它），get_screen() 才是此刻的画面
        self.screen = list(rows if cached_rows is None else cached_rows)
        self.fresh = list(rows)
        # check() 残留的坐标：现在的实现绝不能再用它
        self.tx, self.ty = STALE_X, STALE_Y
        self.confirm_boxes = []
        self.click_text = Mock(return_value=cheat_window)
        self.ts = Mock()
        self.ts.find_with_box = Mock(side_effect=self._ocr)

    def click_confirm_text(self, box):
        self.confirm_boxes.append(list(box))
        super().click_confirm_text(box)

    def get_screen(self):
        return self.fresh

    def _ocr(self, box=None, redundancy=10, forward=0, mode=0, re_screen=False):
        """
        按 core/simulated/ocr.py:284-300 的取帧规则返回落在这个框里的文字行：真实实现只有
        ``re_screen and forward`` 才在这一刻重新截图，否则 ``forward`` 读的是缓存帧 self.screen；
        桩按 re_screen 取帧（被测调用点固定 forward=True）。
        """
        frame = self.get_screen() if re_screen else self.screen
        box = list(box or [0, self.xx, 0, self.yy])
        return [
            item for item in frame
            if isinstance(item, dict)
            and box[0] <= item["box"][0] and item["box"][1] <= box[1]
            and box[2] <= item["box"][2] and item["box"][3] <= box[3]
        ]


class ConfirmYesTest(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.simulated.engine.key_mouse_manager", self.manager))
        self.logger = self.enterContext(patch("core.simulated.engine.CUS_LOGGER", Mock()))

    def make_engine(self, rows, **kwargs):
        self.engine = _StubConfirmEngine(rows, **kwargs)
        return self.engine

    def assertCheatGuardChecked(self):
        self.engine.click_text.assert_called_once_with(
            text="作弊", box=CHEAT_TITLE_BOX, click=False, allow_fail=True)

    def assertClicked(self, *boxes):
        """断言点击落在文字框中心（click_point 收到的是 1920x1080 像素坐标），且不是残留坐标。"""
        self.assertEqual(self.manager.click_point.call_count, len(boxes))
        for clicked, box in zip(self.manager.click_point.call_args_list, boxes):
            actual = clicked.args
            expected = center(box)
            self.assertAlmostEqual(actual[0], expected[0], places=6)
            self.assertAlmostEqual(actual[1], expected[1], places=6)
            self.assertNotEqual((actual[0], actual[1]), (STALE_X, STALE_Y))

    def test_clicks_the_confirm_text_from_a_fresh_screenshot(self):
        """点的是重新截图后识别到的「确认」按钮中心（缓存帧里那块位置不算数）。"""
        engine = self.make_engine([CONFIRM], cached_rows=[CONFIRM_CACHED])

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        self.assertCheatGuardChecked()
        self.assertClicked(CONFIRM["box"])
        self.assertEqual(engine.confirm_boxes, [CONFIRM["box"]])
        self.assertEqual(self.manager.wait.call_count, 1)
        self.assertEqual(engine.ts.find_with_box.call_count, 1)

    def test_ocr_uses_the_whole_confirm_dialog_area_on_a_fresh_frame(self):
        """识别区域必须与「确认纯文本」触发框一致，且点击前要新截图。"""
        engine = self.make_engine([CONFIRM])

        engine.confirm_yes()

        engine.ts.find_with_box.assert_called_once_with(
            box=CONFIRM_AREA_BOX, forward=True, re_screen=True)
        # 识别区域的底边在按钮文字下面，且排除右下角的「确认效果」（y 961~994）
        box = engine.ts.find_with_box.call_args.kwargs["box"]
        self.assertGreater(box[3], CONFIRM["box"][3])
        self.assertLess(box[3], 961)

    def test_does_nothing_while_the_cheat_dialog_is_open(self):
        """作弊选项窗正开着：那个「确认」属于作弊流程，状态机不能代点，连 OCR 都不该做。"""
        engine = self.make_engine([TITLE, CONFIRM], cheat_window=True)

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        self.assertCheatGuardChecked()
        engine.ts.find_with_box.assert_not_called()
        self.assertEqual(engine.confirm_boxes, [])
        self.manager.click_point.assert_not_called()
        self.manager.wait.assert_not_called()
        self.assertIn("当前处于作弊选项窗", str(self.logger.debug.call_args_list))

    def test_does_not_click_when_the_confirm_text_is_missing(self):
        """这一帧没认到「确认」就什么都不点：点残留坐标只会乱点，等下一帧重试。"""
        engine = self.make_engine([line("取消", [1000, 1080, 811, 841])])

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        self.assertCheatGuardChecked()
        engine.ts.find_with_box.assert_called_once()
        self.assertEqual(engine.confirm_boxes, [])
        self.manager.click_point.assert_not_called()
        self.manager.wait.assert_not_called()
        self.assertIn("没识别到弹窗的「确认」文字", str(self.logger.warning.call_args))

    def test_does_nothing_when_ocr_returns_nothing(self):
        """OCR 什么都认不到（空列表）同样不点、不崩。"""
        engine = self.make_engine([])

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        engine.ts.find_with_box.assert_called_once()
        self.manager.click_point.assert_not_called()
        self.assertIn("没识别到弹窗的「确认」文字", str(self.logger.warning.call_args))

    def test_does_not_recheck_or_click_again_when_the_button_survives(self):
        """点击后按钮仍可识别也不复核、不补点，避免重复触发确认。"""
        engine = self.make_engine([TITLE, CONFIRM])

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        self.assertClicked(CONFIRM["box"])
        engine.ts.find_with_box.assert_called_once()
        self.assertEqual(self.manager.wait.call_count, 1)

    def test_title_above_the_button_is_not_clicked(self):
        """标题里也带「确认」：按钮在标题下面，要取最靠下的那一块，绝不点标题。"""
        engine = self.make_engine([TITLE, CONFIRM])

        engine.confirm_yes()

        self.assertClicked(CONFIRM["box"])
        self.assertNotEqual(engine.confirm_boxes[0], TITLE["box"])

    def test_ocr_order_does_not_matter(self):
        """OCR 返回顺序不保证：按钮那块排在前面时也要点按钮，不是「第一个命中」。"""
        engine = self.make_engine([CONFIRM, TITLE])

        engine.confirm_yes()

        self.assertClicked(CONFIRM["box"])

    def test_rows_without_usable_text_are_ignored(self):
        """OCR 行可能缺 raw_text 或 raw_text 为 None：不能因此报错，也不能被当成「确认」。"""
        engine = self.make_engine([
            {"box": [788, 1117, 512, 539]},
            {"raw_text": None, "box": [800, 900, 600, 630]},
            CONFIRM,
        ])

        result = engine.confirm_yes()

        self.assertEqual(result, 0)
        self.assertClicked(CONFIRM["box"])


if __name__ == "__main__":
    unittest.main()
