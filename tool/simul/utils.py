import ctypes
import json
import math
import os
import random
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime
from math import cos, sin

import cv2
import cv2 as cv
import numpy as np
import pythoncom
import win32api
import win32com.client
import win32con
import win32gui
import win32print
from PIL import Image, ImageDraw, ImageFont

from diver import merge_text
from route import PATHS
from tool.GLOBAL import (
    factor,
    get_global_stop_flag,
    key_mouse_manager,
    set_global_stop_flag,
)
from tool.log import CUS_LOGGER, log_emitter
from tool.screenshot import Screen
from tool.simul.config import config
from tool.simul.ocr import get_global_my_ts
from tool.simul.text_key import text_keys
from tool.thread import ThreadWithException
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
from tool.utils.minimap_util import (
    MINIMAP_RADIUS,
    POSITION_MINIMAP_SCALE,
    POSITION_SEARCH_SCALE,
    crop,
    deal_minimap,
    get_minimap,
    mask_minimap_outside,
    re_get_position,
)
from tool.utils.mminimap import PositionPredict
from tool.utils.ocr_num import match_skill_numbers_in_region
from tool.utils.predict import get_text_position, predict


def set_forground():
    config.read()
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





class UniverseUtils:
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
        # 用户选择的命途
        for i in range(len(config.fates)):
            if config.fates[i] == self.fate:
                self.my_fate = i
        if self.my_fate == -1:
            CUS_LOGGER.warning("info有误，自动选择巡猎命途    错误：" + self.fate)
            self.my_fate = 4
        self.tk = text_keys(self.my_fate)
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
            # 本地客户端保留原有的 DWM 边框和超宽屏裁剪逻辑。
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
            # 算法坐标系固定为 1920x1080；云浏览器少量边框差异在这里归一化。
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

    def use_consumable(self, x=1, y=1):
        """
        使用x排，y列的消耗品
        """
        key_mouse_manager.press("b")
        if self.wait_flag(lambda:not self.check("use_package", 0.5182, 0.9407), 3):
            key_mouse_manager.click(0.3677,0.0861)
            self.get_screen()
            if self.wait_flag(lambda:not self.check("use_star", 0.8828, 0.8648, threshold=0.9), 0.8):
                self.use_it(x, y)
                if self.wait_flag(lambda:not self.check("use_def", 0.3198, 0.0880), 2.2):
                    key_mouse_manager.click(0.3198,0.0880)
                    self.get_screen()
                    if self.wait_flag(lambda:not self.check("use_star", 0.8828, 0.8648, threshold=0.9), 0.6):
                        self.use_it(x, y)
                        self.wait_flag(lambda:not self.check("use_package", 0.5182, 0.9407), 2)
                    key_mouse_manager.press("esc")
            else:
                key_mouse_manager.press("esc")
        self.fresh_state()
        if not self.state=="run":
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()


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

    def get_end_point(self, mask=0,device=0):
        self.get_screen()
        local_screen = self.get_local(0.4979, 0.6296, (715, 1399))
        white = np.array([255, 255, 255])
        black = np.array([0, 0, 0])
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        b_map = deepcopy(bw_map)
        b_map[np.sum((local_screen - black) ** 2, axis=-1) <= 1600] = 255
        w_map = deepcopy(bw_map)
        w_map[np.sum((local_screen - white) ** 2, axis=-1) <= 1600] = 255
        kernel = np.zeros((7, 7), np.uint8)  # 设置kenenel大小
        kernel += 1
        b_map = cv.dilate(b_map, kernel, iterations=1)  # 膨胀还原图形
        bw_map[(b_map > 200) & (w_map > 200)] = 255
        cen = 660
        if mask:
            try:
                #仅保留图像x轴310~910区域
                bw_map[:, : cen - 350 // mask] = 0
                bw_map[:, cen + 350 // mask :] = 0
            except Exception:
                pass
        # region = cv.imread("resource/imgs/region.jpg", cv.IMREAD_GRAYSCALE)
        if device:
            region = find_image_in_folder('gray_image/', 'device.png')
        else:
            region=find_image_in_folder('gray_image/', 'region.jpg')
        result = cv.matchTemplate(bw_map, region, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        if max_val < 0.6:
            return None
        else:
            #正数位于中心点660右侧，负数位于中心点660左侧
            dx = max_loc[0] - cen
            if dx > 0:
                return dx**0.7
            else:
                return -((-dx) ** 0.7)

    def move_to_end(self, i=0,mode=0,device=0):
        CUS_LOGGER.debug(f"一人前往未来……一人留在过去。(类型{mode})")
        dx = self.get_end_point(i,device)
        if dx is None:
            if i:
                CUS_LOGGER.warning("而我将行尽未竟的道路…一如过去无数个我，一如既往。")
                return 0
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 0, -200)
            dx = self.get_end_point(device=device)
            off = 0
            if dx is None:
                CUS_LOGGER.debug('…找到那个新生的「我」…让他延续三千万世的徒劳。')
                for k in [60,120,60,60,30,30,-60,-60,-60,-60,-60,-60]:
                    key_mouse_manager.mouse_move(-k)
                    key_mouse_manager.wait()
                    off += k
                    dx = self.get_end_point(device=device)
                    if dx is not None:
                        break
                if dx is None:
                    key_mouse_manager.mouse_move(off*1.03)
                    key_mouse_manager.wait()
                    CUS_LOGGER.warning(f"即便理智随身形一起化作焦炭，{factor}也会记得自己的使命……(旋转未找到终点)")
                    return 0
        CUS_LOGGER.debug(f"移动面向终点 参数{i}移动距离{dx}")
        if i == 0:
            key_mouse_manager.mouse_move(dx / 3)
            key_mouse_manager.wait()
        else:
            key_mouse_manager.mouse_move(dx / 5)
            key_mouse_manager.wait()
        if i == 0 and abs(dx / 3) > 30:
            dx = self.get_end_point(1,device=device)
            if dx is not None:
                key_mouse_manager.mouse_move(dx / 4)
                key_mouse_manager.wait()
        return 1





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

    def get_blank_state(self, save_debug_dir=None):
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

        # 保存调试图像，用于判断阈值是否合适
        if save_debug_dir and non_black_pixels < 250:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            tag = f"blank_{non_black_pixels}_{timestamp}"
            save_debug_dir=os.path.join(save_debug_dir, f"{tag}")
            os.makedirs(save_debug_dir, exist_ok=True)
            cv.imwrite(os.path.join(save_debug_dir, "minimap.png"), local_screen)
            cv.imwrite(os.path.join(save_debug_dir, "bwmap.png"), bw_map)
            cv.imwrite(os.path.join(save_debug_dir, "greymap.png"), grey_map)
            with open(os.path.join(save_debug_dir, "params.txt"), "w", encoding="utf-8") as fp:
                fp.write(f"non_black_pixels = {non_black_pixels}\n")
                fp.write("threshold = 250\n")
                fp.write("verdict = reference_lines_too_few (参考线太少，进入无地图寻路)\n")
                fp.write("grey_threshold = np.array([55, 55, 55]), dist <= 4800\n")
                fp.write("white_threshold = np.array([210, 210, 210]), dist <= 9000\n")
                fp.write("dilate_kernel = 5x5, iterations=1\n")

        return non_black_pixels
    @timer
    def get_bw_map(self, local_screen=None,re_screen=1):
        """
            进一步得到小地图的黑白格式
            re_screen：是否重新截图
            大小是186*186
        """
        if re_screen and self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False) or self.state!="run":
            CUS_LOGGER.warning("未找到大地图，可能在其它游戏界面")
        white = np.array([210, 210, 210])
        gray = np.array([55, 55, 55])
        # local_screen=screen[46:222,43:219]#[43,46,219,222]源范围  正确范围#[45,56,231,242]
        # local_screen=screen[56:242,45:231]#[43,46,219,222]源范围  正确范围#[45,56,231,242] 偏移[2,10,12,20]
        if local_screen is None:
            local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True,center_radius=93)

        # local_screen[np.sum(np.abs(local_screen - blue), axis=-1) <= 50] = 0
        hsv = cv.cvtColor(local_screen, cv.COLOR_BGR2HSV)  # 转HSV
        lower = np.array([80, 60, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        upper = np.array([110, 255, 255])

        mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        loc_tp = cv.bitwise_and(local_screen, local_screen, mask=mask)
        local_screen = local_screen - loc_tp
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        # 灰块、白线：小地图中的可移动区域、可移动区域的边缘
        # b_map：当前像素点是否是灰块。只允许灰块附近（2像素）的像素被识别为白线
        grey_map = deepcopy(bw_map)
        grey_map[
            np.sum((local_screen - gray) ** 2, axis=-1) <= 4800
            ] = 255
        kernel = np.zeros((5, 5), np.uint8)  # 设置kenenel大小
        kernel += 1
        grey_map = cv.dilate(grey_map, kernel, iterations=1)
        bw_map[
            (np.sum((local_screen - white) ** 2, axis=-1) <= 9000)
            & (grey_map > 200)
            ] = 255
        # 排除半径90以外的像素点
        for i in range(bw_map.shape[0]):
            for j in range(bw_map.shape[1]):
                if ((i - 93) ** 2 + (j - 93) ** 2) > 90 ** 2:
                    bw_map[i, j] = 0
        return bw_map

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

    def get_level(self):
        if not self.floor_init:
            key_mouse_manager.press("m", 0.3)
            self.update_state("map")
        return 1
    def get_floor(self):
        CUS_LOGGER.info(f"开始更新层数旧层数：{self.floor}")
        old_floor= self.floor
        self.get_screen()
        for i in range(13, 0, -1):
            if self.check("floor/ff" + str(i), 0.0589, 0.8796):
                self.update_floor(i)
                CUS_LOGGER.info(f"当前层数：{i}")
                self.floor_init = 1
                break
        if self.floor!=old_floor and old_floor!=0:
            CUS_LOGGER.warning(f"层数已更新为：{self.floor}")
            self.floor_change=True
        key_mouse_manager.press("m", 0.2)
        return 1

    def good_f(self,run=True):
        """
        不是"沉浸", "紧锁", "复活", "下载"的交互
        """
        CUS_LOGGER.info("请求：「开启再创世，去迎接翁法罗斯崭新的黎明。」")
        t_start=time.time()
        img = self.get_small_interaction_img(x=0.3344,y=0.4241,mask="mask_f")
        text = self.ts.similar_list(self.tk.interacts, img)
        if text is None:
            # 使用新坐标重新尝试
            img = self.get_small_interaction_img(x=0.3181,y=0.4324,mask="mask_f")
            text = self.ts.similar_list(self.tk.interacts, img)
        is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
        if text is not None:
            CUS_LOGGER.info(f'响应：「一▇▇▇▇徒劳的▇▇▇{text}▇▇▇。」')
        CUS_LOGGER.debug(f"交互最佳结果判断{text is not None and not is_killed}")
        if not (text is not None and not is_killed) and run:
            key_mouse_manager.keyDown("w")
            key_mouse_manager.wait()
        t_end=time.time()
        return text is not None and not is_killed, t_end-t_start

    def get_recent_target(self):
        """
        寻找最近的目标点位与类型
        """
        mn_dis = 100000
        recent_loc = 0
        recent_type = -1
        # log.info(f"当前状态{self.target}")
        for target_loc, target_type in self.target:
            # log.info(f"遍历当前状态{self.target}")
            dis=get_dis(target_loc, self.now_loc)
            if dis < mn_dis:
                mn_dis = dis
                recent_loc = target_loc
                recent_type = target_type
        # 如果找不到，将最后一个完成的目标点作为目标点
        if recent_loc == 0:
            recent_loc = self.last
            recent_type = 3
        if recent_type==1 and mn_dis<40:
            red = [47, 47, 232]
            # self.save_screen(not_now=True)
            rd = np.where(np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True) - red) ** 2, axis=-1) <= self.red_threshold)
            if rd[0].shape[0] > 0:
                self.target.remove((recent_loc, 1))
                new_loc = re_get_position(self.now_loc)
                CUS_LOGGER.debug(f"移除目标{recent_loc},当前状态{self.target},距离{mn_dis},图片全局坐标{new_loc}")
                # 创建所有检测到的敌人坐标的列表
                enemy_coords = []
                for i in range(len(rd[0])):
                    enemy_x, enemy_y = rd[1][i], rd[0][i]
                    world_x = new_loc[0] + (enemy_x - 93)*POSITION_MINIMAP_SCALE
                    world_y = new_loc[1] + (enemy_y - 93)*POSITION_MINIMAP_SCALE
                    new_loc = re_get_position((world_x, world_y), re=True)
                    enemy_coords.append((new_loc, (enemy_x, enemy_y)))

                # 按距离self.real_loc排序，最近的在前面
                enemy_coords.sort(key=lambda coord: get_dis(coord[0], self.now_loc))
                # 选择最近的敌人作为目标
                nearest_world_coord, nearest_local_coord = enemy_coords[0]
                recent_loc = tuple(nearest_world_coord)
                self.target.add((recent_loc, 1))
                CUS_LOGGER.debug(f"找到新的敌对目标点：{recent_loc}，本地图像坐标{nearest_local_coord }共检测到{len(enemy_coords)}个敌人，按距离排序,最近距离(浮点）{get_dis(recent_loc, self.now_loc)}")
            else:
                self.target.remove((recent_loc, 1))
                self.target.add((recent_loc, 0))
                CUS_LOGGER.info(f"……怒火……在溢出……（使用当前目标作为路径点位：{recent_loc}）")
                recent_type=0
        return recent_loc, recent_type

    def move_to_red_point(self):
        self.get_screen()
        if not self.is_run():
            return False
        CUS_LOGGER.info("终于，还是……看来，避免刀剑交锋，果真是天方夜谭。")
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True,center_radius=90)
        # 找红色点位（敌人）
        rd = np.where(np.sum((local_screen - [47, 47, 232]) ** 2, axis=-1) <= 5000)
        CUS_LOGGER.debug(f"敌人检测结果{rd[0].shape[0]}")
        if rd[0].shape[0] > 0:
            # 仅检测存在性，不需要排序，使用第一个检测到的点
            target = ((rd[1][0], rd[0][0]), 3)
            CUS_LOGGER.debug(f"交互点类型{target[1]}，位置{target[0][0]},{target[0][1]}")
            self.target_type = target[1]
            self.has_target = True
            self.update_direction_data(mode=2, target=target)
            return True
        else:
            return False
    def move_to_event(self,threshold = 0.85,rest=False):
        self.get_screen()
        if not self.is_run():
            return False
        CUS_LOGGER.info(f"{factor}总是会如此下定决心。")
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True,center_radius=90)
        if not rest:
            icon = find_image_by_name("mini_event")
        else:
            icon =find_image_by_name("mini_rest")
        best_val=-1
        best_scale=-1
        for scale in [1.00, 1.05, 1.10, 1.15, 1.20, 1.25]:
            mini_icon=cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            sp = mini_icon.shape
            #小地图查找交互点并获取其位置
            result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
            if max_val>best_val:
                best_val=max_val
                nearest = (max_loc[0] + sp[1] // 2, max_loc[1] + sp[0] // 2)
                target = (nearest, 1)
                best_scale =scale
        if best_val > threshold:
            CUS_LOGGER.debug(f"交互点最佳相似度{best_val}，位置{nearest},比例{best_scale}")
            self.target_type = 1 if not rest else 2
            self.has_target=True
            self.update_direction_data(mode=2,target=target)
            return True
        else:
            return False
    def move_to_shop(self,threshold = 0.925):
        self.get_screen()
        if not self.is_run():
            return False
        CUS_LOGGER.info(f"暴烈的火焰随时都能将{factor}的身躯崩裂，吞噬这个世界，这座可悲的囚笼…")
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True,center_radius=90)
        icon =find_image_by_name("mini_shop")
        best_val=-1
        best_scale=-1
        best_points = []
        for scale in [1.00, 1.05, 1.10, 1.15, 1.20, 1.25]:
            mini_icon=cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            sp = [14*scale,14*scale]
            #小地图查找交互点并获取其位置
            result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
            # 如果当前缩放的最佳值优于之前记录的最佳值，更新最佳缩放并重新收集点位
            if max_val > best_val:
                best_val = max_val
                best_scale = scale
                if max_val > threshold:
                    loc = np.where(result > threshold)
                    all_points = []
                    for pt in zip(*loc[::-1]):
                        point = (pt[0] + sp[1], pt[1] + sp[0])
                        all_points.append(point)
                    best_points = all_points

        # 从最佳点位中选择最左边的一个（x 坐标最小）
        if best_val > threshold and len(best_points) > 0:
            best_points.sort(key=lambda p: p[0])
            nearest = best_points[0]
            target = (nearest, 1)
            CUS_LOGGER.debug(f"交互点最佳相似度{best_val}，位置{nearest},比例{best_scale},候选点位{len(best_points)}")
            self.target_type = 2
            self.has_target=True
            self.update_direction_data(mode=2,target=target)
            return True
        else:
            return False

    def move_to_interact(self, ii=0):
        self.get_screen()
        if not self.is_run():
            return False
        CUS_LOGGER.info("正在寻找交互点")
        threshold = 0.88
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
        target = ((-1, -1), 0)
        mini_icon = find_image_by_name("mini" + str(ii + 1))
        sp = mini_icon.shape
        # 小地图查找交互点并获取其位置
        result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        if max_val > threshold:
            nearest = (max_loc[0] + sp[1] // 2, max_loc[1] + sp[0] // 2)
            target = (nearest, 1)
            CUS_LOGGER.debug(f"交互点相似度{max_val}，位置{max_loc[0]},{max_loc[1]},图像序号{ii}")

            if self.floor >= 13:
                self.update_floor(12)
        else:  # 226 64 66
            # 再试试另外一张图，即黑塔图
            mini_icon = find_image_by_name("mini" + str(ii + 2))
            sp = mini_icon.shape
            result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
            if max_val > threshold:  # -0.035*(self.floor in [5,9,12]):
                nearest = (max_loc[0] + sp[1] // 2, max_loc[1] + sp[0] // 2)
                target = (nearest, 2)
                CUS_LOGGER.debug(f"黑塔相似度{max_val}，位置{max_loc[0]},{max_loc[1]}")
                if self.floor >= 13:
                    self.update_floor(12)
        # 在图像上绘制一个以(120, 128)为中心、半径为90的圆形遮罩，圆形区域外的所有像素都被涂黑
        for i in range(local_screen.shape[0]):
            for j in range(local_screen.shape[1]):
                if get_dis((120, 128), (i, j)) >= 90:
                    local_screen[i, j] = [0, 0, 0]
        # 两个交互都没有找红色点位（应该是敌人）
        if max_val <= threshold:
            red = [47, 47, 232]
            rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= self.red_threshold)
            CUS_LOGGER.debug(f"敌人检测结果{rd[0].shape[0]}")
            if rd[0].shape[0] > 0:
                # 仅检测存在性，不需要排序，使用第一个检测到的点
                nearest = (rd[1][0], rd[0][0])
                target = (nearest, 3)
                if self.floor == 12:
                    self.update_floor(13)
        if target[1] >= 1:
            CUS_LOGGER.debug(f"交互点类型{target[1]}，位置{target[0][0]},{target[0][1]}")
            self.target_type = target[1]
            self.has_target = True
            self.update_direction_data(mode=2, target=target)
            return True
        else:
            return False
    def move_direct_thread(self,device=0):
        CUS_LOGGER.info("「去成为翁法罗斯的黎明吧......」")
        self.is_find_end = 0
        if self.mini_state > 2:
            CUS_LOGGER.info("直到另一轮太阳在遥远的地平升起，为翁法罗斯带来真正的黎明。")
            self.is_find_end = self.move_to_end(mode=2,device=device)
            self.has_target=bool(self.is_find_end)
            if self.has_target:
                self.target_type=4
        else:
            self.has_target=self.move_direct_to_text()
            if self.has_target:
                self.target_type=1
        self.ready = 1
        now_time = time.time()
        if self.is_find_end == 0:
            self.is_find_end = 0.5
        while not self.stop_move and time.time() - now_time < 3:
            if self.moving_direct:
                continue
            if self.mini_state > 2:
                self.is_find_end = max(self.move_to_end(self.is_find_end,mode=3,device=device), self.is_find_end)
                if self.is_find_end!=0.5 and self.is_find_end!=0:
                    self.has_target=True
                    self.target_type=4
        CUS_LOGGER.info(f"无需再去追逐什么，如今，{factor}已是长夜尽头的烈火……")

    def backup_map(self):
        """
        备份当前地图数据到磁盘文件

        将当前的地图数据和相关属性保存到磁盘文件中，包括：
        1. 地图图像数据(big_map)保存为PNG图像文件
        2. 其他地图相关属性保存为JSON文件

        备份文件保存在项目目录下的config/backup文件夹中。
        """
        try:
            # 确保备份目录存在（相对于项目根目录）
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "backup")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # 保存 big_map 到磁盘作为图像文件
            if self.big_map is not None:
                cv.imwrite(os.path.join(backup_dir, "big_map_backup.png"), self.big_map)

            # 保存其他属性到JSON文件
            backup_data = {
                'big_map_init': self.big_map_init,
                'now_loc': self.now_loc,
                'mini_state': self.mini_state,
                'first_mini': self.first_mini
            }
            with open(os.path.join(backup_dir, "map_attrs_backup.json"), 'w') as f:
                json.dump(backup_data, f)
        except Exception:
            pass
    # 初始化地图，刚进图时调用
    def init_map(self):
        self.backup_map()
        self.big_map=None
        self.big_map_init = False
        self.now_loc = (93,93)
        self.first_mini = 1
        self.find=1
        self.red_threshold = 4500
        self.mini_state=1
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
    def save_screen(self, save_path="/temp/",force=False,not_now=False):
        """
        获取截图并保存到指定路径
        :param save_path: 保存截图的路径
        :param force: 是否展示
        """
        if not_now:
            sc=self.screen
        else:
            sc = self.get_screen()
        save_path = PATHS["root"]+save_path
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
                    self.save_screen(not_now=True,save_path="/temp/angle/")
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
    # 寻路函数
    def get_direct_with_big_map(self):
        """
        np.array颜色为（b,g,r)
        """
        CUS_LOGGER.info(f"开始有地图寻路,模式{self.find}")
        self.set_path_state("开始有地图寻路")
        self.get_loc(False)
        # 录图模式，将小地图覆盖到录制的大地图中
        if self.find == 0:
            map_num=self.pos_predictor.map_num
            map_pos=re_get_position(self.now_loc,need_int=False)
            CUS_LOGGER.debug("尝试裁剪地图中")
            self.cut_map(map_pos, self.pos_predictor.assets_floor_feat)
            CUS_LOGGER.debug("尝试写入地图中")
            self.write_map(self.pos_predictor.assets_floor_feat, map_num)
        # 寻路模式
        else:
            self.get_screen()
            self.set_path_state("开始寻路")
            self.target_loc, self.target_type = self.get_recent_target()
            now_distance=self.update_direction_data()
            if not now_distance:
                CUS_LOGGER.warning("角度更新失败，不在大地图中")
                return
            if not self._stop:
                key_mouse_manager.keyDown("w")
                key_mouse_manager.wait()
            self.is_sprinting=0
            if self.target_type != 3:
                sprint()
                self.is_sprinting = 1
            self.set_path_state("开始获取真实路径")
            if not self.get_loc():
                CUS_LOGGER.warning("路径更新失败，不在大地图中")
                return False
            # 复杂的定位、寻路过程
            go_direct = 2
            go_time=random.uniform(0.5, 0.75)
            retry_time = 0
            has_not_found_red=False
            if self.bai_e:
                add_round=7
            elif self.quan:
                add_round=4
            else:
                add_round=0
            threshold_distance = [13,21 + add_round,11,7]
            # 基于距离的位置卡住检测
            last_locs = []
            STUCK_DISTANCE_THRESHOLD = 2.0  # 卡住判定的距离阈值
            for i in range(30):
                self.set_path_state("开始定位寻路")
                CUS_LOGGER.info(f"第{i}次定位寻路")
                if self._stop == 1:
                    key_mouse_manager.keyUp("w")
                    return
                #预判实际点位
                if not self.get_loc():
                    CUS_LOGGER.warning("寻路中路径更新失败，不在大地图中")
                    return
                if self.target_type==1:
                    red = [47, 47, 232]
                    self.set_path_state("先验遇敌")
                    outside = mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True),
                                                   center_radius=85)
                    rd = np.where(
                        np.sum((outside - red) ** 2, axis=-1) <= self.red_threshold)
                    if rd[0].shape[0]:
                        # 就在旁边
                        self.set_path_state("检测到遇敌红环")
                        break
                    now_distance = get_dis(self.now_loc, self.target_loc)
                    if now_distance<20:
                        self.set_path_state("距离敌人交互点比较近")
                        CUS_LOGGER.info(f"距离小于20,开始清除{(self.target_loc, 1)}从{self.target}")
                        self.target.remove((self.target_loc, 1))
                        rd = np.where(
                            np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True,
                                                rotation=True) - red) ** 2, axis=-1) <= self.red_threshold)
                        if rd[0].shape[0] > 0:
                            self.set_path_state("尝试找新的敌人点位")
                            # 创建所有检测到的敌人坐标的列表
                            enemy_coords = []
                            for i in range(len(rd[0])):
                                enemy_x, enemy_y = rd[1][i], rd[0][i]
                                new_loc=re_get_position(self.now_loc)
                                world_x = new_loc[0] + (enemy_x - 93)*POSITION_MINIMAP_SCALE
                                world_y = new_loc[1] + (enemy_y - 93)*POSITION_MINIMAP_SCALE
                                new_loc=re_get_position((world_x, world_y),re= True)
                                enemy_coords.append((new_loc, (enemy_x, enemy_y)))

                            # 按距离self.now_loc排序，最近的在前面
                            enemy_coords.sort(key=lambda coord: get_dis(coord[0], self.now_loc))
                            # 选择最近的敌人作为目标
                            nearest_world_coord, nearest_local_coord = enemy_coords[0]
                            recent_loc = tuple(nearest_world_coord)
                            CUS_LOGGER.info(f"当前目标集合{self.target}")
                            self.target.add((recent_loc, 1))
                            self.target_loc=recent_loc
                            CUS_LOGGER.info(f"找到新的敌对目标点：{recent_loc}，共检测到{len(enemy_coords)}个敌人，按距离排序")
                        else:
                            self.set_path_state("未找到红色敌人！！！")
                            self.save_screen(not_now= True,save_path="/temp/no_red1/")
                            # self.save_screen(not_now=True)
                            has_not_found_red= True
                            # self.target_loc, type = self.get_recent_target()
                        if has_not_found_red:
                            self.set_path_state("未找到敌人！！！")
                            break
                else:
                    red = [47, 47, 232]
                    outside = mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True),
                                                   center_radius=85)
                    rd = np.where(
                        np.sum((outside - red) ** 2, axis=-1) <= self.red_threshold)
                    if rd[0].shape[0]:
                        # 就在旁边
                        self.red_threshold*=0.7
                        CUS_LOGGER.debug(f"检测到遇敌红环,但是当前为非战斗节点！！！下次阈值{self.red_threshold}")
                        self.target_type=1
                        break
                now_distance = get_dis(self.now_loc, self.target_loc)
                CUS_LOGGER.info(f"当前距离目标点{self.target_loc}距离为{now_distance}阈值{threshold_distance[self.target_type]}")
                if now_distance>threshold_distance[self.target_type]:
                    self.set_path_state("距离较远，开始更新方向2")
                    self.update_direction_data(mode=1)
                else:
                    self.set_path_state("距离目标小于阈值")
                    if self.target_type == 0:
                        self.target.remove((self.target_loc, self.target_type))
                        CUS_LOGGER.info("已到达路径点" + str((self.target_loc, self.target_type)))
                        self.last_interact_time = time.time()
                        self.target_loc, self.target_type = self.get_recent_target()
                        if self.target_type == 3:
                            sprint()
                            self.is_sprinting = 0
                        go_direct = 2
                    else:
                        key_mouse_manager.keyUp("w")
                        break
                self.set_path_state(f"获取当前距离目标距离{now_distance}")
                # 检查是否位置卡住（连续3次距离过小）
                last_locs.append(self.now_loc)
                if len(last_locs) > 3:
                    last_locs.pop(0)
                # 判断是否卡住：连续3个位置间距离都小于阈值
                is_stuck = False
                if len(last_locs) == 3:
                    dist1 = get_dis(last_locs[0], last_locs[1])
                    dist2 = get_dis(last_locs[1], last_locs[2])
                    dist3 = get_dis(last_locs[0], last_locs[2])
                    is_stuck = (dist1 < STUCK_DISTANCE_THRESHOLD and
                               dist2 < STUCK_DISTANCE_THRESHOLD and
                               dist3 < STUCK_DISTANCE_THRESHOLD)
                # 距离没有更近 或者 位置卡住：开始尝试绕过障碍
                if is_stuck:
                    CUS_LOGGER.debug(f"自身坐标{self.now_loc}，目标坐标{self.target_loc}")
                    CUS_LOGGER.debug("距离未改善，开始尝试绕过障碍")
                    self.set_path_state("尝试绕过障碍")
                    ts = " da"
                    if go_direct > 0:
                        CUS_LOGGER.info(f"尝试绕过障碍向{ts[go_direct]}")
                        key_mouse_manager.keyUp("w")
                        key_mouse_manager.press("s", 0.35)
                        if go_direct==2:
                            key_mouse_manager.press(ts[go_direct], go_time)
                        else:
                            key_mouse_manager.press(ts[go_direct], go_time+random.uniform(0, 0.5))
                        key_mouse_manager.keyDown("w")
                        self.get_screen()
                        if not self.get_loc():
                            CUS_LOGGER.info("绕过障碍中不在大地图界面，返回")
                            return
                        # 成功绕过障碍后清空位置记录
                        last_locs.clear()
                        go_direct -= 1
                    else:
                        CUS_LOGGER.info("尝试次数过多，不再尝试绕过障碍")
                        key_mouse_manager.keyUp("w")
                        break
                self.set_path_state("距离目标更近了")
                retry_time += 1
                key_mouse_manager.wait()
            self.set_path_state("结束寻路")
            CUS_LOGGER.info(f"寻路判断已到达交互点附近 {now_distance}")
            key_mouse_manager.clean()
            key_mouse_manager.keyUp("w")
            key_mouse_manager.wait()
            if not self.get_loc():
                CUS_LOGGER.info("结束寻路后后不在大地图界面，返回")
                return
            if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                if self.target_type != 3 and self.good_f()[0] and not self.ts.similar("黑塔"):
                    self.set_path_state("位于交互点，移除交互点")
                    for j in deepcopy(self.target):
                        #类型为二，交互点
                        if j[1] == 2:
                            self.target.remove(j)
                            CUS_LOGGER.info("检测到交互点，已移除目标:" + str(j))
                    return
            if self.target_type == 1:
                if has_not_found_red:
                    self.target.add((self.target_loc, 0))
                    self.target_type = 0
                    CUS_LOGGER.info("寻路时未找到敌对目标点，强行攻击后把旧目标点视作路径")
                self.set_path_state("准备开战")
                CUS_LOGGER.info("准备开战")
                local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
                red = [47, 47, 232]
                rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= self.red_threshold)
                if rd[0].shape[0] > 0:
                    enemy_coords = []
                    for i in range(len(rd[0])):
                        enemy_coords.append((rd[1][i], rd[0][i]))
                    # 按距离self.now_loc排序，最近的在前面
                    enemy_coords.sort(key=lambda coord: get_dis(coord, (93,93)))
                    # 选择最近的敌人作为目标
                    target = (tuple(enemy_coords[0]), 3)
                    self.update_direction_data(mode=2, target=target)
                if self.quan:
                    key_mouse_manager.keyUp("w")
                    for _ in range(2):
                        self.use_e()
                    if not self.get_loc():
                        CUS_LOGGER.info("开战后不在大地图界面，返回")
                        return
                    key_mouse_manager.press('w')
                elif self.bai_e:
                    self.use_e()
                    if not self.get_loc():
                        CUS_LOGGER.info("开战后不在大地图界面，返回")
                        return
                    key_mouse_manager.press('w')
                else:
                    key_mouse_manager.click(0.5, 0.5)
            if self.target_type == 3:
                self.set_path_state("当前寻找终点")
                for i in range(9):
                    self.get_screen()
                    if not self.is_run():
                        CUS_LOGGER.info("找终点时不在大地图，返回")
                        return
                    if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        CUS_LOGGER.info("大图识别到类型三传送点")
                        key_mouse_manager.press('f',force= True)
                        key_mouse_manager.wait()
                        if self.nof(must_be='tp'):
                            return
                    if not self.is_run():
                        return
                    if i in [0,4]:
                        self.move_to_end(mode=1)
                    key_mouse_manager.press('w')
                    key_mouse_manager.wait()
            # 离目标点挺近了，准备找下一个目标点
            elif now_distance <= 20:
                self.set_path_state("距离目标非常近")
                try:
                    CUS_LOGGER.info("靠近目标点，尝试移除:" + str((self.target_loc, self.target_type)))
                    self.last_interact_time = time.time()
                    self.target.remove((self.target_loc, self.target_type))
                    CUS_LOGGER.info("靠近目标点，成功移除:" + str((self.target_loc, self.target_type)))
                except Exception:
                    pass
            self.set_path_state("结束寻路")



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

    def write_map(self, map, map_num):
        """
        写入地图
        """
        small_map_set=crop(map, [self.cut_pos[0],self.cut_pos[2],self.cut_pos[1],self.cut_pos[3]])
        if self.start_pos[0]==0 and self.start_pos[1]==0:
            self.start_pos=self.now_loc
        CUS_LOGGER.debug(f"地图保存至{self.map_file},起点{self.start_pos}")
        cv.imwrite(
            self.map_file + f"map_{map_num}_({self.start_pos[0]},{self.start_pos[1]}).jpg", small_map_set
        )
        pos=re_get_position(self.start_pos)
        # 将灰度图转换为BGR彩色图以便使用颜色
        map_color = cv.cvtColor(map.copy(), cv.COLOR_GRAY2BGR)
        # 绘制绿色小圆点标记起点
        cv.circle(map_color,
                   tuple(pos),
                   radius=1,
                   color=(0, 255, 0),  # 绿色
                   thickness=-1)
        small_map_set = crop(map_color, [self.cut_pos[0], self.cut_pos[2], self.cut_pos[1], self.cut_pos[3]])
        self.debug_map=deepcopy(small_map_set)
        cv.imwrite(self.map_file + f"target_{self.cut_pos[0]}_{self.cut_pos[2]}.jpg", small_map_set)

    # 匹配地图，找到最相似的地图，确定当前房间对应的地图
    def match_scr(self, img):
        img = deal_minimap(img,is_minimap=True)
        max_sim = -1
        ans = -1
        scale=0.5
        # CUS_LOGGER.debug(f"开始匹配地图，缩放比例{scale}地图集合{self.img_map}")
        for k,v in self.img_map.items():
            local = cv.resize(img, None, fx=scale, fy=scale, interpolation=cv.INTER_CUBIC)
            search_image = v
            result = cv.matchTemplate(search_image, local, cv.TM_CCOEFF_NORMED)
            _, sim, _, loca = cv.minMaxLoc(result)
            # cv2.imshow("match_result.png", search_image)
            # cv2.imshow("local.png", local)
            # cv2.waitKey(0)
            if sim > max_sim:
                max_sim = sim
                ans = k
        # CUS_LOGGER.debug(f"匹配地图结果{ans}相似度{max_sim}")
        return ans, max_sim

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
    def update_floor(self,v):
        self.floor = v
        self.floor_change=True
    def add_floor(self):
        self.floor+=1
        self.floor_change = True
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
    def update_debug_map(self):
        self.debug_map = deepcopy(get_minimap(self.get_screen(), radius=MINIMAP_RADIUS))
        if self.pos_map is not None:
            self.pos_map=None
    def auto_update_map(self):
        if self.has_update:
            return
        self.has_update=True
        while self.should_update_map and not self._stop:
            CUS_LOGGER.info(f"{factor}铭记了此刻，铭记了所有无法亲眼目睹世界尽头的友人们与他们的夙愿……")
            self.update_debug_map()
            time.sleep(2)
        self.has_update=False
    def get_direc_only_minimap(self):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        self.check_bonus含义
        是否领取沉浸奖励
        """
        CUS_LOGGER.info("开始无地图寻路")
        if self.state=="battle":
            CUS_LOGGER.info("战斗中，返回")
            return
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        #打补给罐子
        if self.mini_state==1 and self.floor in [5,9,12]:
            key_mouse_manager.press('w',0.55)
            key_mouse_manager.click(0.5,0.5)
            key_mouse_manager.press('w')
            key_mouse_manager.wait()
        #13层并且不要奖励
        if self.mini_state==3 and self.floor==13 and not self.check_bonus:
            self.mini_state=5
        #4，8，13层领奖
        if self.mini_state==3 and self.floor in [4,8,13] and self.check_bonus:
            key_mouse_manager.press('d',0.6)
            key_mouse_manager.keyDown('w')
            nt = time.time()
            while time.time()-nt<1.3:
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                    key_mouse_manager.press('f',force= True)
                    key_mouse_manager.keyUp('w')
                    break
            key_mouse_manager.keyUp('w')
            key_mouse_manager.press('f',force= True)
            key_mouse_manager.wait()
            for _ in range(2):
                if not self.check_bonus:
                    break
                #领取沉浸奖励
                if self.check('bonus_c',0.2385,0.6685,fresh=True):
                    key_mouse_manager.click(0.4453,0.3250)
                    key_mouse_manager.wait()
                    if self.click_text(text="储存沉浸器",box=[838, 1070, 298, 400],click=False,ocr_line=False,warning=False):
                        self.check_bonus = 0
                    key_mouse_manager.click(0.5062, 0.1454)
                    key_mouse_manager.wait()
            key_mouse_manager.keyUp('w')
            if self.check('bonus_c',0.2385,0.6685,fresh=True):
                key_mouse_manager.click(0.2385,0.6685)
            self.mini_state=5
            if self.floor==13:
                self.should_update_map = False
                return
            key_mouse_manager.press('s',0.4)
        self.stop_move=0
        self.ready=0
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        self.get_screen()
        first = self.first_mini
        CUS_LOGGER.info("移动方向前往交互点(大图)")
        self.target_type = -1
        if not self.move_to_interact(2):
            CUS_LOGGER.info("未在小地图找到交互")
            self.has_target=False
            if self.floor==13 and self.mini_state>=5:
                key_mouse_manager.press('esc')
                key_mouse_manager.wait()
                self.update_state("exit")
                self.should_update_map=False
                return
        if not self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95,fresh=True) and not self.has_target or (self.target_type==2 and self.has_target and self.mini_state>2):
            ThreadWithException(target=self.move_direct_thread, name="移动").start()
        else:
            self.ready = 1
        while not self.ready:
            time.sleep(0.1)
        if self.mini_state == 1 and self.floor == 12 and self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
            self.update_floor(13)
        key_mouse_manager.keyDown("w")
        run_wait_time = 4
        self.first_mini = 0
        self.is_sprinting = 0
        if self.mini_state==1:
            run_wait_time += 1
            sprint()
            self.is_sprinting = 1
            #事件
            if self.target_type!=3:
                run_wait_time += 0.8
        need_confirm=0
        init_time = time.time()
        while True:
            CUS_LOGGER.info("开始检测交互点循环")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            key_mouse_manager.keyUp("w")
            key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("未检测到f交互")
                key_mouse_manager.keyDown("w")
            if have_f and self.target_type==1:
                key_mouse_manager.press('f')
                CUS_LOGGER.info('发现事件交互')
                self.stop_move=1
                need_confirm = 1
                if self.nof(must_be='event'):
                    self.should_update_map = False
                    return
                break
            elif have_f:
                CUS_LOGGER.info("发现其它交互")
                judge,use_time=self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    CUS_LOGGER.info("不是黑塔或是黑塔但上次交互超过30秒")
                    if self.speed <= 0 or not self.ts.similar("黑塔"):
                        CUS_LOGGER.info("不是速通或并非黑塔")
                        key_mouse_manager.press('f')
                        key_mouse_manager.press('s',use_time)
                        self.stop_move = 1
                        key_mouse_manager.wait()
                        need_confirm = 1
                        CUS_LOGGER.info('等待验证交互文本 ' + self.ts.text)
                        if self.nof():
                            CUS_LOGGER.info("未检测到f")
                            key_mouse_manager.keyUp("w")
                            self.should_update_map = False
                            return
                        break
                    else:
                        self.quit = time.time()
                        key_mouse_manager.keyUp("w")
                        self.stop_move=1
                        self.mini_state+=2
                        self.should_update_map = False
                        return
                elif self.ts.similar("黑塔") and time.time() - self.quit < 30:
                    CUS_LOGGER.info("检测到黑塔,但上次交互时间过短")
                    key_mouse_manager.press("w")
                    self.mini_state+=2
                    self.should_update_map = False
                else:
                    CUS_LOGGER.info("未检测到黑塔")
                    key_mouse_manager.keyUp("w")
            if self.check("auto_2", 0.0583, 0.0769):
                CUS_LOGGER.info("检测到位于战斗中")
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                self.mini_state+=2
                key_mouse_manager.wait()
                break
            if self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                CUS_LOGGER.info("检测到怪物z标志")
                self.stop_move=1
                if self.mini_state==1 and self.floor in [4, 8, 13] and not (self.quan or self.bai_e):
                    key_mouse_manager.keyUp("w")
                    if not self.check("ruan",0.0625,0.7065,threshold=0.95) and not self.check("U", 0.0240,0.7759):
                        for i in range([4, 8, 13].index(self.floor)+2):
                            key_mouse_manager.press(str(i+1))
                            key_mouse_manager.wait()
                            self.use_e()
                            self.get_screen()
                            if not self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                                break
                            if self._stop:
                                break
                    key_mouse_manager.keyDown("w")
                    key_mouse_manager.wait()
                iters = 0
                while self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95,fresh=True) and not self._stop:
                    CUS_LOGGER.info("检测到怪物，准备攻击")
                    key_mouse_manager.keyUp("w")
                    iters+=1
                    if iters>4:
                        break
                    red = [47, 47, 232]
                    outside=mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True), center_radius=80)
                    rd = np.where(
                        np.sum((outside - red) ** 2, axis=-1) <= self.red_threshold)
                    if rd[0].shape[0]:
                        #就在旁边
                        pass
                        # key_mouse_manager.keyUp("w")
                    else:
                        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True)
                        rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= self.red_threshold)
                        if rd[0].shape[0] > 0:
                            # 仅检测存在性，不需要排序，使用第一个检测到的点
                            target = ((rd[1][0], rd[0][0]), 3)
                            self.get_screen()
                            # local_screen = self.get_local(0.9333, 0.8657, shape)
                            ds=self.update_direction_data(mode=2,target=target)
                            if not ds:
                                break
                        else:
                            #没扫到红点，却有z的怪物标识，那红点可能被蓝色箭头挡住了，说明很近了
                            ds=0
                        if ds>28:
                            key_mouse_manager.keyDown("w")
                            if self.is_sprinting:
                                wait_time = (ds - 22.0) / 12
                                CUS_LOGGER.debug(f"距离目标{ds},太远，等待{(ds - 22.0) / 12}秒(冲刺)")
                            else:
                                wait_time = (ds - 22.0) / 8
                                CUS_LOGGER.debug(f"距离目标{ds},太远，等待{(ds - 22.0) / 8}秒")
                            now=time.time()
                            while time.time()-now<wait_time:
                                self.get_screen()
                                if predict(self.screen, enemy=True, item=False)['enemy'] is not None:
                                    CUS_LOGGER.info("检测到待击杀目标")
                                    self.save_screen(not_now=True,save_path="/temp/kill/")
                                    break

                    if self.quan:
                        key_mouse_manager.keyUp("w")
                        self.use_e()
                        if self.floor not in [4, 8, 13]:
                            for _ in range(2):
                                self.use_e()
                            self.stop_move=1
                            self.mini_state+=2
                            self.should_update_map = False
                            return
                        else:
                            key_mouse_manager.keyDown("w")
                    elif self.bai_e:
                        # key_mouse_manager.keyUp("w")
                        self.use_e(face=True)
                        if self.floor not in [4, 8, 13]:
                            self.stop_move = 1
                            self.mini_state += 2
                            key_mouse_manager.press('w')
                            self.should_update_map = False
                            return
                        else:
                            key_mouse_manager.keyDown("w")
                    else:
                        key_mouse_manager.click(0.5,0.5)
                    if iters + self.quan == 2:
                        key_mouse_manager.press('d',0.85)
                        key_mouse_manager.press('a',0.3)
                self.mini_state+=2
                break
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("检测到其它界面，退出循环")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.info(f"等待时间超时,是否有目标{self.has_target}")
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    self.last_interact_time = 0
                    self.should_update_map = False
                    key_mouse_manager.press('esc')
                    key_mouse_manager.wait()
                    self.update_state("ui")
                    return
                if self.has_target and self.target_type!=3:
                    key_mouse_manager.press('s',0.3)
                    key_mouse_manager.press('a',0.7)
                    key_mouse_manager.press('d',0.45)
                    key_mouse_manager.press('w',0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click(0.5,0.5)
                    key_mouse_manager.wait()

                break
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        if self.fresh_state()==1:
            self.should_update_map = False
            return
        if self.state=="run" and (need_confirm or (first and self.target_type!=2)):
            CUS_LOGGER.info("尝试乱转找到交互点")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.target_type==1:
                    CUS_LOGGER.info("必须找到交互点，尝试寻找")
                    if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        key_mouse_manager.press('f',force= True)
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                elif self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                    key_mouse_manager.keyUp(i)
                    key_mouse_manager.wait()
                    if self.good_f()[0] and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                        CUS_LOGGER.info("找到最佳交互点")
                        key_mouse_manager.press('f',force= True)
                        self.get_screen()
                        if self.nof():
                            self.should_update_map = False
                            return
                if self.is_find_end==1 and self.mini_state > 2:
                    if self.move_to_end(mode=0):
                        key_mouse_manager.press('w')
                        key_mouse_manager.wait()
                elif self.move_direct_to_text():
                    i="w"
                key_mouse_manager.press(i, 0.25)
                CUS_LOGGER.info(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False
    def get_event_only_minimap(self):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        """
        CUS_LOGGER.info(f"{factor}以「负世」之名向你保证……刻法勒永志不忘。")
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        self.stop_move=0
        self.ready=0
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        self.is_find_end = 0
        self.get_screen()
        CUS_LOGGER.info(f"{factor}决定穿过那道门扉，去拥抱一个更适合「毁灭」的结局.")
        self.target_type = -1
        if not self.move_to_event():
            CUS_LOGGER.info("相比一团只懂得燃烧的火焰，她一定能在救世的路上走得更远。")
            self.has_target=False
            if self.mini_state > 2:
                CUS_LOGGER.info(f"{factor}也会和曾经的他们一样，带着记忆和火焰…走进新生的混沌。")
                self.is_find_end = self.move_to_end(mode=2,device=1)
                self.has_target = bool(self.is_find_end)
                if self.has_target:
                    self.target_type = 4
            else:
                self.map_data_load(create=False)
                if int(self.now_map)==27793:
                    key_mouse_manager.mouse_move(15)
                else:
                    self.has_target=self.move_direct_to_text()
            CUS_LOGGER.info(f"{factor}需要在此驻足片刻，消化那千万次循环中沉积的悲伤、痛苦和挣扎。")
        else:
            self.has_target=True
            self.target_type = 1
        if not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
            key_mouse_manager.keyDown("w")
        run_wait_time = 2
        self.first_mini = 0
        self.is_sprinting = 0
        if self.has_target:
            run_wait_time+=4
        if self.mini_state==1:
            sprint()
            self.is_sprinting = 1
        need_confirm=0
        init_time = time.time()
        while True:
            key_mouse_manager.wait()
            CUS_LOGGER.info("请求：「救世主，带领吾等前进吧。」")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            if self.mini_state>1:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("「但倘若黎明从一开始就不存在……」")
                key_mouse_manager.keyDown("w")
            if have_f:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.press('f')
                CUS_LOGGER.info('「那就让怒火燃尽此身，化作明日的烈阳！」')
                self.stop_move=1
                need_confirm = 1
                if self.nof(must_be='event'):
                    self.should_update_map = False
                    return
                break
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("响应：「一道无足轻重的伤疤。」")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press('s',0.3)
                    key_mouse_manager.press('a',0.7)
                    key_mouse_manager.press('d',0.45)
                    key_mouse_manager.press('w',0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click(0.5,0.5)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        if not self.is_run():
            self.should_update_map = False
            return
        first_find=self.first_mini
        if need_confirm or self.has_target:
            CUS_LOGGER.info(f"{factor}会坚守。直到有人前来打破这漫长的轮回，为翁法罗斯的命运添上结尾。")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.target_type==1:
                    CUS_LOGGER.info("沿着他们的足迹……写下前所未有的结局。")
                    if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        key_mouse_manager.press('f',force= True)
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                        else:
                            key_mouse_manager.press('f')
                            if self.nof(must_be='event'):
                                self.should_update_map = False
                                return
                if (self.is_find_end==1 or first_find) and self.mini_state > 2:
                    first_find=False
                    if self.move_to_end(mode=0,device=1):
                        i = "w"
                elif self.move_to_event():
                    i="w"
                elif self.move_direct_to_text():
                    i="w"
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                    key_mouse_manager.press('f',force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                    else:
                        key_mouse_manager.press('f')
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                key_mouse_manager.press(i, 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False
    def get_rest_only_minimap(self):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        """
        CUS_LOGGER.info("「那个身影燃烧自己……但也燃尽周围所有的一切……」")
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        #打补给罐子
        if self.mini_state==1:
            key_mouse_manager.press('w',0.55)
            key_mouse_manager.click(0.5,0.5)
            key_mouse_manager.press('w')
            key_mouse_manager.wait()
        self.stop_move=0
        self.ready=0
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        self.is_find_end = 0
        self.get_screen()
        first = self.first_mini
        CUS_LOGGER.info("在一片死寂中，那形如焦炭的熟悉身影踽踽独行，朝着漫无止尽的黑暗走去。")
        self.target_type = -1
        if not self.move_to_event(rest=True):
            CUS_LOGGER.info("梦中，太阳坠落，英雄的造像崩塌，融化，碎裂，将世界烧成一片灰烬。")
            self.has_target=False
            if self.mini_state > 2:
                CUS_LOGGER.info(f"{factor}不会知晓这趟旅程有多遥远，直到成为熊熊燃烧的薪柴，去壮大那徒劳的火焰。")
                self.is_find_end = self.move_to_end(mode=2,device=1)
                self.has_target = bool(self.is_find_end)
                if self.has_target:
                    self.target_type = 4
            CUS_LOGGER.info("请回头吧，别将你那荒谬又不公的命运付诸实现。")
        else:
            self.has_target=True
            self.target_type = 2
        key_mouse_manager.keyDown("w")
        run_wait_time = 2
        self.first_mini = 0
        self.is_sprinting = 0
        if self.has_target:
            run_wait_time+=5
        if self.mini_state==1:
            run_wait_time += 2
            sprint()
            self.is_sprinting = 1
        need_confirm=0
        init_time = time.time()
        while True:
            key_mouse_manager.wait()
            CUS_LOGGER.info(f"{factor}拒绝了「死亡」：他将灵魂化为烈火…为了将那「毁灭」的神像焚烧殆尽。")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("醒醒…迷途者啊……看清那黑暗中的火光…并非……")
                key_mouse_manager.keyDown("w")
            if have_f:
                if self.mini_state <=1:
                    key_mouse_manager.keyUp("w")
                CUS_LOGGER.info(" 火焰尚有缺欠。必须…助长火焰。")
                judge, use_time = self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    CUS_LOGGER.info("哪怕…要将这副身躯焚毁……")
                    if not self.ts.similar("黑塔"):
                        CUS_LOGGER.info("不管付出多少口舌，结局都不会改变。")
                    else:
                        self.quit = time.time()
                        self.mini_state += 2
                    key_mouse_manager.keyUp("w")
                    key_mouse_manager.press('f')
                    key_mouse_manager.press('s', use_time)
                    self.stop_move = 1
                    key_mouse_manager.wait()
                    need_confirm = 1
                    self.should_update_map = False
                    if self.nof():
                        CUS_LOGGER.info("做出你们最大的努力抗争，或是接受命运，将火种交给他……")
                        key_mouse_manager.keyUp("w")
                        self.should_update_map = False
                        return
                    break
                elif self.ts.similar("黑塔") and time.time() - self.quit < 30:
                    CUS_LOGGER.info("也许你所行的根本不是拯救的道路，只是单纯地把这世界拖入火海而已。")
                    key_mouse_manager.press("w")
                    self.mini_state += 2
                    self.should_update_map = False
                else:
                    CUS_LOGGER.info("你心底的救世主情结，已将你变得与你口中冷眼的神明并无区别。")
                    need_confirm=1
                    break
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("那些你誓言要拯救的人子…如今在你眼里，他们的性命恐怕与蝼蚁无异吧？")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press('s',0.3)
                    key_mouse_manager.press('a',0.7)
                    key_mouse_manager.press('d',0.45)
                    key_mouse_manager.press('w',0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click(0.5,0.5)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        if not self.is_run():
            self.should_update_map = False
            return
        if need_confirm or self.has_target:
            CUS_LOGGER.info("你的冷漠令我心寒。他们对你而言，只是一堆无足轻重的注脚？")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.target_type==2:
                    CUS_LOGGER.info("可是，告诉我……若当真如此，我们又为何会步入相同的结局？")
                    if self.good_f(run=False)[0]:
                        key_mouse_manager.press('f',force= True)
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            self.mini_state+=2
                            return
                if (self.is_find_end==1 or first) and self.mini_state > 2:
                    if self.move_to_end(mode=0,device=1):
                        i="w"
                elif self.move_to_event(rest=True):
                    i="w"
                if self.good_f(run=False)[0]:
                    key_mouse_manager.press('f',force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                key_mouse_manager.press(i, 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False
    def get_adventure(self):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        """
        CUS_LOGGER.info("「这样的世界……正在呼唤著英雄的到来吧……」")
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        self.is_find_end = 0
        self.get_screen()
        CUS_LOGGER.info("「哪怕百次，万次，千万次…英雄可以被毁灭，但绝不会被打败……」")
        self.target_type = -1
        if self.mini_state > 2:
            CUS_LOGGER.info(f"到达终点时，{factor}才会得知自己已行过漫长的路。")
            self.is_find_end = self.move_to_end(mode=2,device=1)
            self.has_target = bool(self.is_find_end)
            if self.has_target:
                self.target_type = 4
        key_mouse_manager.keyDown("w")
        run_wait_time = 2
        self.first_mini = 0
        self.is_sprinting = 0
        if self.has_target:
            run_wait_time+=5
        if self.mini_state==1:
            run_wait_time += 2
            sprint()
            self.is_sprinting = 1
        init_time = time.time()
        while True:
            key_mouse_manager.wait()
            CUS_LOGGER.info(f"{factor}请求：「成为回应世界期许，背负众人心愿的人。」")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("响应：「一个孑然一身的人。」")
                key_mouse_manager.keyDown("w")
            if have_f:
                if self.mini_state <=1:
                    key_mouse_manager.keyUp("w")
                judge, _ = self.good_f()
                if judge:
                    key_mouse_manager.keyUp("w")
                    key_mouse_manager.press('f')
                    key_mouse_manager.wait()
                    self.should_update_map = False
                    if self.nof(must_be="challenge"):
                        CUS_LOGGER.info(f"最后一次，{factor}回想起那个朝阳初升的时刻，自己曾刻下理想的雏形…")
                        key_mouse_manager.keyUp("w")
                        if self.is_run():
                            key_mouse_manager.press("esc")
                            key_mouse_manager.wait()
                            self.update_state("ui")
                            self.should_update_map = False
                            return
                    break
                else:
                    CUS_LOGGER.info(f"{factor}为它取另外一个名字——「救世主」。而他自己的名，就此在记忆中零落。")
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("警告：进度无法更新,检测到其它界面,退出循环")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                break
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        self.should_update_map = False
        return
    def get_shop_only_minimap(self):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        """
        CUS_LOGGER.info("「汝将肩负骄阳…直至…」")
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        self.stop_move=0
        self.ready=0
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        self.is_find_end = 0
        self.get_screen()
        first = self.first_mini
        CUS_LOGGER.info("那就去吧，卡厄斯兰那。如你约定的那般：欺骗世界，夺得火种，扭转命运……")
        self.target_type = -1
        if not self.move_to_shop():
            CUS_LOGGER.info(f"那些源自本心的坚持和选择，{factor}不相信它们是所谓「命途」的设计……")
            self.has_target=False
            if self.mini_state > 2:
                CUS_LOGGER.info("奋力地燃烧自己，以徒劳为剑，反抗神明吧——")
                key_mouse_manager.wait()
                self.is_find_end = self.move_to_end(mode=2,device=1)
                self.has_target = bool(self.is_find_end)
                if self.has_target:
                    self.target_type = 4
            CUS_LOGGER.info("…你害怕了吗？在了解到自己的本源后……")
        else:
            self.has_target=True
            self.target_type = 2
            if self.mini_state > 2:
                CUS_LOGGER.info(f"你会将「我」给予你的动力，视作「毁灭」蛊惑人心的低语吗？(当前状态{self.mini_state})")
                key_mouse_manager.wait()
                self.is_find_end = self.move_to_end(mode=2,device=1)
                self.has_target = bool(self.is_find_end)
                if self.has_target:
                    self.target_type = 4
        key_mouse_manager.keyDown("w")
        run_wait_time = 4
        self.first_mini = 0
        self.is_sprinting = 0
        if self.mini_state==1:
            run_wait_time += 1.8
            sprint()
            self.is_sprinting = 1
        need_confirm=0
        init_time = time.time()
        while True:
            key_mouse_manager.wait()
            CUS_LOGGER.info(f"每一个人的愿望…{factor}都铭记在心。")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("听好，自往日而来的救世主——请回头吧——勿要惊扰它们，那众多鲜花的如泥死亡。")
                key_mouse_manager.keyDown("w")
            if have_f:
                if self.mini_state<=1:
                    key_mouse_manager.keyUp("w")
                CUS_LOGGER.info(f"{factor}…从未抛弃过。")
                judge, use_time = self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    CUS_LOGGER.info("相比炽盛的神火，人性的部分…实在微小。")
                    if not self.ts.similar("黑塔"):
                        CUS_LOGGER.info("空洞的火焰，无法拯救任何人……")
                    else:
                        self.quit = time.time()
                        self.mini_state += 2
                    key_mouse_manager.keyUp("w")
                    key_mouse_manager.press('f')
                    key_mouse_manager.press('s', use_time)
                    self.stop_move = 1
                    key_mouse_manager.wait()
                    need_confirm = 1
                    self.should_update_map = False
                    if self.nof():
                        CUS_LOGGER.info("…将这团火递给下一个我……无数次…无数次…无数次。")
                        key_mouse_manager.keyUp("w")
                        self.should_update_map = False
                        return
                    break
                elif self.ts.similar("黑塔") and time.time() - self.quit < 30:
                    CUS_LOGGER.info("你自己…无数个你自己的愿望…又是什么呢？")
                    key_mouse_manager.press("w")
                    self.mini_state += 2
                    self.should_update_map = False
                else:
                    CUS_LOGGER.info("当你毫无怨言地…背负起世界的时候……属于你的「自我」，就无法诞生了啊。")
                    need_confirm=1
                    break
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("你已无力为继了…半神。把火种，交给我。让你我…尽快结束痛苦。")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press('s',0.3)
                    key_mouse_manager.press('a',0.7)
                    key_mouse_manager.press('d',0.45)
                    key_mouse_manager.press('w',0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click(0.5,0.5)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        if not self.is_run():
            self.should_update_map = False
            return
        if need_confirm or self.has_target:
            CUS_LOGGER.info("再骄盛的太阳，也有遍照不到的地方。")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.target_type==2:
                    CUS_LOGGER.info("……直到，逆转「再创世」揭示的残酷未来。")
                    if self.good_f(run=False)[0]:
                        key_mouse_manager.press('f',force= True)
                        key_mouse_manager.keyUp('w')
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                if (self.is_find_end==1 or first) and self.mini_state > 2:
                    if self.move_to_end(mode=0,device=1):
                        i="w"
                elif self.move_to_shop():
                    i="w"
                if self.good_f(run=False)[0]:
                    key_mouse_manager.press('f',force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                key_mouse_manager.press(i, 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False
    def get_path_only_minimap(self,fixed=False):
        """
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        """
        CUS_LOGGER.info("走下去…背负这个世界…直到…灰白的英雄…无名的救世主…带来黎明……")
        if self.debug:
            CUS_LOGGER.debug(f'当前状态{self.mini_state}')
        self.should_update_map=True
        ThreadWithException(target=self.auto_update_map,name="更新地图").start()
        self.stop_move=0
        self.ready=0
        self.is_target = 0
        self.moving_direct=False
        self.has_target=True
        CUS_LOGGER.info(f"PhiLia093已经拥抱了她的命运……而{factor}，也会投身自己的本源——「毁灭」。")
        self.target_type = -1
        if not self.move_to_red_point():
            CUS_LOGGER.info("想反悔就反悔，孩子们总是幸福的……可属于大人的命运，从来没有回头的选择。")
            self.has_target=False
        if not self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95,fresh=True) and not self.has_target:
            ThreadWithException(target=self.move_direct_thread,
    kwargs={"device":1}, name="移动").start()
            while not self.ready:
                time.sleep(0.1)
        key_mouse_manager.keyDown("w")
        run_wait_time = 2
        self.first_mini = 0
        self.is_sprinting = 0
        if self.has_target:
            run_wait_time+=3
        if self.mini_state==1:
            run_wait_time += 1
            sprint()
            self.is_sprinting = 1
            #事件
            if self.target_type!=3:
                run_wait_time += 0.8
        need_confirm=0
        init_time = time.time()
        while True:
            CUS_LOGGER.info(f"{factor}以「愤怒」铭记此世的全部。只要{factor}还在燃烧，他们就从未离去。")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            if self.has_target:
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96)
            if not have_f:
                CUS_LOGGER.info(f"{factor}的悲伤从未消逝。恰恰相反，火种加诸此身，他心中的火焰前所未有地暴烈……")
                key_mouse_manager.keyDown("w")
            elif have_f:
                CUS_LOGGER.info(f"然后，{factor}杀死了自己。")
                key_mouse_manager.press('f')
                self.stop_move = 1
                key_mouse_manager.wait()
                need_confirm = 1
                CUS_LOGGER.debug('等待验证交互文本 ' + self.ts.text)
                if self.nof("tp"):
                    CUS_LOGGER.info(f"而后，{factor}在这次轮回中的一切努力，也会在同一时间化为泡影。")
                    key_mouse_manager.keyUp("w")
                    self.should_update_map = False
                    if not self.is_run():
                        return
                break
            if self.check("auto_2", 0.0583, 0.0769):
                CUS_LOGGER.info("「逐火是不断失却的旅途，在那一切当中，生命也微不足惜。」")
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                self.mini_state+=2
                key_mouse_manager.wait()
                return
            if self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                CUS_LOGGER.info("「付之一炬」…多么熟悉的结局。它也出现在每一段旅途里，始终如一。")
                self.stop_move=1
                iters = 0
                while self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95,fresh=True) and not self._stop:
                    CUS_LOGGER.info("「羁客」与「学士」兑现了他们的命运，再一次。")
                    key_mouse_manager.keyUp("w")
                    iters+=1
                    if iters>4:
                        break
                    red = [47, 47, 232]
                    rd = np.where(
                        np.sum((mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True), center_radius=80) - red) ** 2, axis=-1) <= self.red_threshold)
                    if not rd[0].shape[0]:
                        rd = np.where(np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True) - red) ** 2, axis=-1) <= self.red_threshold)
                        if rd[0].shape[0] > 0:
                            # 仅检测存在性，不需要排序，使用第一个检测到的点
                            target = ((rd[1][0], rd[0][0]), 3)
                            self.get_screen()
                            ds=self.update_direction_data(mode=2,target=target)
                            if not ds:
                                break
                        else:
                            #没扫到红点，却有z的怪物标识，那红点可能被蓝色箭头挡住了，说明很近了
                            ds=0
                        if ds>28:
                            key_mouse_manager.keyDown("w")
                            if self.is_sprinting:
                                wait_time = (ds - 22.0) / 12
                                CUS_LOGGER.debug(f"距离目标{ds},太远，等待{(ds - 22.0) / 12}秒(冲刺)")
                            else:
                                wait_time = (ds - 22.0) / 8
                                CUS_LOGGER.debug(f"距离目标{ds},太远，等待{(ds - 22.0) / 8}秒")
                            now=time.time()
                            while time.time()-now<wait_time:
                                self.get_screen()
                                if predict(self.screen, enemy=True, item=False)['enemy'] is not None:
                                    CUS_LOGGER.info(f"或者，兑现命运的不止他们。只是{factor}已记不清了。")
                                    if self.debug:
                                        self.save_screen(not_now=True,save_path="/temp/kill/")
                                    break

                    if self.quan:
                        key_mouse_manager.keyUp("w")
                        skill_num=match_skill_numbers_in_region(self.get_screen())
                        if skill_num is not None:
                            self.skill_num=skill_num
                        if self.skill_num==0:
                            fixed=True
                        self.use_e(fixed=fixed)
                        if self.floor not in [4, 8, 13]:
                            for _ in range(2):
                                self.use_e(fixed=fixed)
                            self.stop_move=1
                            self.mini_state+=2
                            self.should_update_map = False
                            return
                        else:
                            key_mouse_manager.keyDown("w")
                    elif self.bai_e:
                        skill_num = match_skill_numbers_in_region(self.get_screen())
                        if skill_num is not None:
                            self.skill_num = skill_num
                        if self.skill_num == 0:
                            fixed = True
                        self.use_e(face=True,fixed=fixed)
                        self.stop_move = 1
                        self.mini_state += 2
                        key_mouse_manager.press('w')
                        self.should_update_map = False
                        return
                    else:
                        key_mouse_manager.click(0.5,0.5)
                    if iters + self.quan == 2:
                        key_mouse_manager.press('d',0.85)
                        key_mouse_manager.press('a',0.3)
                self.mini_state+=2
                break
            if not self.is_run():
                key_mouse_manager.keyUp("w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("哪怕是微不足道的注脚，也会在故事里留下自己的印记。")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                self.mini_state+=2
                break
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        self.update_state("check")
        if not self.is_run():
            self.should_update_map = False
            return
        if self.state=="run" and need_confirm:
            CUS_LOGGER.info("哪怕只是徒劳，你们…我们，都有选择的权利。")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                    key_mouse_manager.keyUp(i)
                    key_mouse_manager.wait()
                    key_mouse_manager.press('f')
                    self.get_screen()
                    if self.nof():
                        self.should_update_map = False
                        return
                if self.is_find_end==1 and self.mini_state > 2:
                    if self.move_to_end(mode=0,device=1):
                        key_mouse_manager.press('w')
                        key_mouse_manager.wait()
                elif self.move_direct_to_text():
                    i="w"
                elif self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                    key_mouse_manager.keyUp(i)
                    key_mouse_manager.wait()
                    key_mouse_manager.press('f')
                    self.get_screen()
                    if self.nof():
                        self.should_update_map = False
                        return
                key_mouse_manager.press(i, 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False
    def solve_snack(self):
        if self.check('snack', 0.3844,0.5065, mask='mask_snack',fresh= True):
            key_mouse_manager.click(self.tx,self.ty)
            self.click_position([1184, 815])
        else:
            self.allow_e = 0
        self.click_position([768, 815])
        if self.allow_e:
            key_mouse_manager.press('e')
    def move_direct_to_text(self):
        find=False
        self.moving_direct = True
        for k in [0, 90, 90, 90, 45, -90, -90, -90, -45]:
            pos = get_text_position(self.get_screen())
            if pos:
                CUS_LOGGER.debug(f"距离中心点{960 - pos[0][0]}，进行旋转")
                key_mouse_manager.mouse_move((pos[0][0] - 960) / 16.5)
                find=True
                key_mouse_manager.wait()
                break
            key_mouse_manager.mouse_move(-k)
            key_mouse_manager.wait()
        self.moving_direct = False
        return find
    def use_e(self,face=False,fixed=False):
        if not fixed:
            if self.quan:
                key_mouse_manager.press('e',force= True)
                key_mouse_manager.wait()
            elif self.bai_e:
                CUS_LOGGER.info(f"「{factor}」施放【莫因舍弃而哭泣】")
                if face:
                    key_mouse_manager.press('e',force= True)
                else:
                    key_mouse_manager.press('s')
                    key_mouse_manager.press('e')
                    key_mouse_manager.wait()
                    if self.click_text(text="秘技点不足", box=[895, 1023, 178, 312], click=False, ocr_line=False,
                                       warning=False):
                        key_mouse_manager.press("w")
                        key_mouse_manager.click(0.5, 0.5)
                        key_mouse_manager.wait()
                        CUS_LOGGER.info(f"「{factor}」施放【沉默的悲叹】")
                    else:
                        time.sleep(1.6)
                        key_mouse_manager.press('w')
                        key_mouse_manager.press('e')
            else:
                key_mouse_manager.press('e')
            key_mouse_manager.wait()
            if self.click_text(text="秘技点不足", box=[895, 1023, 178, 312], click=False, ocr_line=False, warning=False):
                key_mouse_manager.click(0.5, 0.5)
                key_mouse_manager.wait()
                CUS_LOGGER.info(f"「{factor}」施放【沉默的悲叹】")
            if self.click_text(text="快速恢复", box=[864, 1058, 224, 318], click=False, ocr_line=False, warning=False):
                self.solve_snack()
                CUS_LOGGER.debug("告诉我…你甘为烈阳……哪怕燃尽…世间万物……")
                key_mouse_manager.wait()
                if self.quan or self.bai_e:
                    key_mouse_manager.press('e')
                    key_mouse_manager.wait()
        else:
            key_mouse_manager.click(0.5, 0.5)
            key_mouse_manager.wait()

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
    def get_path_with_big_map(self,fixed=False):
        """
        np.array颜色为（b,g,r)
        """
        if fixed:
            CUS_LOGGER.info("「汝将肩负骄阳，直至灰白的黎明显著。」")
        else:
            CUS_LOGGER.info("『然而逐火是不断失却的旅途，在那一切当中，生命也当如尘埃般渺小。』")
        self.get_loc(False)
        self.get_screen()
        self.target_loc, self.target_type = self.get_recent_target()
        now_distance = self.update_direction_data()
        if not now_distance:
            CUS_LOGGER.warning("惟有…助长火焰。方能烧熔…那绝望的未来。")
            return
        if not self._stop:
            key_mouse_manager.keyDown("w")
            key_mouse_manager.wait()
        self.is_sprinting = 0
        if self.target_type != 3:
            sprint()
            self.is_sprinting = 1
        if not self.get_loc():
            CUS_LOGGER.warning("金血…出自「毁灭」。我们早已失去…奢求温暖的权利。")
            return False
        # 复杂的定位、寻路过程
        go_direct = 2
        go_time = random.uniform(0.5, 0.75)
        retry_time = 0
        has_not_found_red = False
        skill_num = match_skill_numbers_in_region(self.get_screen())
        if skill_num is not None:
            self.skill_num = skill_num
        if self.skill_num == 0:
            fixed = True
        if not fixed:
            if self.bai_e:
                add_round = 7
            elif self.quan:
                add_round = 4
            else:
                add_round = 0
        else:
            add_round=0
        threshold_distance = [13, 19 + add_round, 11, 7]
        # 基于距离的位置卡住检测
        last_locs = []
        STUCK_DISTANCE_THRESHOLD = 2.0  # 卡住判定的距离阈值
        for i in range(30):
            CUS_LOGGER.debug(f"第{i}次定位寻路")
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                return
            else:
                key_mouse_manager.keyDown("w")
            # 预判实际点位
            if not self.get_loc():
                CUS_LOGGER.warning("它理应照亮众人，照亮前路，照亮翁法罗斯终将到来的黎明……")
                return
            if self.target_type == 1:
                red = [47, 47, 232]
                CUS_LOGGER.info(f"{factor}的前路将是光明，和永恒不熄的烈火。")
                outside = mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True),
                                               center_radius=85)
                rd = np.where(
                    np.sum((outside - red) ** 2, axis=-1) <= self.red_threshold)
                if rd[0].shape[0]:
                    # 就在旁边
                    CUS_LOGGER.info("毁灭的太阳，已然成双……")
                    break
                now_distance = get_dis(self.now_loc, self.target_loc)
                if now_distance < 20:
                    CUS_LOGGER.info("让它点燃你的血液…你的愤怒…！")
                    CUS_LOGGER.debug(f"距离小于20,开始清除{(self.target_loc, 1)}从{self.target}")
                    self.target.remove((self.target_loc, 1))
                    rd = np.where(
                        np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True,
                                            rotation=True) - red) ** 2, axis=-1) <= self.red_threshold)
                    if rd[0].shape[0] > 0:
                        CUS_LOGGER.info("还不够……以此身祭火…燃烧下去…！来…让怒火吞噬…！或成为此世…下一座焦碑…！")
                        # 创建所有检测到的敌人坐标的列表
                        enemy_coords = []
                        for i in range(len(rd[0])):
                            enemy_x, enemy_y = rd[1][i], rd[0][i]
                            new_loc = re_get_position(self.now_loc)
                            world_x = new_loc[0] + (enemy_x - 93)*POSITION_MINIMAP_SCALE
                            world_y = new_loc[1] + (enemy_y - 93)*POSITION_MINIMAP_SCALE
                            new_loc = re_get_position((world_x, world_y), re=True)
                            enemy_coords.append((new_loc, (enemy_x, enemy_y)))

                        # 按距离self.now_loc排序，最近的在前面
                        enemy_coords.sort(key=lambda coord: get_dis(coord[0], self.now_loc))
                        # 选择最近的敌人作为目标
                        nearest_world_coord, nearest_local_coord = enemy_coords[0]
                        recent_loc = tuple(nearest_world_coord)
                        CUS_LOGGER.debug(f"当前目标集合{self.target}")
                        self.target.add((recent_loc, 1))
                        self.target_loc = recent_loc
                        CUS_LOGGER.info(
                            f"{factor}以这力量反抗它的造主，为席卷世间的黑暗，带去无尽的怒火：{recent_loc}，共检测到{len(enemy_coords)}个敌人，按距离排序")
                    else:
                        CUS_LOGGER.info(f"真是如出一辙啊，就像{factor}过去认识的许多个他们……既狡猾…又天真。")
                        if self.debug:
                            self.save_screen(not_now=True,save_path="/temp/no_red2/")
                        has_not_found_red = True
                        # self.target_loc, type = self.get_recent_target()
                    if has_not_found_red:
                        CUS_LOGGER.info("就让天空…熔合此世全部痛苦吧。")
                        break
            else:
                red = [47, 47, 232]
                outside = mask_minimap_outside(get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True),
                                               center_radius=85)
                rd = np.where(
                    np.sum((outside - red) ** 2, axis=-1) <= self.red_threshold)
                if rd[0].shape[0]:
                    # 就在旁边
                    self.red_threshold *= 0.7
                    CUS_LOGGER.debug(f"无妨，就让这轮烈阳……用金色的火焰…填满天空。下次「毁灭」阈值{self.red_threshold}")
                    self.target_type = 1
                    break
            now_distance = get_dis(self.now_loc, self.target_loc)
            CUS_LOGGER.debug(
                f"当前距离目标点{self.target_loc}距离为{now_distance}阈值{threshold_distance[self.target_type]}")
            if now_distance > threshold_distance[self.target_type]:
                CUS_LOGGER.info("我必须出发…必须背负。我必须和你告别，然后…继续以「毁灭」对抗「毁灭」。")
                self.update_direction_data(mode=1)
            else:
                CUS_LOGGER.info(f"{factor}的火焰越燃越旺，{factor}开始变得无比接近…纯粹的愤怒，恨意的化身。")
                if self.target_type == 0:
                    self.target.remove((self.target_loc, self.target_type))
                    CUS_LOGGER.debug("已到达路径点" + str((self.target_loc, self.target_type)))
                    self.last_interact_time = time.time()
                    self.target_loc, self.target_type = self.get_recent_target()
                    if self.target_type == 3:
                        sprint()
                        self.is_sprinting = 0
                    go_direct = 2
                else:
                    key_mouse_manager.keyUp("w")
                    break
            CUS_LOGGER.info(f"但黑潮的阴影依旧笼罩，痛苦和绝望遍布在遥远的大地……(目标距离{now_distance})")
            # 检查是否位置卡住（连续3次距离过小）
            last_locs.append(self.now_loc)
            if len(last_locs) > 3:
                last_locs.pop(0)
            # 判断是否卡住：连续3个位置间距离都小于阈值
            is_stuck = False
            if len(last_locs) == 3:
                dist1 = get_dis(last_locs[0], last_locs[1])
                dist2 = get_dis(last_locs[1], last_locs[2])
                dist3 = get_dis(last_locs[0], last_locs[2])
                is_stuck = (dist1 < STUCK_DISTANCE_THRESHOLD and
                            dist2 < STUCK_DISTANCE_THRESHOLD and
                            dist3 < STUCK_DISTANCE_THRESHOLD)
            # 距离没有更近 或者 位置卡住：开始尝试绕过障碍
            if is_stuck:
                CUS_LOGGER.debug(f"自身坐标{self.now_loc}，目标坐标{self.target_loc}")
                CUS_LOGGER.info(f"昔日的伙伴已尽数成为仇敌。无尽的杀戮令{factor}不知苦痛为何物，沉痛的虚无几乎将{factor}吞噬，逼迫{factor}停止抗争——但{factor}坚持了下来。")
                ts = " da"
                if go_direct > 0:
                    CUS_LOGGER.debug(f"尝试绕过障碍向{ts[go_direct]}")
                    key_mouse_manager.keyUp("w")
                    key_mouse_manager.press("s", 0.35)
                    if go_direct == 2:
                        key_mouse_manager.press(ts[go_direct], go_time)
                    else:
                        key_mouse_manager.press(ts[go_direct], go_time + random.uniform(0, 0.5))
                    key_mouse_manager.keyDown("w")
                    self.get_screen()
                    if not self.get_loc():
                        CUS_LOGGER.info(f"{factor}将侵晨刺入每一尊泰坦的心脏，金血沿指尖淌下，神火灼烧的剧痛几乎令他放弃了挣扎")
                        return
                    # 成功绕过障碍后清空位置记录
                    last_locs.clear()
                    go_direct -= 1
                else:
                    CUS_LOGGER.info("「毁灭」早已汇成烈阳，在这具脆弱的躯壳中翻涌，理智在纪元开端便燃烧殆尽…")
                    key_mouse_manager.keyUp("w")
                    break
            CUS_LOGGER.info(" 若我们生来只是一串模拟生命的数字，那就是我所憧憬的形象，想要成为的样子。")
            retry_time += 1
            key_mouse_manager.wait()
        CUS_LOGGER.info("现在，一轮太阳将走向陨落，它顷刻便能将这荒诞的时空焚烧殆尽——")
        CUS_LOGGER.debug(f"寻路判断已到达交互点附近 {now_distance}")
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("w")
        key_mouse_manager.wait()
        if not self.get_loc():
            CUS_LOGGER.info("「救世主」…我愿你…常战常胜。")
            return
        if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96, fresh=True):
            if self.target_type != 3 and self.good_f()[0] and not self.ts.similar("黑塔"):
                CUS_LOGGER.info(f"{factor}…别无选择。")
                for j in deepcopy(self.target):
                    # 类型为二，交互点
                    if j[1] == 2:
                        self.target.remove(j)
                        CUS_LOGGER.debug("检测到交互点，已移除目标:" + str(j))
                return
        if self.target_type == 1:
            if has_not_found_red:
                self.target.add((self.target_loc, 0))
                self.target_type = 0
                CUS_LOGGER.info(f"为了不让最黑暗的命运降临，{factor}必须如此。")
            CUS_LOGGER.info(f"{factor}将以这数亿颗火种点燃的烈阳，与「毁灭」的神明和祂的走卒，一同燃烧殆尽……")
            local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
            red = [47, 47, 232]
            rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= self.red_threshold)
            if rd[0].shape[0] > 0:
                enemy_coords = []
                for i in range(len(rd[0])):
                    enemy_coords.append((rd[1][i], rd[0][i]))
                # 按距离self.now_loc排序，最近的在前面
                enemy_coords.sort(key=lambda coord: get_dis(coord, (93, 93)))
                # 选择最近的敌人作为目标
                target = (tuple(enemy_coords[0]), 3)
                self.update_direction_data(mode=2, target=target)
            if self.quan:
                key_mouse_manager.keyUp("w")
                skill_num = match_skill_numbers_in_region(self.get_screen())
                if skill_num is not None:
                    self.skill_num = skill_num
                if self.skill_num == 0:
                    fixed = True
                for _ in range(2):
                    self.use_e(fixed=fixed)
                if not self.get_loc():
                    CUS_LOGGER.info("这是神明计算中的时刻。此后的旅途，与您熟知的一切并无区别。有人到来，有人离去，逐火者们身负微光，在长夜中艰难向前。")
                    return
                key_mouse_manager.press('w')
            elif self.bai_e:
                skill_num = match_skill_numbers_in_region(self.get_screen())
                if skill_num is not None:
                    self.skill_num = skill_num
                if self.skill_num == 0:
                    fixed = True
                self.use_e(fixed=fixed)
                if not self.get_loc():
                    CUS_LOGGER.info("切莫……犹疑……PhiLia093在学习……她在利用……你的爱……")
                    return
                key_mouse_manager.press('w')
            else:
                key_mouse_manager.click(0.5, 0.5)
        if self.target_type == 3:
            CUS_LOGGER.info("何不…让愤怒…焚化命运…？卡…厄斯……")
            for i in range(9):
                self.get_screen()
                if not self.is_run():
                    CUS_LOGGER.info("沿着我们的足迹……写下前所未有的结局。")
                    return
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                    CUS_LOGGER.info("那一定是个不同以往的浪漫故事。")
                    key_mouse_manager.press('f', force=True)
                    key_mouse_manager.wait()
                    if self.nof(must_be='tp'):
                        return
                if not self.is_run():
                    return
                if i in [0, 4]:
                    self.move_to_end(mode=1,device=1)
                key_mouse_manager.press('w')
                key_mouse_manager.wait()
        # 离目标点挺近了，准备找下一个目标点
        elif now_distance <= 20:
            CUS_LOGGER.info("你也是这么想的……对吧？")
            try:
                CUS_LOGGER.debug("靠近目标点，尝试移除:" + str((self.target_loc, self.target_type)))
                # 如果是敌人类型，移除后需要重新扫描地图上的红色点位
                if self.target_type == 1:
                    CUS_LOGGER.info("为自己而活，倒也不错...")
                    self.last_interact_time = time.time()
                    self.target.remove((self.target_loc, self.target_type))
                    CUS_LOGGER.debug("靠近目标点，成功移除敌人:" + str((self.target_loc, self.target_type)))

                    # 扫描地图红色点位，尝试添加回检测到的目标点
                    red = [47, 47, 232]
                    rd = np.where(
                        np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True,
                                            rotation=True) - red) ** 2, axis=-1) <= self.red_threshold)
                    if rd[0].shape[0] > 0:
                        CUS_LOGGER.info("他的眼泪还未落下,便蒸发不见。")
                        # 创建所有检测到的敌人坐标的列表
                        enemy_coords = []
                        for i in range(len(rd[0])):
                            enemy_x, enemy_y = rd[1][i], rd[0][i]
                            new_loc = re_get_position(self.now_loc)
                            world_x = new_loc[0] + (enemy_x - 93)*POSITION_MINIMAP_SCALE
                            world_y = new_loc[1] + (enemy_y - 93)*POSITION_MINIMAP_SCALE
                            new_loc = re_get_position((world_x, world_y), re=True)
                            enemy_coords.append((new_loc, (enemy_x, enemy_y)))

                        # 按距离self.now_loc排序，最近的在前面
                        enemy_coords.sort(key=lambda coord: get_dis(coord[0], self.now_loc))
                        # 选择最近的敌人作为新目标
                        nearest_world_coord, nearest_local_coord = enemy_coords[0]
                        recent_loc = tuple(nearest_world_coord)
                        self.target.add((recent_loc, 1))
                        self.target_loc = recent_loc
                        self.target_type = 1
                        CUS_LOGGER.info(
                            f"已添加新的敌人目标: {recent_loc}，共检测到{len(enemy_coords)}个敌人")
                    else:
                        CUS_LOGGER.info("看来，你终究得逞了………刽子手。")
                else:
                    # 非敌人类型，直接移除
                    self.last_interact_time = time.time()
                    self.target.remove((self.target_loc, self.target_type))
                    CUS_LOGGER.debug("靠近目标点，成功移除:" + str((self.target_loc, self.target_type)))
            except Exception:
                pass
        CUS_LOGGER.info("逐火…是不断失却的旅途……失去…还远远不足……")

