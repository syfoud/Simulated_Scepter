import ctypes
import math
import os
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime
from math import cos, sin

import cv2 as cv
import numpy as np
import pythoncom
import win32com.client
import win32con
import win32gui
import win32print
from PIL import Image, ImageDraw, ImageFont

from diver import merge_text
from route import PATHS
from tool.currency.config import config
from tool.currency.ocr import get_global_my_ts
from tool.currency.text_key import text_keys
from tool.GLOBAL import (
    factor,
    get_global_stop_flag,
    key_mouse_manager,
    set_global_stop_flag,
)
from tool.log import CUS_LOGGER, log_emitter
from tool.screenshot import Screen
from tool.timer import timer
from tool.utils.game_window import (
    BASE_HEIGHT,
    BASE_WIDTH,
    CLOUD_WINDOW_KIND,
    find_game_window,
    get_client_screen_rect,
    is_supported_resolution,
    set_game_foreground,
)
from tool.utils.get_win_rect import get_window_rect
from tool.utils.image_tool import find_image_by_name, find_image_in_folder
from tool.utils.minimap_util import MINIMAP_RADIUS, POSITION_SEARCH_SCALE, get_minimap
from tool.utils.mminimap import PositionPredict


def set_forground():
    try:
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        if getattr(sys, 'frozen', False):
            shell.SendKeys(" ")  # Undocks my focus from Python IDLE
        else:
            shell.SendKeys("")
        set_game_foreground()
    except Exception:
        pass


def sprint():
    CUS_LOGGER.debug("「救世主，带领吾等前进吧。」")
    if config.long_press_sprint:
        key_mouse_manager.keyDown('shift')
    else:
        key_mouse_manager.press('shift')


def get_dis(x, y):
    """
    返回两点间的直线距离
    """
    return ((x[0] - y[0]) ** 2 + (x[1] - y[1]) ** 2) ** 0.5





class CurrencyUtils:
    def __init__(self,speed=False):
        #层数是否变动
        self.floor_change = False
        self.state = None
        self.ang = 270
        #是否速通
        self.speed = speed
        #当前计算坐标
        self.now_loc = [0,0]
        #裁剪大地图范围
        self.cut_pos = None
        self.mini_state = 0
        self.target = set()
        self.fps_list = []
        self.check_bonus = 1
        self._stop = False
        self.stop_move = 0
        self.multi = config.multi
        self.diffi = config.diffi
        self.fate = config.fate
        self.my_fate = -1
        self.fail_count = 0
        self.first_mini = 1
        self.ts = get_global_my_ts(father=self)
        self.last_info = ''
        self.target_type = -1
        self.f_time = 0
        self.slow = 0
        self.allow_e = 1
        self.quan = 0
        self.bai_e=0
        self.img_map = dict()
        self.should_update_map=True
        self.big_map = None
        #红色阈值，避免误识别无限循环，识别到后会不断减少
        self.red_threshold=4500
        #是否有更新地图线程
        self.has_update=False
        #调试显示用地图
        self.debug_map = None
        #目标坐标
        self.target_loc = None
        #地图集合
        self.img_set = []
        #是否拥有黄泉
        self.quan = 0
        self.bai_e = 0
        self.skill_num=5
        #上次交互时间
        self.quit = 0
        # 用于存储tmp地图
        self.pos_map = None
        self.target_type=-1
        #当前层数
        self.floor = -1
        #最佳匹配地图编号
        self.now_map = None
        # 最佳匹配地图相似度
        self.now_map_sim = None
        #上次截屏时间
        self.last_get_screen_time = None
        #上次路径状态日志时间
        self.last_path_state_time = None
        #上次更新状态时间
        self.last_update_time = None
        #默认匹配阈值
        self.threshold = 0.97
        #位置预测
        self.pos_predictor=PositionPredict()
        set_forground()
        self.tk = text_keys()
        self.debug, self.find = 0, 1
        self.bx, self.by = 1920, 1080
        CUS_LOGGER.warning("我会等待那一天的到来。一直等待下去。总有一天……会有人翻开这近乎「永恒」的一页……(等待游戏窗口)")
        # 使用全局停止标志，避免__init__阻塞导致无法停止
        start_time = time.time()
        timeout = 300  # 5分钟超时
        while not get_global_stop_flag():
            try:
                re=self.get_xy()
                if re:
                    break
                # 检查是否超时
                if time.time() - start_time > timeout:
                    CUS_LOGGER.error(f"等待游戏窗口超时({timeout}秒)，请检查游戏是否启动")
                    raise TimeoutError(f"等待游戏窗口超过{timeout}秒")
            except TimeoutError:
                raise
            except Exception:
                traceback.print_exc()
                time.sleep(0.3)
                pass
        if get_global_stop_flag():
            CUS_LOGGER.debug("初始化被用户中断")
            set_global_stop_flag(False)  # 重置标志
            return
        self.order = config.order
        self.sct = Screen()
    def get_xy(self):
        game_window = find_game_window(prefer_foreground=True)
        if game_window is None:
            time.sleep(0.3)
            return 0
        hwnd = game_window.hwnd
        Text = game_window.title
        self.game_hwnd = hwnd
        self.game_window_kind = game_window.kind
        self.xx = game_window.client_width
        self.yy = game_window.client_height
        if game_window.kind == CLOUD_WINDOW_KIND:
            self.x0, self.y0, self.x1, self.y1 = get_client_screen_rect(hwnd)
        else:
            self.x0, self.y0, self.x1, self.y1 = get_window_rect(hwnd)
        self.full = self.x0 == 0 and self.y0 == 0
        self.x0 = max(0, self.x1 - self.xx)  # + 9 * self.full
        self.y0 = max(0, self.y1 - self.yy)  # + 9 * self.full
        if game_window.kind != CLOUD_WINDOW_KIND and (
                (self.xx == 1920 or self.yy == 1080)
                and self.xx >= 1920
                and self.yy >= 1080
        ):
            self.x0 += (self.xx - 1920) // 2
            self.y0 += (self.yy - 1080) // 2
            self.x1 -= (self.xx - 1920) // 2
            self.y1 -= (self.yy - 1080) // 2
            self.xx, self.yy = 1920, 1080
        if not is_supported_resolution(game_window.kind, self.xx, self.yy):
            if game_window.kind == CLOUD_WINDOW_KIND:
                CUS_LOGGER.error(
                    f"云游戏窗口大小错误 {self.xx} {self.yy}，"
                    f"请将窗口调整到接近{BASE_WIDTH}*{BASE_HEIGHT}"
                )
            else:
                CUS_LOGGER.error(f"分辨率错误 {self.xx} {self.yy} 请设为1920*1080")
            time.sleep(0.3)
            return 0
        if game_window.kind == CLOUD_WINDOW_KIND:
            self.x1 = self.x0 + BASE_WIDTH
            self.y1 = self.y0 + BASE_HEIGHT
            self.xx, self.yy = BASE_WIDTH, BASE_HEIGHT
        self.scx = self.xx / self.bx
        self.scy = self.yy / self.by
        dc = win32gui.GetWindowDC(hwnd)
        dpi_x = win32print.GetDeviceCaps(dc, win32con.LOGPIXELSX)
        win32gui.ReleaseDC(hwnd, dc)
        scale_x = dpi_x / 96
        try:
            self.scale = ctypes.windll.user32.GetDpiForWindow(hwnd) / 96.0
        except Exception:
            CUS_LOGGER.warning('DPI获取失败')
            self.scale = 1.0
        CUS_LOGGER.debug(
            "DPI: " + str(self.scale) + " A:" + str(int(self.multi * 100) / 100)
        )
        CUS_LOGGER.info("当前演算世界: " + str(Text))
        # 计算出真实分辨率
        self.real_width = int(self.xx * scale_x)
        # x01y01:窗口左上右下坐标
        # xx yy:窗口大小
        # scx scy:当前窗口和基准窗口（1920*1080）缩放大小比例
        time.sleep(1)
        return 1
    def gen_hotkey_img(self,hotkey="e",bg=PATHS["image"]+"/f_bg.jpg"):
        img=find_image_in_folder('key/', hotkey)
        if img is None:
            hotkey = hotkey.upper()
            img = Image.open(bg)
            font = ImageFont.truetype(PATHS["font"]+"/base.ttf", 24)
            d = ImageDraw.Draw(img)
            position = (2,-3)
            color = (152, 214, 241)
            d.text(position, hotkey, font=font, fill=color)
            img = np.array(img)
            cv.imwrite(PATHS["image"]+"/key/"+hotkey.lower()+".jpg", img)
        return img


    # example: self.wait_fig(lambda:self.check("strange", 0.9417, 0.9481), 1.4)
    def wait_flag(self, f, timeout=3.0):
        tm=time.time()
        while time.time()-tm<timeout:
            if not f():
                return 1
            time.sleep(0.05)
            self.get_screen()
        return 0
    @timer
    def fresh_state(self):
        self.get_screen()
        return self.run_static()[1]
    def use_it(self, x, y):
        if x != 1 or y != 1:
            key_mouse_manager.click(0.903 - 0.06 * (x - 1), 0.827 - 0.14 * (y - 1))
        # 点击使用
        key_mouse_manager.click(0.154,0.088)
        self.wait_flag(lambda:not self.click_text(text="确认",box=[1126, 1252, 716, 812],click=False,ocr_line=False,warning=False), 1.2)
        # 点击确认
        key_mouse_manager.click(0.386,0.294)
        r = self.wait_flag(lambda:not self.click_text(text="替换同类",box=[816, 1006, 284, 380],click=False,warning=False), 0.8)
        if r:
            # 覆盖效果
            key_mouse_manager.click(0.386,0.294)

    def calc_point(self, point, offset):
        return point[0] - offset[0] / self.xx, point[1] - offset[1] / self.yy

    def click_text(self, text,delay=0,box=None,after_delay=0,click=True,find_all=False,warning=True,ocr_line=True,need_fresh=True,allow_fail=False):
        if delay:
            time.sleep(delay)
        if not ocr_line:
            ocr_text = self.ts.find_with_box(box=box,forward=need_fresh)
            if len(ocr_text) and text in merge_text(ocr_text):
                CUS_LOGGER.debug(f"找到{text}当前返回结果{ocr_text}")
                return True
            else:
                if warning:
                    CUS_LOGGER.warning(f"{text}文本未找到(非单行)当前返回结果{ocr_text}")
        if need_fresh:
            img = self.get_screen()
        else:
            img = self.screen
        if box:
            match=self.ts.ocr_one_row(img,box)
            CUS_LOGGER.info(f"{factor}请求：{text}响应：{match}")
            # 检查匹配结果是否包含目标文本
            if len(match) and text in match:
                if click:
                    key_mouse_manager.click(
                        (box[0]+box[1])//2,
                        (box[2]+box[3])//2
                    )
                if after_delay:
                    time.sleep(after_delay)
                return True
            elif allow_fail:
                return False
        pt = self.ts.find_text(img, text,find_all)
        if pt is not None:
            if click:
                key_mouse_manager.click(
                        1 - (pt[0][0] + pt[1][0]) / 2 / self.xx,
                        1 - (pt[0][1] + pt[2][1]) / 2 / self.yy
                )
            if after_delay:
                time.sleep(after_delay)
            return True
        if warning:
            CUS_LOGGER.warning(f"{text}文本未找到")
        return False

    # 由click_target调用，返回图片匹配结果
    def scan_screenshot(self, prepared):
        screenshot = self.get_screen()
        result = cv.matchTemplate(screenshot, prepared, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        return {
            "screenshot": screenshot,
            "min_val": min_val,
            "max_val": max_val,
            "min_loc": min_loc,
            "max_loc": max_loc,
        }

    # 计算匹配中心点坐标
    def calculated(self, result, shape):
        mat_top, mat_left = result["max_loc"]
        prepared_height, prepared_width, prepared_channels = shape
        x = int((mat_top + mat_top + prepared_width) / 2)
        y = int((mat_left + mat_left + prepared_height) / 2)
        return x, y





    # 点击与模板匹配的点，flag=True表示必须匹配，不匹配就会一直寻找直到出现匹配
    def click_target(self, target_path, threshold, flag=True, sub=True, click=False):
        target = target_path
        while not self._stop:
            result = self.scan_screenshot(target)
            if result["max_val"] > threshold:
                CUS_LOGGER.debug(f"全局图像匹配度{result['max_val']}")
                points = self.calculated(result, target.shape)
                if click:
                    key_mouse_manager.click(*points)
                return True
            if not flag:
                return False
            elif sub:  # 降低阈值直到匹配到为止
                threshold -= 0.01

    # 在截图中裁剪需要匹配的部分
    def get_local(self, x, y, size, large=True):
        sx, sy = size[0] + 60 * large, size[1] + 60 * large
        bx, by = self.xx - int(x * self.xx), self.yy - int(y * self.yy)
        return self.screen[
            max(0, by - sx // 2) : min(self.yy, by + sx // 2),
            max(0, bx - sy // 2) : min(self.xx, bx + sy // 2),
            :,
        ]


    def get_small_interaction_img(self,x, y, mask=None,fresh=False):
        """
        截取指定点位特定模板大小的图片
        x,y：匹配中心点，
        mask：以mask大小为基准裁剪截图
        """
        if fresh:
            self.get_screen()
        # CUS_LOGGER.debug(f"正在获取小交互图片{x},{y}遮罩{mask}")

        if mask is None:
            target = find_image_by_name("z")
            target = cv.resize(
                target,
                dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
            )
            shape = target.shape
        else:
            mask_img = find_image_by_name(mask)
            shape = (
                int(self.scx * mask_img.shape[0]),
                int(self.scx * mask_img.shape[1]),
            )
        local_screen = self.get_local(x, y, shape, False)
        return local_screen
    def check(self, path, x, y, mask=None, threshold=None, use_binary=False,fresh=False):
        """
        判断截图中匹配中心点附近是否存在匹配模板
        path：匹配模板的路径，
        x,y：匹配中心点，
        mask：如果存在，则以mask大小为基准裁剪截图，
        threshold：匹配阈值
        """
        if fresh:
            self.get_screen()
        if threshold is None:
            threshold = self.threshold
        if "/" in path:
            path = path.split("/")
            target = find_image_in_folder(path[0], path[1])
        else:
            target = find_image_by_name(path)
        if path == "f" and config.mapping[0]!='f':
            target = self.gen_hotkey_img(config.mapping[0])
            threshold -= 0.01
        target = cv.resize(
            target,
            dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
        )
        if mask is None:
            shape = target.shape
        else:
            mask_img = find_image_by_name(mask)
            shape = (
                int(self.scx * mask_img.shape[0]),
                int(self.scx * mask_img.shape[1]),
            )
        local_screen = self.get_local(x, y, shape)
        if use_binary:
            # 将截图和模板图像转换为灰度图
            if len(local_screen.shape) == 3:
                gray_screen = cv.cvtColor(local_screen, cv.COLOR_BGR2GRAY)
            else:
                gray_screen = local_screen

            if len(target.shape) == 3:
                gray_target = cv.cvtColor(target, cv.COLOR_BGR2GRAY)
            else:
                gray_target = target

            # 对截图和模板进行二值化处理
            _, binary_screen = cv.threshold(gray_screen, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            _, binary_target = cv.threshold(gray_target, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)

            # 使用二值化图像进行匹配
            result = cv.matchTemplate(binary_screen, binary_target, cv.TM_CCORR_NORMED)
        else:
            try:
                result = cv.matchTemplate(local_screen, target, cv.TM_CCORR_NORMED)
            except Exception:
                CUS_LOGGER.error(f"{path}匹配失败，源图像{local_screen.shape}，目标图像{target.shape}")
                raise
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        self.tx = x - (max_loc[0] - 0.5 * local_screen.shape[1] + 0.5 * target.shape[1]) / self.xx
        self.ty = y - (max_loc[1] - 0.5 * local_screen.shape[0] + 0.5 * target.shape[0]) / self.yy
        self.tm = max_val
        if max_val > threshold:
            if self.last_info != path:
                CUS_LOGGER.debug(f"匹配到图片记忆切片 {path} 相似度 {max_val} 阈值 {threshold}")
            self.last_info = path
        return max_val > threshold




    # 从全屏截屏中裁剪得到游戏窗口截屏
    def get_screen(self):
        current_time = time.time()
        if hasattr(self, 'last_get_screen_time') and self.last_get_screen_time is not None:
            interval = current_time - self.last_get_screen_time
            self.fps_list.append(interval)
            if len(self.fps_list) > 30:
                self.fps_list.pop(0)
            avg_interval = sum(self.fps_list) / len(self.fps_list)
            # 使用信号发射方式更新FPS，避免多线程直接操作GUI
            log_emitter.fps_update_signal.emit(avg_interval)
            # log.info(f"平均FPS: {1 / avg_interval:.2f}")
        self.last_get_screen_time = current_time
        self.screen = self.sct.grab(self.x0, self.y0)
        return self.screen

    def set_path_state(self, text):
        current_time = time.time()
        if self.last_path_state_time is not None:
            elapsed_time = current_time - self.last_path_state_time
            CUS_LOGGER.debug(f"{text} (距离上次日志: {elapsed_time:.2f}秒)")
        else:
            CUS_LOGGER.debug(text)
        self.last_path_state_time = current_time
        log_emitter.find_path_state_signal.emit(text)

    def get_blank_state(self):
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True, center_radius=90)
        #作用是筛选掉蓝色，但会意外筛去一些颜色
        # local_screen = local_screen - cv.bitwise_and(local_screen, local_screen,mask=cv.inRange(cv.cvtColor(local_screen, cv.COLOR_BGR2HSV),np.array([80, 0, 0]), np.array([110, 255, 255])))
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        grey_map = deepcopy(bw_map)
        grey_map[np.sum((local_screen - np.array([55, 55, 55])) ** 2, axis=-1) <= 4800] = 255
        grey_map = cv.dilate(grey_map, np.ones((5, 5), np.uint8), iterations=1)
        bw_map[(np.sum((local_screen - np.array([210, 210, 210])) ** 2, axis=-1) <= 9000) & (grey_map > 200)] = 255
        non_black_pixels = np.count_nonzero(bw_map)
        CUS_LOGGER.debug(f"非黑像素点数量：{non_black_pixels}")
        return non_black_pixels

    def get_now_direct(self, loc_scr):
        """
            计算小地图中蓝色箭头的角度，以正上为0度，逆时针增加
        """
        hsv = cv.cvtColor(loc_scr, cv.COLOR_BGR2HSV)  # 转HSV
        lower = np.array([93, 120, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        upper = np.array([97, 255, 255])
        mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        loc_tp = cv.bitwise_and(loc_scr, loc_scr, mask=mask)
        # loc_tp[np.sum(np.abs(loc_tp - blue), axis=-1) > 0] = [0, 0, 0]
        # 裁剪loc_tp至中心24x24区域
        h, w = loc_tp.shape[:2]
        center_h, center_w = h // 2, w // 2
        crop_size = 12  # 24x24区域的一半是12
        loc_tp = loc_tp[center_h - crop_size-5:center_h + crop_size-5,
                        center_w - crop_size:center_w + crop_size]
        arrows_img = find_image_by_name("combined_arrows")
        # 在拼接的大图上进行一次匹配
        result = cv.matchTemplate(arrows_img, loc_tp, cv.TM_SQDIFF)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        # 根据匹配位置计算对应的角度
        best_row = (min_loc[1]+12) // 26  # 行号
        best_col = (min_loc[0]+12) // 26  # 列号
        ang = best_row * 12 + best_col  # 对应的角度
        # 在combined_img上框出匹配到的结果
        # combined_img_with_rect = arrows_img.copy()
        # log.info(f"角度：{ang}行：{best_row}列：{best_col}")
        # cv.rectangle(combined_img_with_rect, min_loc,
        #             (min_loc[0] + loc_tp.shape[1], min_loc[1] + loc_tp.shape[0]),
        #             (0, 0, 255), 1)
        # cv.imshow("匹配结果", loc_tp)
        # cv.imshow("匹配目标", combined_img_with_rect)
        # cv.waitKey(0)

        return ang

    def nof(self,must_be=None):
        """
        检查当前没有f交互
        """

        tm = time.time()
        self.update_state("inf")
        ava = False
        if must_be is None and (self.ts.similar("区域") or self.ts.similar("觐见")):
            must_be='tp'
        while not ava and time.time()-tm<1.8:
            if not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                if not self.is_run():
                    CUS_LOGGER.info("仿佛连深不见底的最初混沌，也能够烧却。")
                    ava = True
        if self.state=="run":
            if must_be!='challenge':
                key_mouse_manager.press("s")
                key_mouse_manager.wait()
                if not self.is_run():
                    CUS_LOGGER.info("…我以为，那就是世间最极致的力量，再无其他。")
                    ava=True
                elif (not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True)) and must_be == 'tp':
                    CUS_LOGGER.info("或许只要短短万年的时光——它便会被烧成哀毁骨立的焦炭盗火行者了吧。")
                    ava=True
            else:
                if not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96, fresh=True):
                    ava=True

        if ava:
            CUS_LOGGER.info('这一次，逐火的终点………也并无不同。')
            if must_be == 'event':
                self.mini_state += 2
            elif must_be== 'tp':
                if hasattr(self, 'plane_floor'):
                    pass
                else:
                    self.init_map()
                    self.mini_state = 1
                    self.add_floor()
                    if self.floor in [1, 6]:
                        self.floor_init=0
                    self.f_time = time.time()
                    self.last_interact_time = time.time()
                    CUS_LOGGER.debug(f"地图{self.now_map}已完成,相似度{self.now_map_sim},进入{self.floor}层")
            else:
                if self.ts.similar("黑塔"):
                    self.quit = time.time()
                self.mini_state += 2
        else:
            CUS_LOGGER.warning('……那我偏偏，绝不顺从……')
        return ava
    def save_screen(self, save_path=r"./temp",force=False,not_now=False):
        """
        获取截图并保存到指定路径
        :param save_path: 保存截图的路径
        :param force: 是否展示
        """
        if not_now:
            sc=self.screen
        else:
            sc = self.get_screen()
        save_path = PATHS["root"]+"/temp/"
        try:
            os.mkdir(save_path)
        except Exception:
            pass
        filename = save_path+datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
        cv.imwrite(filename,sc)
        if force:
            cv.imshow("save",sc)
            cv.waitKey(0)
        return sc
    def update_direction_data(self,mode=None,target=None):
        self.rotation, d = self.pos_predictor.update_minimap_data(self.screen)
        if d is None:
            return False
        CUS_LOGGER.debug(f"视角{self.rotation}朝向{d}模式{mode}小地图目标{target}")
        CUS_LOGGER.debug(f"当前点位{self.now_loc}大地图目标点位{self.target_loc}")
        if 20<abs(self.rotation-d)<340:
            key_mouse_manager.wait()
            self.rotation, d = self.pos_predictor.update_minimap_data(self.get_screen())
            if d is None:
                return False
            if 20<abs(self.rotation-d)<340 and mode !=1:
                # cv.imshow("now", self.screen)
                if self.debug:
                    self.save_screen(not_now=True)
                CUS_LOGGER.error(f"角度误差过大视角{self.rotation}朝向{d}模式{mode}")
                # raise BigAngError(f"角度误差过大视角{self.rotation}朝向{d}")
                d = self.rotation
            elif 20<abs(self.rotation-d)<340:
                CUS_LOGGER.debug(f"角度误差过大视角{self.rotation}朝向{d}模式1")
                d=self.rotation
        # 纠正为标准坐标系然后上下反转的坐标系角度（取反估计是为了便于底层操作向左为负，向右为正）
        self.ang = 270 + d
        self.ang%=360
        if mode==2:#小地图寻敌
            rel_loc=(93,93)
            target_loc= target[0]
        else:
            rel_loc=self.now_loc
            target_loc= self.target_loc
        # 当前坐标与目标点连成的直线的斜率
        ang = (
                math.atan2(target_loc[0] - rel_loc[0], target_loc[1] - rel_loc[1])
                / math.pi
                * 180
        )
        ang = 90 - ang
        ang%=360
        # 视角需要旋转的角度，规范到[-180,180]
        sub = ang - self.ang
        sub = (sub + 180) % 360 - 180
        if  mode==2 and sub==0:
            sub=1e-9
        key_mouse_manager.mouse_move(sub)
        CUS_LOGGER.debug(f"当前人物角度为：{str(self.ang)}变换后角度{ang},视角移动{sub}")
        # 此处变换为了目标角度
        self.ang = ang
        ds=get_dis(rel_loc, target_loc)
        return ds



    def cut_map(self, pos, map):
        """
        [左上x,右下x,左上y,右下y]
        """
        radius=93
        x,y=map.shape[1],map.shape[0]
        if self.cut_pos is None:
            self.cut_pos=[max(0,pos[0]-radius * POSITION_SEARCH_SCALE), min(x,pos[0]+radius * POSITION_SEARCH_SCALE),max(0,pos[1]-radius * POSITION_SEARCH_SCALE), min(y,pos[1]+radius * POSITION_SEARCH_SCALE)]
        else:
            old_pos=self.cut_pos.copy()
            self.cut_pos=[max(0,min(old_pos[0],pos[0]-radius * POSITION_SEARCH_SCALE)), min(x,max(old_pos[1],pos[0]+radius * POSITION_SEARCH_SCALE)),max(0,min(old_pos[2],pos[1]-radius * POSITION_SEARCH_SCALE)), min(y,max(old_pos[3],pos[1]+radius * POSITION_SEARCH_SCALE))]
        self.cut_pos=np.array(self.cut_pos, dtype=np.float64)
        self.cut_pos= np.round(self.cut_pos).astype(int)
        CUS_LOGGER.debug(f"裁剪地图范围{self.cut_pos}")


    def get_loc(self, fresh=True):
        """
        精确匹配获得精确坐标，该坐标并非代表点位在大地图上的像素坐标，而是经过变换缩放而获得的
        """

        CUS_LOGGER.debug(f"获取新坐标,当前坐标{self.now_loc}是否刷新{fresh}")
        if fresh:
            self.get_screen()
            if not self.is_run():
                return False
        pos,sim=self.pos_predictor.update_position(self.screen)
        self.now_loc= pos
        CUS_LOGGER.debug(f"获取到新坐标{self.now_loc}")
        return True
    def get_offset(self,delta=1):
        if self.slow:
            delta /= 2
        pi = 3.141592653589
        CUS_LOGGER.debug(f"当前使用偏移角度{self.ang}倍率{delta}")
        dx, dy = sin(self.ang/180*pi), cos(self.ang/180*pi)
        return delta * dx * 3, delta * dy * 3

    def update_state(self,state):
        log_emitter.find_path_state_signal.emit(state)
        if self.state is not None and self.state!=state:
            self.last_state=self.state
            self.state = state
            self.last_update_time=time.time()
            CUS_LOGGER.debug(f"当前状态{state}更新时间{self.last_update_time}")
        elif self.state is None:
            self.last_state = self.state
            self.state = state
            self.last_update_time=time.time()
            CUS_LOGGER.debug(f"当前状态{state}更新时间{self.last_update_time}")
    # @timer
    #0.2~0.25s
    def is_run(self,check=True):
        if check:
            if not self.check("big_world", 0.0245, 0.5185, threshold=0.98, fresh=True):
                self.update_state("no_run")
                return False
        # loc_scr = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True)
        # hsv = cv.cvtColor(loc_scr, cv.COLOR_BGR2HSV)  # 转HSV
        # lower = np.array([93, 120, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        # upper = np.array([97, 255, 255])
        # mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        # sum_blue = np.sum(mask)
        # scr_bak = deepcopy(scr)
        # scr[np.min(scr,axis=-1)<=220]=[0,0,0]
        # scr[np.min(scr,axis=-1)>220]=[255,255,255]
        # res = 40000 < sum_blue < 65000
        # if self.tm>0.96:
        #     res = True
        # self.screen = deepcopy(scr_bak)
        # if res:
        #     self.f_time = 0
        self.update_state("run")
        return True

    def click_box(self, box):
        """
        点击给定坐标框的中心位置

        Args:
            box: 坐标框，格式为[x1, x2, y1, y2]，其中x1,x2为横向坐标，y1,y2为纵向坐标
        """
        x = (box[0] + box[1]) / 2
        y = (box[2] + box[3]) / 2
        key_mouse_manager.click(1 - x / self.xx, 1 - y / self.yy)

    def click_position(self, position):
        """
        点击给定位置坐标

        Args:
            position: 位置坐标，格式为[x, y]，其中x为横向坐标，y为纵向坐标
        """
        self.click_box([position[0], position[0], position[1], position[1]])
