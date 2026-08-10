import json
import os
import shutil
import time

import cv2
import numpy as np
import pyautogui
import yaml

from diver import load_actions, merge_text
from route import PATHS
from tool import EXTRA, GLOBAL
from tool.currency.config import config
from tool.currency.text_key import text_keys
from tool.currency.utils import CurrencyUtils, set_forground
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.utils.Error import NormalEndError
from tool.utils.image_tool import find_image_by_name
from tool.utils.tool import get_hwnd_and_text


class SimulatedCurrency(CurrencyUtils):

    def __init__ (self, find, debug, speed, consumable, slow, nums = -1, bonus = False):
        super ().__init__ (speed)
        key_mouse_manager.set_config (config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params (self.x1, self.y1, self.xx, self.yy, self.full)
        #第几次选择策略
        self.select_bless_count = 0
        #停止运行标志
        self._stop = True
        #调试级别
        self.debug = debug
        # 设置全局调试模式标志，供 UILogHandler 使用
        GLOBAL.DEBUG_MODE = bool (self.debug)
        #启动时时间
        self.init_time = time.time ()
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        #当前运行状态
        self.state=None
        #上次执行操作时间
        self.action_time = time.time()
        #事件与行为存储路径
        self.default_json_path = "actions/currencywar.json"
        self.default_json = load_actions(self.default_json_path)
        self.action_history = []
        #策略最大刷新次数
        self.max_refresh = 1
        #运行次数
        self.count = 0
        self.bonus_rounds_remaining = 0  # 剩余奖励轮次数
        self.tk = text_keys ()

        self.ENVIR_BOXES = [[266, 610, 375, 413], [780, 1134, 375, 414], [1314, 1645, 373, 413]]
        self.BLESS_BOXES = [[298, 608, 472, 513], [783, 1095, 472, 513], [1298, 1605, 472, 513]]

        if debug != 2:
            #似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False

        CUS_LOGGER.debug (f"开始运行,初始计数：{self.count}")
        self.last_interact_time = time.time ()

        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                data = json.load(file)

        # 读取货币战争专用配置
        currency_config_file = PATHS["root"] + "\\config\\config\\currency_config.yml"
        currency_example_file = PATHS["root"] + "\\config\\config\\currency_config_example.yml"
        if not os.path.exists(currency_config_file):
            if os.path.exists(currency_example_file):
                shutil.copy2(currency_example_file, currency_config_file)
            else:
                # 如果示例文件也不存在，创建一个默认的
                os.makedirs(os.path.dirname(currency_config_file), exist_ok=True)
                with open(currency_config_file, "w", encoding="utf-8") as f:
                    f.write("# 货币战争模块配置文件\n")
                    f.write("# 在第几面结束后退出（默认第1面）\n")
                    f.write("exit_after_plane: 1\n")

        # 加载配置
        try:
            with open(currency_config_file, encoding="utf-8", errors="ignore") as f:
                currency_config = yaml.safe_load(f) or {}
                self.exit_plane = currency_config.get("exit_after_plane", 1)
                CUS_LOGGER.info(f"货币战争退出位面设置为: 第{self.exit_plane}面")
        except Exception as e:
            CUS_LOGGER.warning(f"读取货币战争配置失败，使用默认退出位面1: {e}")
            self.exit_plane = 1

        self.record = data.get("recording_state", True)

    def recognize_options (self, boxes, redundancy = 30):
        """对多个选项区域进行 OCR 识别，返回文字列表"""
        texts = []
        for box in boxes:
            try:
                res = self.ts.find_with_box (box, redundancy = redundancy, forward = 1)
                merged = merge_text (res)
                texts.append (merged)
            except Exception:
                texts.append ("")
        return texts

    def route (self):
        set_forground ()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text ()
            warn_game = False
            cnt = 0
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                self.last_interact_time = time.time ()
                if self._stop:
                    raise NormalEndError
                if not warn_game:
                    warn_game = True
                    CUS_LOGGER.warning (f"等待游戏窗口，当前窗口：{Text}")
                time.sleep (0.5)
                cnt += 1
                if cnt == 1200:
                    set_forground ()# 将游戏窗口设为前台
                hwnd,Text = get_hwnd_and_text ()
            if self._stop:
                break
            self.loop ()
        CUS_LOGGER.info ("已停止任务")

    def loop (self):
        CUS_LOGGER.info ("开始OCR识别，等待触发文字")
        while not self._stop:
            self.ts.forward (self.get_screen())
            self.run_static ()

    def goto_currency (self):
        """
        前往货币战争
        该函数负责自动导航到货币战争，主要流程包括：
        1. 检查是否已经在货币战争内
        2. 如果不在，通过星际和平指南传送
        """
        self.update_state("init")
        CUS_LOGGER.info("前往货币战争")
        CUS_LOGGER.info("打开")
        key_mouse_manager.press('f4')

    def is_one (self):
        box = [752, 1060, 378, 409]
        try:
            text_list = self.ts.find_with_box (box, forward=1)
            merged = merge_text (text_list)
            CUS_LOGGER.info (f"OCR 识别结果: {merged}")
            return "开局时获得" in merged
        except Exception:
            CUS_LOGGER.info ("正在选择难度1")
            return False

    def select_difficulty_start (self):
        max_attempts = 30
        for _ in range (max_attempts):
            self.get_screen()
            if self.is_one ():
                CUS_LOGGER.info ("已识别到难度1")
                key_mouse_manager.operation_queue.clear()
                key_mouse_manager.click (1692, 965)   # “开始对局”按钮坐标
                self.update_state("startbattle")          # 直接进入战斗状态
                return True
            CUS_LOGGER.info ("等待选择难度1")
            key_mouse_manager.drag (0.4615, 0.2450, 0.4615, 0.9000)
            time.sleep(0.3)   # 等待界面稳定
        CUS_LOGGER.warning ("等待选择难度1")
        return

    def auto_battle(self):
        # 需要打开自动战斗
        key_mouse_manager.press("v")



    def select_envir (self):
        CUS_LOGGER.info ("=== 进入投资环境选择阶段===")
        time.sleep (1)#等待界面加载
        self.ts.forward (self.get_screen ())
        boxes = self.ENVIR_BOXES
        def match_prior (texts):
            for pri in self.tk.prior_envir:
                for idx, text in enumerate (texts):
                    if pri in text:
                        CUS_LOGGER.info (f"匹配到必选策略: {pri}，选择选项{idx+1}")
                        return True, idx
            return False, -1
        texts = self.recognize_options (self.ENVIR_BOXES)
        CUS_LOGGER.info (f"OCR 识别结果: {texts}")
        matched, selected_idx = match_prior (texts)

        if not matched:
            CUS_LOGGER.info ("未匹配到必选策略，点击刷新按钮")
            key_mouse_manager.click (672, 984)  # 刷新按钮坐标
            time.sleep (4)        # 等待刷新完成
            self.ts.forward (self.get_screen ())
            # 刷新后重新识别并再次尝试匹配必选
            texts = self.recognize_options (self.ENVIR_BOXES)
            CUS_LOGGER.info (f"刷新后 OCR 结果: {texts}")
            matched, selected_idx = match_prior (texts)
        #构建完整的优先级列表（按顺序）
        if not matched:
            #    顺序：prior_envir + envir[0] + envir[1] + ... + envir[4]
            prior_list = self.tk.prior_envir[:]  # 复制最高优先级列表
            for i in range(5):  # envir 有5个子列表，索引0~4
                prior_list.extend(self.tk.envir[i])  # 依次追加
            #按优先级匹配选项
            selected_idx = -1  # 初始化为-1，表示未匹配
            for pri in prior_list:
                for idx, text in enumerate(texts):
                    # 判断当前选项文字中是否包含优先级关键词（使用 in 进行子串匹配）
                    if pri in text:
                        selected_idx = idx
                        CUS_LOGGER.info(f"匹配到优先级策略: {pri}，选择选项{idx+1}")
                        break
                if selected_idx != -1:
                    break  # 已匹配到，跳出外层循环
            # 5. 如果都未匹配，默认选中间
            if selected_idx == -1:
                selected_idx = 1
                CUS_LOGGER.warning("未匹配到任何优先级策略，默认选择中间")


        if any("银金彩" in text for text in texts):
            self.max_refresh = 3
            CUS_LOGGER.info("选择银金彩，已将刷新次数调整至3次")
        else:
            self.max_refresh = 1
        # 点击选中的选项（点击其中心位置）
        #    计算每个选项的中心像素坐标
        centers = []
        for box in boxes:
            cx = (box[0] + box[1]) // 2
            cy = (box[2] + box[3]) // 2
            centers.append((cx, cy))

        key_mouse_manager.click (centers[selected_idx][0], centers[selected_idx][1])
        time.sleep (0.1)  # 等待点击生效

        self.click_text (
            text="确认",
            box=[1053, 1108, 967, 998],
            click=True,
        )
        self.select_bless_count = 0
        self.bonus_rounds_remaining = 0
        time.sleep (0.1)
        CUS_LOGGER.info ("投资环境选择完成")
        return 1

    def detect_has_icon(self, roi):
        """
        检测 ROI 中是否有图标（通过图像复杂度判断）
        返回 True：有图标（未解锁），False：无图标（已解锁）
        """
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        std = np.std(gray)
        CUS_LOGGER.debug(f"标准差: {std:.2f}")
        # 有图标时标准差 > 15，纯色背景时标准差 < 8
        # 这个阈值可以调整，你先用 10 测试
        return std > 10, std

    def select_bless (self):
        """选择投资策略：第一次直接选中间，后续匹配必选'环保大使叽米'，否则选中间"""

        CUS_LOGGER.info(f"=== 第 {self.select_bless_count} 次进入 select_bless ===")
        time.sleep (1)
        self.ts.forward (self.get_screen ())
        # 三个选项的 box
        boxes = self.BLESS_BOXES

        centers = []
        for box in boxes:
            cx = (box[0] + box[1]) // 2
            cy = (box[2] + box[3]) // 2
            centers.append((cx, cy))

        if self.select_bless_count < self.exit_plane:

            selected_idx = -1

            for attempt in range (self.max_refresh + 1):  # 0次正常识别 + 最多3次刷新后识别
                self.ts.forward (self.get_screen ())
                # ---- 调试：保存三个选项区域 ----
                debug_dir = os.path.join(os.getcwd(), "temp")
                os.makedirs(debug_dir, exist_ok=True)

                # 三个选项的矩形区域（像素坐标）
                roi_boxes = [
                    [617, 641, 219, 241],
                    [1116, 1141, 219, 241],
                    [1616, 1639, 219, 241]
                ]
                target_centers = []
                for box in roi_boxes:
                    cx = (box[0] + box[1]) / 2 / self.xx
                    cy = (box[2] + box[3]) / 2 / self.yy
                    target_centers.append((cx, cy))

                for idx, box in enumerate(roi_boxes):
                    x1, x2, y1, y2 = box
                    roi = self.screen[y1:y2, x1:x2]

                    texts = self.recognize_options (self.BLESS_BOXES)
                    CUS_LOGGER.info (f"OCR 识别结果: {texts}")

                    # 调用标准差检测
                    has_icon, std = self.detect_has_icon(roi)
                    CUS_LOGGER.info(f"选项{idx+1} 是否有图标: {has_icon} (标准差: {std:.2f})")  # 如果需要打印具体值
                    if has_icon:
                        # 检测到图标 → 未解锁 → 选中它！
                        selected_idx = idx
                        CUS_LOGGER.info(f"第{attempt}次检测到未解锁图标，选中选项{idx+1}")
                        break
                if selected_idx != -1:
                    if "黄金投资" in texts[selected_idx] or "白银投资" in texts[selected_idx]:
                        self.bonus_rounds_remaining = 2  # 赠送 2 次选择
                        CUS_LOGGER.info("检测到特殊投资，设置奖励轮次数: 2")
                    break

                # 如果没找到未解锁的，刷新...
                if attempt < self.max_refresh:
                    CUS_LOGGER.info(f"第 {attempt+1} 次未匹配，点击刷新")
                    key_mouse_manager.click(384, 869)
                    key_mouse_manager.click(868, 869)
                    key_mouse_manager.click(1380, 869)
                    time.sleep(1.5)
                    self.ts.forward(self.get_screen())
                else:
                    # 刷新三次都没找到未解锁的 → 可能全部已解锁，随便选一个
                    CUS_LOGGER.warning("刷新后仍未找到未解锁图标，默认选中间")
                    selected_idx = 1

            # 点击选中的选项


            key_mouse_manager.click (centers[selected_idx][0], centers[selected_idx][1])
            time.sleep (0.1)

            # 点击确认
            self.update_state ("escshop")
            self.click_text (text = "确认", box = [948, 1005, 968, 999], click = True)
            time.sleep (5)
            CUS_LOGGER.info ("投资策略选择完成")
            self.ts.forward (self.get_screen())
        self.select_bless_count += 1
        if self.bonus_rounds_remaining > 0:
            self.select_bless_count -= 1
            self.bonus_rounds_remaining -= 1
            CUS_LOGGER.info(f"抵消一次特殊投资，剩余奖励次数: {self.bonus_rounds_remaining}")


        CUS_LOGGER.info(f"比较: {self.select_bless_count} < {self.exit_plane} ? {self.select_bless_count < self.exit_plane}")

        if self.select_bless_count >= self.exit_plane:
            CUS_LOGGER.info(f"达到退出位面（{self.exit_plane}面），按两次 ESC 退出当前对局，然后重开")
            self.update_state ("escshop")
            key_mouse_manager.press('esc') #关闭商店
            time.sleep(1)
            self.ts.forward (self.get_screen ())

            if self.exit_plane == 1:
                battle_box = [724, 760, 77, 104]
            elif self.exit_plane in (2, 3):
                battle_box = [569, 608, 80, 104]
            else:
                # 默认使用第一个（保险）
                battle_box = [724, 760, 77, 104]

            if self.click_text (text = "战斗", box = battle_box, click = False, allow_fail = True):
                CUS_LOGGER.info ("检测到'战斗'，按 ESC 重开")
                key_mouse_manager.press('esc')
                time.sleep(1)
            else:
                self.update_state ("startbattle")

        self.update_state ("startbattle")
        return 1

    def run_static (self, json_path = None, json_file = None, action_list = []) -> (str, int):
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
                json_file = load_actions (json_path)
        # 查找指定项或者默认项
        tm = time.time ()
        while time.time () - tm < 2:
            men = np.mean (self.get_screen ())
            if men > 12:
                break
            elif self.state != "black":
                CUS_LOGGER.info("无边的黑暗中，没有来由地，一道声音始终在耳边萦绕……")
                self.update_state ("black")
        if np.mean (self.get_screen ()) > 12 and self.state == "black":
            self.update_state (self.last_state)
        for j in action_list if len (action_list) else json_file:
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

    def start (self):
        """
        启动货币战争自动化程序

        该方法负责初始化并启动整个货币战争运行流程，包括：
        1. 初始化运行状态
        2. 启动键盘鼠标管理器
        3. 启动地图显示线程（如果启用）
        4. 开始执行主要路线逻辑

        如果在执行过程中发生异常，会尝试停止运行并重新抛出异常。
        """
        self._stop = False
        key_mouse_manager.start ()
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
        停止任务运行

        该方法负责安全地停止所有运行中的线程和操作，包括：
        1. 设置停止标志
        2. 停止键盘鼠标管理器
        3. 等待并终止地图显示线程

        参数:
            *_: 忽略的位置参数
            **__: 忽略的关键字参数
        """
        CUS_LOGGER.info("终止任务")
        self._stop = 1
        key_mouse_manager.stop()
        self.map_thread = None
