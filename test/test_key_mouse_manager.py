"""验证键鼠操作不会把光标送到游戏窗口之外。

2026-10-11 12:18 前台丢失事故：core/any_fate/engine.py:1096 传入的浮点数 y
减去 0.1139 后变成负数，换算成屏幕坐标落在游戏窗口下边界以下 15px，
点击送给了窗口下方的自动化工具窗口，抢走游戏前台并卡住任务。
本测试用事故当时的像素坐标走真实队列，确认越界操作被拦下。
"""

import unittest
from unittest.mock import patch

import numpy as np

from tool.key_mouse_manager import KeyMouseManager

# 与实机参数一致：客户区 1920x1080 贴在窗口右下角，窗口右下角在屏幕 (1940, 1110)
WINDOW_RIGHT = 1940
WINDOW_BOTTOM = 1110
CLIENT_WIDTH = 1920
CLIENT_HEIGHT = 1080

# 事故请求点：换算成屏幕坐标是 (1716, 1125)，比窗口下边界 1110 低 15px
INCIDENT_X = 1696
INCIDENT_Y = 1095


class KeyMouseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.manager = KeyMouseManager()
        self.manager.set_screen_params(WINDOW_RIGHT, WINDOW_BOTTOM, CLIENT_WIDTH, CLIENT_HEIGHT)
        self.addCleanup(self.manager.stop)
        self.logger = self.enterContext(patch("tool.key_mouse_manager.CUS_LOGGER"))
        self.cursor = self.enterContext(patch("tool.key_mouse_manager.win32api.SetCursorPos"))
        self.click = self.enterContext(patch("tool.key_mouse_manager.pyautogui.click"))
        self.drag_to = self.enterContext(patch("tool.key_mouse_manager.pyautogui.dragTo"))
        self.scroll = self.enterContext(patch("tool.key_mouse_manager.pyautogui.scroll"))
        self.mouse_event = self.enterContext(patch("tool.key_mouse_manager.win32api.mouse_event"))
        self.manager.start()

    def click_at(self, x, y):
        self.manager.click_point(x, y)
        self.manager.wait()

    def test_pixel_click_is_offset_by_client_origin(self):
        """像素坐标加客户区左上角的屏幕坐标即得屏幕坐标；右下角边界算窗口内。"""
        for (x, y), expected in (((0, 0), (20, 30)), ((1920, 1080), (1940, 1110))):
            with self.subTest(x=x, y=y):
                self.cursor.reset_mock()
                self.click.reset_mock()
                self.click_at(x, y)
                self.cursor.assert_called_once_with(expected)
                self.click.assert_called_once_with()

    def test_incident_click_below_window_is_skipped(self):
        """事故坐标必须被跳过：不移动光标、不点击，并记录一次越界警告。"""
        self.click_at(INCIDENT_X, INCIDENT_Y)
        self.cursor.assert_not_called()
        self.click.assert_not_called()
        self.logger.warning.assert_called_once()
        # 警告参数：操作名、窗口范围、请求像素坐标、换算后的屏幕坐标
        self.assertEqual(self.logger.warning.call_args.args[1], "点击")
        self.assertEqual(self.logger.warning.call_args.args[-2:], (1716, 1125))

    def test_repeated_out_of_range_click_warns_once(self):
        """同一个越界点反复请求只警告一次，避免刷屏。"""
        for _ in range(3):
            self.click_at(INCIDENT_X, INCIDENT_Y)
        self.cursor.assert_not_called()
        self.click.assert_not_called()
        self.logger.warning.assert_called_once()

    def test_click_outside_other_edges_is_skipped(self):
        """左上、右、下三个方向越界同样跳过。"""
        for x, y in ((-5, 540), (1925, 540), (960, 1085)):
            with self.subTest(x=x, y=y):
                self.click_at(x, y)
        self.cursor.assert_not_called()
        self.click.assert_not_called()

    def test_click_on_window_boundary_is_allowed(self):
        """下边界正好等于窗口下边界时允许点击。"""
        self.click_at(INCIDENT_X, CLIENT_HEIGHT)
        self.cursor.assert_called_once_with((1716, 1110))
        self.click.assert_called_once_with()

    def test_click_inside_window_still_clicks(self):
        """窗口内的正常点击不受越界拦截影响。"""
        self.click_at(215, 896)
        self.cursor.assert_called_once_with((235, 926))
        self.click.assert_called_once_with()

    def test_out_of_range_warning_reports_pixel_coordinates(self):
        """越界警告打印调用方传入的像素坐标，而不是换算后的屏幕坐标。"""
        self.click_at(1940, 540)
        self.cursor.assert_not_called()
        self.logger.warning.assert_called_once()
        self.assertEqual(self.logger.warning.call_args.args[1], "点击")
        self.assertEqual(self.logger.warning.call_args.args[-4:-2], (1940, 540))

    def test_turn_splits_degrees_into_steps_no_wider_than_thirty(self):
        """45 度按每段不超过 30 度拆成 30 + 15，正角度向右转。"""
        self.manager.turn(45)
        self.manager.wait()
        self.assertEqual(self.mouse_event.call_count, 2)
        for call in self.mouse_event.call_args_list:
            self.assertGreater(call.args[1], 0)
        self.click.assert_not_called()

    def test_scroll_inside_window_still_scrolls(self):
        """窗口内滚轮：光标先移到指定像素点，方向为负时向下滚一格。"""
        self.manager.scroll_point(960, 540, direct=-1)
        self.manager.wait()
        self.cursor.assert_called_once_with((980, 570))
        self.scroll.assert_called_once_with(-120)

    def test_scroll_outside_window_is_skipped(self):
        """越界滚轮直接跳过，不移动光标也不滚动。"""
        self.manager.scroll_point(INCIDENT_X, INCIDENT_Y, direct=-1)
        self.manager.wait()
        self.cursor.assert_not_called()
        self.scroll.assert_not_called()

    def test_drag_inside_window_still_drags(self):
        """窗口内拖拽：起始点移动光标并调用一次 dragTo。"""
        self.manager.drag_point(960, 540, 768, 432)
        self.manager.wait()
        self.cursor.assert_called_once_with((980, 570))
        self.assertEqual(self.drag_to.call_args.args[:2], (788, 462))

    def test_drag_outside_window_is_skipped(self):
        """终点越界时连起点都不移动，否则左键会一直按在错误的位置上。"""
        self.manager.drag_point(960, 540, INCIDENT_X, INCIDENT_Y)
        self.manager.wait()
        self.cursor.assert_not_called()
        self.drag_to.assert_not_called()

    def test_float_center_from_ocr_is_rounded_to_integer(self):
        """识别框中心是 (x1 + x2) / 2 算出来的小数，入队前要四舍五入到整像素。

        视觉识别拿到的框边界常是 numpy 整数，求和除以 2 会变成 np.float64，
        而 win32api.SetCursorPos 只接受整数；不在入队前收口就会抛 TypeError 中断任务。
        """
        for (x, y), expected in (
                ((np.float64(1290.0), np.float64(796.5)), (1310, 826)),
                ((np.float64(1290.6), np.float64(796.6)), (1311, 827))):
            with self.subTest(x=float(x), y=float(y)):
                self.cursor.reset_mock()
                self.manager.click_point(x, y)
                self.manager.wait()
                self.cursor.assert_called_once_with(expected)
                # Mock 不校验类型，必须显式确认进 win32api 的是 python 整数
                for value in self.cursor.call_args.args[0]:
                    self.assertIsInstance(value, int)

    def test_drag_with_float_center_is_rounded_to_integer(self):
        """拖拽的两个端点同样要收成整像素再入队。"""
        self.manager.drag_point(np.float64(960.4), np.float64(540.6),
                                np.float64(768.6), np.float64(432.6))
        self.manager.wait()
        self.cursor.assert_called_once_with((980, 571))
        self.assertEqual(self.drag_to.call_args.args[:2], (789, 463))

    def test_click_from_box_logs_box_and_click_point(self):
        """点框中心时日志要同时给出源框和实际点击位置。

        框边界来自识别结果，常是带小数的 numpy 值；日志里的框同样收成整像素，
        才能和点击坐标并排核对落点是不是在框该在的位置。
        """
        self.manager.click_point(
            np.float64(150.0), np.float64(350.6),
            box=[np.float64(100), np.float64(200), np.float64(300), np.float64(400)])
        self.manager.wait()
        self.cursor.assert_called_once_with((170, 381))
        logged = str(self.logger.debug.call_args)
        self.assertIn("'x': 150", logged)
        self.assertIn("'y': 351", logged)
        self.assertIn("'box': [100, 200, 300, 400]", logged)

    def test_click_without_box_keeps_old_log_shape(self):
        """没有来源框的纯坐标点击不带 box 字段，日志与改版前一致。"""
        self.click_at(215, 896)
        self.assertNotIn("'box'", str(self.logger.debug.call_args))


if __name__ == "__main__":
    unittest.main()
