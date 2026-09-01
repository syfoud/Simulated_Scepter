import json
import os
import random
import shutil
import sqlite3
import time

import cv2 as cv
import yaml

from route import PATHS
from simul import SimulatedUniverse
from tool import EXTRA
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER, log_emitter
from tool.public_ocr import load_actions, merge_text
from tool.utils.analysis_map import (
    build_rightward_graph,
    compute_all_max_steps,
    compute_start_point_from_crop,
    detect_corner_markers,
    display_matches,
    evaluate_best_single_replacement,
    match_multiple_targets,
    max_weight_path,
)
from tool.utils.Error import NoBossError, NoMatchError
from tool.utils.image_tool import find_image_by_name
from tool.utils.minimap_util import (
    MINIMAP_RADIUS,
    deal_minimap,
    get_minimap,
    re_get_position,
)
from tool.utils.ocr_num import (
    extract_number,
    match_cheat_count_in_region,
    match_numbers_in_region,
    match_roll_count_in_region,
)
from tool.utils.tool import find_latest_modified_file
from tool.window_recorder import WindowRecorder
import datetime


class IronBloodUniverse(SimulatedUniverse):
    def __init__(
            self):
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                self.opt = json.load(file)
        super().__init__(find=True,speed=False,consumable=False, slow=False,debug=self.opt.get("debug", True), nums=self.opt.get("max_run_time", 0))
        self.plane_floor = -1
        self.need_record = False
        self.record_event_map_enabled = bool(
            self.debug and self.opt.get("record_event_map", False)
        )
        self.record_map_contexts = {}
        for map_kind, directory_name in (
                ("event", "event_nmaps"),
                ("rest", "rest_nmaps"),
                ("trade", "trade_nmaps")):
            map_root = os.path.join(PATHS["image"], directory_name)
            os.makedirs(map_root, exist_ok=True)
            self.record_map_contexts[map_kind] = (
                map_root,
                self._load_map_templates(map_root),
            )
        if self.record_event_map_enabled:
            roots = "、".join(
                context[0] for context in self.record_map_contexts.values()
            )
            CUS_LOGGER.debug(f"特殊地图录图模式已开启，各类地图将分别保存至{roots}")
        self.default_json_path = "actions/insect.json"
        self.default_json = load_actions(self.default_json_path)

        config_file = "config/config/event_info.yml"
        example_file = "config/config/info_example.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)

        with open(config_file, encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["event"]
        self.action_history = []
        self.steps=None
        self.nodes=None
        self.replace_idx=None
        self.next_node = None
        self.max_limited = None
        self.kill_count =0
        self.run_start_time = time.time()
        self.need_end=False
        self.record = self.opt.get("recording_iron_blood", True)
        self.recorder = WindowRecorder('logs/video/', fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=self.opt.get("record_add_label", True), offsets=[10, 50, 10, 10], overlay_map=self.opt.get("record_add_label", True) and self._show_map, simul_instance=self)
        self.early_stop=self.opt.get("early_stop", False)
        self.first_plane_count=self.opt.get("first_plane", 14)
        self.second_plane_count=self.opt.get("second_plane", 31)
        self.first_plane_min_weight=self.opt.get("first_plane_min_weight", 6)
        self.del_record_time=self.opt.get("del_record_time", 31)
        self.max_interact_time=self.opt.get("max_interact_time", 40)
        self.area=""
        self.now_map=-1
        self.new_node = True
        self.node_count=0
        self.fail_match_count = 0
        self.ruanmei2 = False  # 本轮是否遭遇过「阮·梅（其二）」
        self.special_interaction_failures = {}
        self.native_special_map_root = None
        self.loaded_map_root = None
        CUS_LOGGER.info("宇宙的中心有一团火种,它愈烧愈旺,直至燃尽整片星河。")

    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            need_del=self.del_record_time and self.del_record_time>self.kill_count
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.kill_count}")
            self.recorder.stop_recording(need_del)
            time.sleep(0.8)
            self.recorder.start_recording(self.count + 1)
            self.update_state("re_start")
        self.kill_count = 0
        self.fail_match_count=0
        self.node_count=0
    def end_of_university(self):
        super().end_of_university()
        elapsed = int(time.time() - self.run_start_time)
        record_file = "config/backup/kill_record.txt"
        try:
            if self.plane_floor==3:
                self.kill_count+=1
            os.makedirs("config/backup", exist_ok=True)
            with open(record_file, "a", encoding="utf-8") as file:
                now_lunhuirizhi = datetime.datetime.now()
                timestamp_lunhuirizhi = now_lunhuirizhi.strftime("%Y年%m月%d日%H点%M分%S秒")
                file.write(f"{timestamp_lunhuirizhi}, 轮回次数:{self.count}, 击杀数:{self.kill_count}, 用时:{elapsed // 60}分{elapsed % 60}秒\n")
                # file.write(f"轮回次数:{self.count}, 击杀数:{self.kill_count:02d}, 用时:{elapsed // 60}分{elapsed % 60}秒\n")
        except Exception as e:
            CUS_LOGGER.error(f"写入击杀记录文件失败{e}")
        self.run_start_time = time.time()  # 开始下一局计时
        self.need_end=False
        self.init_map()
        if self.kill_count>=40:
            if self.count>10000:
                CUS_LOGGER.info("寰宇或为您的意志撼动，但「毁灭」的道路，注定无法手捧鲜花……")
            elif self.count>1000:
                CUS_LOGGER.info("…不必考量本心，不必渴求胜利，只须知道，铁血战士——让人感到愤怒！")
            elif self.count>100:
                CUS_LOGGER.info("无所谓，旅途本就会改变一个人。")
            self.stop()
            CUS_LOGGER.info("恭喜，您获得了铁血战士！")
        else:
            CUS_LOGGER.info(f'{factor}再度踏上轮回……')


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
                    lines = fh.readlines()
                    if lines:
                        try:
                            new_cnt = int(lines[0].strip())
                        except Exception:
                            pass
            else:
                os.makedirs("config/backup", exist_ok=True)
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write("0\n0\n")
            self.count = new_cnt
        else:
            new_cnt = self.count + 1
            lines = ["0\n", "0\n"]
            if os.path.exists(file_name):
                with open(file_name, encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                    if len(lines) < 2:
                        lines += ["0\n"] * (2 - len(lines))
            lines[0] = str(new_cnt) + "\n"
            try:
                with open(file_name, "w", encoding="utf-8") as file:
                    file.writelines(lines)
                self.count = new_cnt
            except Exception as e:
                CUS_LOGGER.error(f"写入铁血计数失败 {e}")
    def normal(self):
        bk_lst_changed = self.last_interact_time
        self.last_interact_time = time.time()
        self.ts.forward(self.get_screen())
        res,state = self.run_static()
        if self.state=="run":
            CUS_LOGGER.info("那朵微弱的火苗，启程之初便已种进他的心里。")
            #检查黄泉
            if not self.quan and self.check("huangquan", 0.0578,0.7083):
                key_mouse_manager.press("1")
                self.quan = 1
            if not self.bai_e and self.check("bai_e", 0.0625,0.7092):
                key_mouse_manager.press("1")
                self.bai_e = 1
            # 当前节点为祝福猪节点时切2号位并重置黄泉/白厄状态
            start_node = getattr(self, 'start_nodes', None)
            if start_node is not None:
                cm = (start_node.get('orig') or {}).get('corner_marker')
                if cm and cm.get('name') in ('pig1', 'pig2'):
                    CUS_LOGGER.info("梦中那刺骨的愤怒与对自我的憎恨仍在震动着他的心。")
                    key_mouse_manager.press("2")
                    self.quan = 0
                    self.bai_e = 0
            #上次交互时间
            self.last_interact_time = bk_lst_changed
            # 刚进图，初始化一些数据
            if not self.need_end:
                ocr_text = self.ts.find_with_box(box=[55, 164, 12, 40],forward=True,re_screen=False)
                self.area=merge_text(ocr_text) if len(ocr_text) else ""
                CUS_LOGGER.debug(f"当前区域{self.area}")
                battle_map_root = os.path.join(PATHS["image"], "nmaps")
                if (("战斗" in self.area or "精英" in self.area or "首领" in self.area)
                        and self.loaded_map_root not in (None, battle_map_root)):
                    self.init_map()
                if "战斗" in self.area:
                    if not self.big_map_init:
                        key_mouse_manager.clean()
                        key_mouse_manager.keyUp("w")
                        key_mouse_manager.wait()
                        if self._stop:
                            return 1
                        self.find,self.need_record,state=self.map_data_load()
                        CUS_LOGGER.info(f"{factor}将燃烧…会燃尽。成为这一世的盗火行者。杀死神明和伙伴，夺走火种。")
                        if self._stop or not state:
                            return 1
                    if self.need_record:
                        self.recording_map()
                    elif self.find:
                        # 有先验寻路
                        self.get_path_with_big_map()
                    else:
                        # 无先验寻路
                        self.get_path_only_minimap()
                elif "精英" in self.area or "首领" in self.area:
                    if not self.big_map_init:
                        key_mouse_manager.clean()
                        key_mouse_manager.keyUp("w")
                        key_mouse_manager.wait()
                        if self._stop:
                            return 1
                        self.find, self.need_record,state = self.map_data_load()
                        CUS_LOGGER.info("面对「纷争」的半神……你绝无可能以和平的姿态取走这枚火种。")
                        if self._stop or not state:
                            return 1
                    if self.need_record:
                        self.recording_map()
                    elif self.find:
                        # 有先验寻路
                        self.get_path_with_big_map(True)
                    else:
                        # 无先验寻路
                        self.get_path_only_minimap(True)
                elif "事件" in self.area or "奖励" in self.area:
                    if self.record_special_map_or_navigate(self.get_event_only_minimap):
                        return 1
                elif "休整" in self.area:
                    if self.record_special_map_or_navigate(self.get_rest_only_minimap):
                        return 1
                elif "交易" in self.area:
                    if self.record_special_map_or_navigate(self.get_shop_only_minimap):
                        return 1
                elif "冒险" in self.area:
                    # if not self.big_map_init:
                    #     self.map_data_load()
                    # self.recording_map()
                    self.get_adventure()
                else:
                    #背景有光污染，字都认不出来
                    key_mouse_manager.mouse_move(1)
                    key_mouse_manager.wait()
            # 长时间未交互/战斗，暂离或重开
            if ((time.time() - self.last_interact_time >= self.max_interact_time) and not self.need_record )or self.need_end:
                key_mouse_manager.clean()
                key_mouse_manager.wait()
                key_mouse_manager.keyUp("w")
                key_mouse_manager.press("esc")
                key_mouse_manager.wait()
                tm=time.time()
                found=False
                #esc有时不一定生效，比如释放秘技时
                while time.time()-tm<3:
                    if self.click_text(text="暂离", box=[1321, 1383, 787, 821],click=False,allow_fail=True):
                        found=True
                        break
                if not found:
                    return 1
                self.update_state("ui")
                self.init_map()
                self.floor_init = 0
                if self.need_end:
                    self.update_state("exit")
                    CUS_LOGGER.info(f"{factor}将跨越旧世界的余烬，不断燃烧……(本轮击杀数:{self.kill_count})")
                    return 1
                elif self.fail_count <= 1:
                    CUS_LOGGER.error(f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，尝试暂离")
                    CUS_LOGGER.info(f"纵使神火已经如此炽烈，以至于…每次回归起点的瞬间，它便会顷刻将{factor}烧尽…… ")
                    self.fail_count += 1
                else:
                    CUS_LOGGER.error(f"地图{self.now_map}多次未发现目标,相似度{self.now_map_sim},尝试退出重进")
                    CUS_LOGGER.info(f"但，所有人的的愿望…引领{factor}抵达轮回尽头")
                    if self.debug == 0:
                        self.fail_count = 0
                self.last_interact_time = time.time()
                return 1
            return 2
        key_mouse_manager.wait()
        if res != '':
            return state
        else:
            return 0
    def get_record_map_context(self):
        """根据当前区域返回其专属录图目录和地图模板集合。"""
        if "事件" in self.area or "奖励" in self.area:
            map_kind = "event"
        elif "休整" in self.area:
            map_kind = "rest"
        elif "交易" in self.area:
            map_kind = "trade"
        else:
            return None
        return self.record_map_contexts.get(map_kind)

    def record_special_map_or_navigate(self, navigate):
        """优先使用已标注特殊地图；录图开关仅控制未知地图的录制。"""
        context = self.get_record_map_context()
        map_root, image_maps = context
        if self.native_special_map_root == map_root:
            navigate()
            return False
        if self.big_map_init and self.loaded_map_root != map_root:
            super().init_map()
            self.loaded_map_root = None
        if not self.big_map_init:
            key_mouse_manager.clean()
            key_mouse_manager.keyUp("w")
            key_mouse_manager.wait()
            if self._stop:
                return True
            # 每张特殊地图独立计算裁剪范围并保存初始小地图。
            self.cut_pos = None
            self.first_save_map = True
            self.find, self.need_record, state = self.map_data_load(
                create=self.record_event_map_enabled,
                map_root=map_root,
                image_maps=image_maps,
                target_mode="special",
            )
            if self._stop or not state:
                return True
        if not self.need_record and (not self.find or not self.target):
            # 特殊地图匹配会写入 big_map_init 等共用地图状态。确认本房间
            # 无可用录图后恢复原生入口，并在换房间前不再重复特殊匹配。
            super().init_map()
            self.loaded_map_root = None
            self.native_special_map_root = map_root
            CUS_LOGGER.warning("当前房间无可用特殊地图，恢复原生寻路状态")
            navigate()
            return False
        if self.need_record:
            self.recording_map()
        else:
            self.navigate_recorded_special_map(navigate)
        return False

    def navigate_recorded_special_map(self, fallback):
        """追踪已标注的特殊地图目标，并在到达交互点后执行交互。"""
        interaction_targets = {target for target in self.target if target[1] == 2}
        CUS_LOGGER.info(f"已匹配特殊地图{self.now_map}，开始追踪地图目标")
        self.trust_annotated_attack_targets = True
        try:
            self.get_path_with_big_map()
        finally:
            self.trust_annotated_attack_targets = False
        if self._stop:
            return

        # 一轮大图寻路也可能只抵达蓝色路径点；仅当本轮目标确实是
        # 交互点时才尝试按 F，避免误触附近的终点或其它装置。
        current_interactions = self._current_interaction_group(
            interaction_targets, self.target_loc
        )
        retry_key = None
        if current_interactions:
            retry_target = min(current_interactions, key=lambda target: target[0])
            retry_key = (
                str(self.now_map),
                round(float(retry_target[0][0])),
                round(float(retry_target[0][1])),
            )
        if self.target_type == 2 and self.do_interaction():
            self.last_interact_time = time.time()
            for target in current_interactions:
                self.target.discard(target)
            self.special_interaction_failures.pop(retry_key, None)
            # 原生大图寻路会一次移除全部类型 2；恢复其它人工交互点。
            self.target.update(interaction_targets - current_interactions)
            CUS_LOGGER.info("已到达地图交互点并完成交互")
            return

        if self.target_type == 2 and current_interactions:
            failures = self.special_interaction_failures.get(retry_key, 0) + 1
            self.special_interaction_failures[retry_key] = failures
            if failures >= 3:
                for target in current_interactions:
                    self.target.discard(target)
                self.special_interaction_failures.pop(retry_key, None)
                remaining = interaction_targets - current_interactions
                self.target.update(remaining)
                CUS_LOGGER.warning(
                    f"地图交互点连续失败{failures}轮，移除当前点并尝试重新识别"
                )
                if not remaining:
                    fallback()
                return

        # 大地图寻路会在足够接近时移除目标。未达到失败上限时恢复
        # 目标供下一轮继续定位；蓝色路径点或红色攻击点不计入失败。
        self.target.update(interaction_targets)
        if interaction_targets:
            CUS_LOGGER.debug("尚未触发有效交互，保留地图交互点等待重试")
        else:
            CUS_LOGGER.debug("地图交互点已处理，继续追踪剩余地图目标")

    @staticmethod
    def _current_interaction_group(targets, target_loc):
        """合并 JPEG 造成的 8 像素内重复点，只处理当前交互位置。"""
        if not targets or target_loc is None:
            return set()
        current = min(
            targets,
            key=lambda target: (
                (target[0][0] - target_loc[0]) ** 2
                + (target[0][1] - target_loc[1]) ** 2
            ),
        )
        return {
            target for target in targets
            if ((target[0][0] - current[0][0]) ** 2
                + (target[0][1] - current[0][1]) ** 2) <= 64
        }

    @staticmethod
    def _load_map_templates(map_root):
        """加载某一类地图的初始小地图，不与其它地图集合混用。"""
        templates = {}
        if not os.path.isdir(map_root):
            return templates
        for map_name in os.listdir(map_root):
            init_path = os.path.join(map_root, map_name, "init.jpg")
            if not os.path.isfile(init_path):
                continue
            image = cv.imread(init_path)
            if image is None:
                continue
            image = deal_minimap(image, is_minimap=True)
            templates[map_name] = cv.resize(
                image, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC
            )
        return templates

    @staticmethod
    def _match_map_templates(img, templates):
        """在指定地图集合中匹配，确保事件地图不会匹配到战斗地图。"""
        local = deal_minimap(img, is_minimap=True)
        local = cv.resize(
            local, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC
        )
        max_sim = -1
        matched_map = -1
        for map_name, search_image in templates.items():
            if (search_image.shape[0] < local.shape[0]
                    or search_image.shape[1] < local.shape[1]):
                continue
            result = cv.matchTemplate(search_image, local, cv.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv.minMaxLoc(result)
            if similarity > max_sim:
                max_sim = similarity
                matched_map = map_name
        return matched_map, max_sim

    @staticmethod
    def _new_map_directory(map_root):
        """建立不重名的待完善地图目录，并返回带分隔符的路径。"""
        while True:
            map_name = "my_" + str(random.randint(0, 99999))
            map_file = os.path.join(map_root, map_name)
            try:
                os.makedirs(map_file)
                return map_name, map_file + os.sep
            except FileExistsError:
                continue

    def map_data_load(
            self, create=False, map_root=None, image_maps=None,
            target_mode="battle"):
        create = self.debug and create
        if map_root is None:
            context = None
            if getattr(self, "record_event_map_enabled", False):
                context = self.get_record_map_context()
            if context is None:
                map_root = os.path.join(PATHS["image"], "nmaps")
            else:
                map_root, context_images = context
                if image_maps is None:
                    image_maps = context_images
        image_maps = self.img_map if image_maps is None else image_maps
        self.loaded_map_root = map_root
        self.big_map_init = True
        # 寻路模式，匹配最接近的地图
        self.stop_move = False
        find = True
        record=False
        #参考线太少毫无定位价值，则直接采用无地图寻路
        if self.get_blank_state(save_debug_dir=os.path.join(PATHS["root"], "temp", "blank_state"))>250:
            tm=time.time()
            max_map,max_sim=-1,-1
            while time.time()-tm<2:
                self.now_map, self.now_map_sim = self._match_map_templates(
                    get_minimap(self.get_screen(), radius=MINIMAP_RADIUS, copy=True),
                    image_maps,
                )
                if self.now_map_sim>max_sim:
                    max_map=self.now_map
                    max_sim=self.now_map_sim
                if self.now_map_sim > 0.7:
                    break
            self.now_map,self.now_map_sim=max_map,max_sim
            if self.click_text(text="确认",box=[1361, 1417, 713, 744],click=False,allow_fail=True):
                self.big_map_init = False
                key_mouse_manager.wait()
                time.sleep(3)
                return find,record,False
            CUS_LOGGER.debug(f"地图编号：{self.now_map}  相似度：{self.now_map_sim}")
            if (self.debug and self.now_map_sim < 0.4) or self.now_map_sim < 0.35:
                CUS_LOGGER.warning(f"相似度过低,疑似未找到匹配地图,匹配地图{self.now_map}")
                if create:
                    self.now_map, self.map_file = self._new_map_directory(map_root)
                find = False
                if self.debug and create:
                    record=True
            elif self.now_map !=-1 and "m" in str(self.now_map):
                CUS_LOGGER.warning(f"未完成的地图{self.now_map}")
                self.map_file = os.path.join(map_root, str(self.now_map)) + os.sep
                record = True
            if find:
                files,x,y,map_num,self.upx,self.upy,target_path = find_latest_modified_file(
                    os.path.join(map_root, str(self.now_map)).replace("\\", "/") + "/"
                )
                self.big_map = cv.imread(files, cv.IMREAD_GRAYSCALE)
                self.debug_map =None
                self.now_loc = (x, y)
                self.start_pos =(x, y)
                self.pos_predictor.position=self.now_loc
                self.pos_predictor.set_now_map(map_num)
                self.target = set()
                self.pos_map = None
                if target_path is not None:
                    self.target = self.get_target(
                        target_path, self.upx, self.upy,
                        target_mode=target_mode,
                    )
                    self.pos_map=cv.imread(target_path)
                    CUS_LOGGER.debug(f"已从地图获取目标路径点{self.target}")
                self.rotation, d = self.pos_predictor.update_minimap_data(self.screen)
            elif (not find) and self.first_save_map and create:
                # 录制模式，保存初始小地图
                self.first_save_map=False
                CUS_LOGGER.warning("未找到匹配地图")
                initial_map = get_minimap(
                    self.screen, radius=MINIMAP_RADIUS, copy=True
                )
                cv.imwrite(self.map_file + "init.jpg", initial_map)
                # 立即加入当前独立集合，避免同一次运行中重复创建同一地图。
                template = deal_minimap(initial_map, is_minimap=True)
                image_maps[str(self.now_map)] = cv.resize(
                    template, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC
                )
                self.best_match=self.pos_predictor.match_multiple_maps(self.screen,0)
                self.start_pos=self.best_match['position']
            if record:
                key_mouse_manager.press("s")
                key_mouse_manager.wait()
                key_mouse_manager.keyDown("w")
        else:
            if self.click_text(text="确认",box=[1361, 1417, 713, 744],click=False,allow_fail=True):
                self.big_map_init = False
                key_mouse_manager.wait()
                time.sleep(3)
                return find,record,False
            find = False
            self.mini_state = 1
            CUS_LOGGER.warning("非常规地图，将进行无地图寻路")
        return find,record,True
    def recording_map(self):
        CUS_LOGGER.info("无名的英雄█████，容纳「负世」火种的黄金裔，正在铭记全世的理想……(开始记录地图)")
        self.get_loc(False)
        # 录图模式，将对应编号大地图裁剪成指定大小小地图
        CUS_LOGGER.info("男人无法流泪，只能凭着心中的剧痛，将回忆刻入脑海。")
        self.cut_map(re_get_position(self.now_loc,need_int=False), self.pos_predictor.assets_floor_feat)
        CUS_LOGGER.info("他相信，终有一日，曙光会穿透翁法罗斯的长夜。")
        self.write_map(self.pos_predictor.assets_floor_feat, self.pos_predictor.map_num)

    def begin_universe(self):
        con = self.click_text(text="继续进度",box=[1610, 1762, 937, 1023],click=False,ocr_line=False,warning=False)
        if not con:
            #点击最低难度
            key_mouse_manager.click(0.9375, 0.8565)
        key_mouse_manager.click(0.1083, 0.1009)
        if con:
            CUS_LOGGER.info("继续，燃烧下去。只要我们不曾熄灭……逐火就不会终结…")
            return
        else:
            self.update_floor(1)
    def select_fate(self):
        self.click_text(text="毁灭",box=[1263, 1317, 791, 821])
    def select_head(self):
        self.click_text(text="击败该首领",box=[1108, 1385, 267, 290])
        self.click_text(text="确认选择",box=[1633, 1733, 961, 990])
    def try_analysis_map(self,mode=1):
        image = self.screen
        matches = match_multiple_targets(image, mode)
        CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
        if len(matches)==0:
            self.click_text(text="点击空白处关闭", box=[875, 1047, 776, 807])
            CUS_LOGGER.warning("未匹配到任何地图图标却错误进入寻路阶段，可能是误识别")
            CUS_LOGGER.warning("刷新截图缓冲区后最后一次尝试匹配地图图标")
            matches = match_multiple_targets(image, mode)
            CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
            if len(matches) == 0:
                self.save_screen(not_now=True, save_path="/temp/bigmaperror/")
                self.save_screen(save_path="/temp/bigmaperror/")
                raise NoMatchError
        # 检测角标（pig/reinforce/alienation等），关联到最近节点
        corner_results = detect_corner_markers(image, matches)
        if corner_results:
            CUS_LOGGER.debug(f'检测到 {len(corner_results)} 个角标')
            for cr in corner_results:
                CUS_LOGGER.debug(f"  {cr['name']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']}({matches[cr['node_idx']]['name']}) dist={cr['node_dist']}")
        if mode==2:
            start=compute_start_point_from_crop(image)
            if start is None:
                start = compute_start_point_from_crop(image,th=0.7)
        elif mode==3:
            start = compute_start_point_from_crop(image,mode=mode)
            if start is None:
                start = compute_start_point_from_crop(image, mode,th=0.7)
        else:
            start=None
        CUS_LOGGER.debug(f"当前起点坐标{start}")
        for i, m in enumerate(matches):
            cm = m.get('corner_marker', None)
            cm_str = f' [角标:{cm["name"]}]' if cm else ''
            CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}{cm_str}")
        boss_head_x = [m['location'][0] for m in matches if m['name'] in ('boss', 'head')]
        if boss_head_x:
            rightmost = max(boss_head_x)
            matches = [m for m in matches if m['location'][0] <= rightmost]
            CUS_LOGGER.debug(f"过滤boss/head右侧节点后，剩余 {len(matches)} 个匹配")
            for i, m in enumerate(matches):
                CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}")
        else:
            raise NoBossError
        if mode == 3:
            self.nodes, self.edges, start_idx = build_rightward_graph(
                matches, start=start,
                max_gap=110, max_overlap=50, max_dy=130
            )
        else:
            self.nodes, self.edges, start_idx = build_rightward_graph(
                matches, start=start
            )
        CUS_LOGGER.debug('构建图后的节点 (索引，类型，相似度，中心 x, 中心 y):')
        for n in self.nodes:
            CUS_LOGGER.debug(f"  {n['idx']}: {n['name']} sim={n.get('similarity', 0):.3f} center=({n['cx']:.1f},{n['cy']:.1f})")
        path, self.expectation_weight, end_idx = max_weight_path(self.nodes, self.edges, start_idx)
        if not path:
            CUS_LOGGER.error("未找到有效路径，可能是起点位于最右端或图构建失败")
            self.fail_match_count += 1
            if self.fail_match_count>=5:
                raise NoMatchError
            else:
                time.sleep(1)
                return
        self.start_nodes=path[0]
        self.path = path
        if path:
            weight_ranges = {
                'event': (0, 1), 'wait': (0, 0), 'trade': (0, 0), 'trade2': (0, 0), 'adventure': (0, 0),
                'reward': (0, 1),'reward2': (0, 1), 'battle': (1, 3), 'elite': (1, 1), 'bugevent': (0, 1),
                'bugbattle': (1, 1), 'head': (1, 1), 'boss': (1, 1), 'blank': (0, 0)
            }
            if len(path)>1:
                self.next_node=path[1]
            CUS_LOGGER.debug(f'路径理论期望值：{self.expectation_weight:.3f}')
            CUS_LOGGER.debug(f"路径理论最小值：{sum(weight_ranges.get(n['name'], (0, 0))[0] for n in path)}")
            CUS_LOGGER.debug(f"路径理论最大值：{sum(weight_ranges.get(n['name'], (0, 0))[1] for n in path)}")
            self.max_limited=0
            self.max_change_count=0
            for i,n in enumerate(path):
                #下一个注定无法改变
                if i==1:
                    self.max_limited +=weight_ranges.get(n['name'], (0, 0))[1]
                else:
                    if n['name']!='battle' and n['name']!='start' and n['name']!='boss' and n['name']!='head' :
                        self.max_change_count+=1
                    if n['name']!='start'and n['name']!='boss' and n['name']!='head':
                        self.max_limited+=3
                    elif n['name']=='head' or n['name']=='boss':
                        self.max_limited+=1
            CUS_LOGGER.debug(f'路径极限最大值：{self.max_limited}')
            # 评估最佳单节点替换
        best_path, best_weight, best_end_idx, self.replace_idx, delta, discounted_delta = evaluate_best_single_replacement(
            self.nodes, self.edges, start_idx, t=0.3 if self.plane_floor == 3 else 0.2)
        self.steps = compute_all_max_steps(self.nodes, self.edges, start_idx)
        if self.debug:
            if self.replace_idx is None or discounted_delta <= 0:
                CUS_LOGGER.info('\n替换评估：未找到有益的单节点替换')
                highlight = None
                alt_path = None
            else:
                b = self.replace_idx
                k = self.steps.get(b, -1)
                CUS_LOGGER.debug(f"\n最佳单节点替换：索引={b}, 名称={self.nodes[b]['name']}")
                CUS_LOGGER.debug(
                    f'  原类型权重 -> 新类型权重：{self.nodes[b]["weight"]:.3f} -> {delta + self.nodes[b]["weight"]:.3f} (+{delta:.3f})')
                CUS_LOGGER.debug(f'  距离起点的最长步数 k={k}')
                CUS_LOGGER.debug(f'  原始增量 delta={delta:.3f}')
                CUS_LOGGER.debug(f'  期权调整后增量 (1-0.2)^{k} × {delta:.3f} = {discounted_delta:.3f}')
                CUS_LOGGER.debug(f'替换后路径总权重：{best_weight:.3f} (原权重：{self.expectation_weight:.3f})')
                highlight = b
                alt_path = best_path
                baseline_ids = [n["idx"] for n in path]
                new_ids = [n["idx"] for n in best_path]
                if baseline_ids == new_ids:
                    CUS_LOGGER.debug('提示：新旧路径节点相同')
                    CUS_LOGGER.debug(f'  被替换节点：{b}({self.nodes[b]["name"]})')
                else:
                    CUS_LOGGER.debug(f'Baseline 路径：{baseline_ids}')
                    CUS_LOGGER.debug(f'New 路径：{new_ids}')
                    CUS_LOGGER.info('改变更优路径！')
                # 计算并打印原路径的理论范围
                weight_ranges = {
                    'event': (0, 1), 'wait': (0, 0), 'trade': (0, 0), 'trade2': (0, 0), 'adventure': (0, 0),
                    'reward': (0, 1),'reward2': (0, 1), 'battle': (1, 3), 'elite': (1, 1), 'bugevent': (0, 1),
                    'bugbattle': (1, 1), 'head': (1, 1), 'boss': (1, 1), 'blank': (0, 0)
                }
                orig_min = sum(weight_ranges.get(n['name'], (0, 0))[0] for n in path)
                orig_max = sum(weight_ranges.get(n['name'], (0, 0))[1] for n in path)
                CUS_LOGGER.debug(f'\n原路径理论期望值：{self.expectation_weight:.3f} (min={orig_min}, max={orig_max})')
                if baseline_ids == new_ids and b is not None:
                    if next((node for node in self.nodes if node['idx'] == b), None):
                        # 获取目标类型的权重范围
                        target_range = (1, 3)
                        old_range = weight_ranges.get(self.nodes[b]['name'], (0, 0))
                        orig_min = orig_min - old_range[0] + target_range[0]
                        orig_max = orig_max - old_range[1] + target_range[1]
                else:
                    # 路径节点发生变化，直接计算新路径的范围
                    orig_min = sum(weight_ranges.get(n['name'], (0, 0))[0] for n in best_path)
                    orig_max = sum(weight_ranges.get(n['name'], (0, 0))[1] for n in best_path)

                CUS_LOGGER.debug(f'新路径理论期望值：{best_weight:.3f} (min={orig_min}, max={orig_max})')
            display_matches(image, matches, path=path, highlight_idx=highlight, save_path=False,
                         font_size_override=14, alt_path=alt_path)
    def initing_map(self):
        key_mouse_manager.keyUp("w")
        if self.click_text(text="振翅",box=[10, 220, 0, 112],click=False,warning=False):
            self.plane_floor=1
        elif self.click_text(text="浪潮",box=[10, 220, 0, 112],click=False,warning=False):
            self.plane_floor=2
        elif self.click_text(text="消褪",box=[10, 220, 0, 112],click=False,warning=False):
            self.plane_floor=3
        else:
            CUS_LOGGER.warning("多么绝妙的巧合。你我都心知肚明。")
            return
        self.try_analysis_map(1)
        if self.early_stop and self.gwypzmgzcndqlp:
            CUS_LOGGER.debug(f"当前一面最低期望{self.first_plane_min_weight}，识别到开局期望{self.expectation_weight}")
            if self.plane_floor==1 and self.expectation_weight < self.first_plane_min_weight:
                CUS_LOGGER.warning("如果不能将此世从「毁灭」中拯救它，那就让寰宇在愤怒中燃烧吧......")
                self.need_end=True
        #self.save_screen(save_path=f"/temp/map{self.plane_floor}/")
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
            self.node_count=0
        key_mouse_manager.wait()
        return
    def initing_map2(self):
        key_mouse_manager.keyUp("w")
        if self.click_text(text="振翅",box=[385, 449, 548, 583],click=False,warning=False):
            self.plane_floor=1
        elif self.click_text(text="浪潮",box=[385, 449, 548, 583],click=False,warning=False):
            self.plane_floor=2
        elif self.click_text(text="消褪",box=[385, 449, 548, 583],click=False,warning=False):
            self.plane_floor=3
        else:
            CUS_LOGGER.warning("以神礼观众之名，我见到————「毁灭」，于斯合题！")
            return
        CUS_LOGGER.debug(f"当前地图位面{self.plane_floor}")
        self.try_analysis_map(3)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        return
    def select_strange(self):
        img = self.get_small_interaction_img(x=0.5000, y=0.7333, mask="mask_strange", fresh=True)
        res = self.ts.split_strange(img)
        if len(res[0])==0:
            CUS_LOGGER.warning("那黄金的血液,救世的希望,原来......")
            return
        value =-1
        strange_index = -1
        black_index_list = []
        black_first=-1
        for i, strange in enumerate(res[1]):
            if '胡须火药' in strange or '纯美骑士' in strange:
                strange_index = i
                break
            elif '三八面' in strange or '银河大乐透' in strange:
                if value<2:
                    strange_index=i
                    value=2
            elif '普通八卦' in strange or '万识囊' in strange or '混沌特效' in strange or '羊皮卷' in strange:
                if value < 1:
                    strange_index = i
                    value = 1
            elif '分裂咕咕钟' in strange or '血锦之纪' in strange or '星际大乐透' in strange or '机械齿轮' in strange:
                black_index_list.append(i)
                if '机械齿轮' in strange:
                    black_first=i
                elif '星际大乐透' in strange and black_first==-1:
                    black_first = i
        if strange_index!=-1:
            CUS_LOGGER.debug(f"优先选择第{strange_index}个奇物")
            key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0][strange_index]))
            key_mouse_manager.click(0.1365, 0.1093)
            key_mouse_manager.wait()
        else:
            can_use_list=[i for i in range(len(res[0])) if i not in black_index_list]
            if len(can_use_list)>0:
                CUS_LOGGER.debug(f"任意选择第{can_use_list[0]}个奇物")
                key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0][can_use_list[0]]))
                key_mouse_manager.click(0.1365, 0.1093)
                key_mouse_manager.wait()
            else:
                CUS_LOGGER.warning(f"极差情况，选择第{black_first}个奇物,齿轮或大乐透")
                key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0][black_first]))
                key_mouse_manager.click(0.1365, 0.1093)
                key_mouse_manager.wait()
    def cheat(self):
        key_mouse_manager.drag(0.5,0.4,0.5,0.8)
        key_mouse_manager.click(571,622)
        self.click_text("确认",box=[1168, 1223, 811, 841],allow_fail=True)
    def select_doing(self):
        text = self.ts.find_with_box(box=[557, 747, 447, 474], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"当前效果{text}")
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996], click=False, allow_fail=True):
            CUS_LOGGER.info("是带着无法被改变的过往，背负它走向未来的决心。")
            return
        if "肉体" in text:
            try:
                self.try_analysis_map(mode=2)
            except NoMatchError:
                return
            except NoBossError:
                return
            if self.replace_idx is not None:
                x,y=int(self.nodes[self.replace_idx]["cx"]),int(self.nodes[self.replace_idx]["cy"])
                key_mouse_manager.click(x,y)
                key_mouse_manager.wait()
                self.click_text(text="确认目标", box=[1635, 1735, 968, 996])
            else:
                CUS_LOGGER.info("所以你才变成了这副模样：残缺的神像…悲哀的薪柴。")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
        elif "战争" in text:
            try:
                self.try_analysis_map(mode=2)
            except NoMatchError:
                return
            except NoBossError:
                return
            path_ids = {n['idx'] for n in self.path}
            start_cx = self.start_nodes['cx']
            def has_pig(n):
                return ((n.get('orig') or {}).get('corner_marker') or {}).get('name') in ('pig1', 'pig2')
            # 第一优先级：path上最靠前的pig节点；第二优先级：不在path且在起点右侧的最靠左pig节点
            target_node = (
                next((n for n in self.path if has_pig(n)), None)
                or min((n for n in self.nodes if n['idx'] not in path_ids and has_pig(n) and n['cx'] >= start_cx),
                       key=lambda n: n['cx'], default=None)
            )
            if target_node is not None:
                x, y = int(target_node["cx"]), int(target_node["cy"])
                key_mouse_manager.click(x, y)
                key_mouse_manager.wait()
                self.click_text(text="确认目标", box=[1635, 1735, 968, 996])
            else:
                #战争崇拜无猪可改，放弃
                CUS_LOGGER.info("「放心，我会替你照顾。」")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
        elif "毁灭" in text:
            #其它节点一律放弃
            self.click_text(text="放弃", box=[1221, 1276, 967, 998])
    def choose_bless(self):
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
    def select_go(self):
        num = extract_number(match_numbers_in_region(self.screen))
        if num is not None:
            num=int(num)
            if num%8==0:
                self.kill_count=num//8
            else:
                CUS_LOGGER.warning("不能整除8的参数")
                return
        else:
            CUS_LOGGER.warning("未知的被动效果参数")
            return
        time.sleep(2)#阻塞式等待播完动画，有待优化
        num = extract_number(match_numbers_in_region(self.get_screen()))
        if num is None or int(num)%8!=0:
            return
        else:
            num = int(num)
            kill_count=num // 8
            if kill_count!=self.kill_count:
                return
        CUS_LOGGER.debug(f"当前击杀数{self.kill_count}")
        self.set_kill_num(str(self.kill_count))
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("w")
        key_mouse_manager.wait()
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996],click=False,allow_fail=True):
            if self.click_text(text="点击空白处关闭", box=[876, 1047, 1008, 1035],click=False,allow_fail=True):
                CUS_LOGGER.info("「下一世，真理定会解明，死生……将有序流转。」")
                key_mouse_manager.wait()
                return
            self.try_analysis_map(mode=2)
            if self.next_node is not None:
                self.start_nodes=self.next_node
                x,y=int(self.next_node["cx"]),int(self.next_node["cy"])
                key_mouse_manager.click(x,y)
                key_mouse_manager.wait()
                self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
                if self.area != "" and self.now_map!=-1:
                    visit_count = self.record_map_visit(self.now_map)
                    CUS_LOGGER.debug(f"上次地图编号{self.now_map}, 累计访问次数: {visit_count}")
            else:
                CUS_LOGGER.error("未找到下一步路径点")
            if self.early_stop and self.gwypzmgzcndqlp:
                if self.plane_floor==1 and self.kill_count+self.max_limited<self.first_plane_count:
                    self.need_end=True
                    CUS_LOGGER.debug(f"当前极限值{self.kill_count+self.max_limited}无法达到第一位面推荐值{self.first_plane_count},终止本次演算")
                elif self.plane_floor==2 and self.kill_count+self.max_limited<self.second_plane_count:
                    self.need_end=True
                    CUS_LOGGER.debug(f"当前极限值{self.kill_count + self.max_limited}无法达到第二位面推荐值{self.second_plane_count},终止本次演算")
        else:
            self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
            self.new_node=True
    def calculated_roll(self):
        if self.nodes is None or self.plane_floor==-1:
            self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
            key_mouse_manager.wait()
            return
        roll_count = match_roll_count_in_region(self.screen)
        if roll_count is not None:
            CUS_LOGGER.debug(f"当前重投次数: {roll_count}")
        cheat_count = match_cheat_count_in_region(self.screen)
        if cheat_count is not None:
            CUS_LOGGER.debug(f"当前作弊次数: {cheat_count}")
        if not self.check("fast_roll", 0.1281,0.9074, threshold=0.9):
            self.click_text(text="快速投掷", box=[1700, 1823, 80, 117])
        if self.plane_floor in [2,3]:
            text = self.ts.find_with_box(box=[1339, 1576, 429, 464], forward=True, re_screen=False)
            text = merge_text(text) if len(text) else ""
            CUS_LOGGER.info(f"拿去吧…我背负的一切。(当前效果{text})")
            if "肉体" not in text:
                cheating =not self.check("zero", 0.3046,0.3324, threshold=0.95)
                redo=not self.check("zero", 0.1297,0.3315, threshold=0.95)
                CUS_LOGGER.debug(f"决策可用动作{cheating},{redo}")
                if cheating or redo:
                    best_path, best_weight, best_end_idx, self.replace_idx, delta, discounted_delta = evaluate_best_single_replacement(
                        self.nodes, self.edges, self.start_nodes['idx'], t=0.3 if self.plane_floor == 3 else 0.2)
                    CUS_LOGGER.debug(f"期权最佳代替节点{self.replace_idx},计算替换后最佳路径{best_path}，当前节点{self.start_nodes}")
                    if len(best_path)>1:
                        if best_path[1]['idx'] == self.replace_idx:
                            CUS_LOGGER.debug(f"期权最佳代替节点{self.replace_idx},替换后最佳路径{best_path}")
                            if cheating:
                                self.click_text(text="作弊", box=[1261, 1321, 761, 792])
                                return
                            elif redo:
                                self.click_text(text="重投", box=[1599, 1657, 760, 795])
                                return
        self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
        self.init_map(self.new_node)
        self.mini_state = 1
    def init_map(self,add=False):
        super().init_map()
        self.special_interaction_failures.clear()
        self.native_special_map_root = None
        self.loaded_map_root = None
        if add:
            self.node_count+=1
    def strange_shop(self):
        img = self.get_small_interaction_img(x=0.5000, y=0.7333, mask="mask_strange", fresh=True)
        res=self.ts.split_strange(img)
        strange_index_list=[]
        black_index_list=[]
        for i,strange in enumerate(res[1]):
            if '胡须火药'in strange or '纯美骑士' in strange:
                strange_index_list.append(i)
            elif '三八面骰' in strange or '银河大乐透' in strange:
                strange_index_list.append(i)
            elif '普通八卦' in strange or '万识囊' in strange or '混沌特效' in strange or '羊皮卷' in strange:
                strange_index_list.append(i)
            elif '分裂咕咕钟' in strange or '血锦之纪' in strange or '星际大乐透' in strange or '机械齿轮' in strange:
                black_index_list.append(i)
        for i in strange_index_list:
            key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0][i]))
            key_mouse_manager.click(0.1365, 0.1093)
            key_mouse_manager.wait()
            for _ in range(5):
                self.click_text(text="点击空白", box=[872, 1048, 729, 1015],warning=False)
        key_mouse_manager.press("esc")
    def select_secret(self):
        tx, ty = self.tx, self.ty
        success = False
        CUS_LOGGER.info("没错，我们会尽己所能将其诠释：比世界的命运更为沉重之物……")
        tm=time.time()
        for i in range(1,9):
            if self.check(f"fate{i}", 0.1828, 0.5000, mask="mask_event", threshold=0.965, fresh=True):
                success=True
                break
        if success:
            success=False
            while time.time()-tm<1.5:
                if self.check("confirm", 0.1828, 0.5000, mask="mask_event", threshold=0.965,fresh=True):
                    success = True
                    break
        else:
            self.click_text(text="秘闻", box=[197, 233, 887, 906])
        if success:
            CUS_LOGGER.info("原来那浑身着火的恶魔，满脑子幻想的都是要成为「救世主」哪！")
            key_mouse_manager.click(self.tx, self.ty)
        else:
            CUS_LOGGER.info("「救世主」…在命运三相神谕的语境下，这张牌意味着谐调和完美无缺。")
            key_mouse_manager.click(tx, ty)
            key_mouse_manager.click(0.1167, ty - 0.1139)
    def select_event(self):
        super().select_event()
        if self.new_node:
            event_name = self.ts.find_with_box(box=[185, 750, 953, 1008], forward=True, re_screen=False)
            if any(isinstance(ev, dict) and "阮·梅" in ev.get("raw_text", "") and "其二" in ev.get("raw_text", "") for ev in event_name):
                self.ruanmei2 = True#本轮遭遇「阮·梅（其二）」，本轮视频将保留
            if self.area!="" and self.area!="休整" and len(event_name)!=0:
                try:
                    db_file = "config/backup/node_log.db"
                    os.makedirs("config/backup", exist_ok=True)
                    conn = sqlite3.connect(db_file)
                    cursor = conn.cursor()
                    cursor.execute('''CREATE TABLE IF NOT EXISTS node_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT DEFAULT (datetime('now','localtime')),
                        data TEXT
                    )''')
                    data = {
                        "area": self.area,
                        "event": event_name,
                        "plane_floor": self.plane_floor,
                    }
                    cursor.execute('INSERT INTO node_log (data) VALUES (?)',
                                   (json.dumps(data, ensure_ascii=False),))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    CUS_LOGGER.error(f"写入节点日志失败: {e}")
            self.new_node=False
    def emergency(self):
        event_name = self.ts.find_with_box(box=[897, 1023, 500, 540], forward=True, re_screen=False)
        if len(event_name)==0:
            self.save_screen(not_now=True,save_path="/temp/event/")
            # self.stop()
            CUS_LOGGER.warning("未识别到突发事件文本，可能是战斗变虫群的突发事件，已截图保存")
        try:
            db_file = "config/backup/emergency.db"
            os.makedirs("config/backup", exist_ok=True)
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS node_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                data TEXT
            )''')
            data = {
                "count": self.count,
                "node_count": self.node_count,
                "event": event_name,
                "plane_floor": self.plane_floor,
            }
            cursor.execute('INSERT INTO node_log (data) VALUES (?)',
                           (json.dumps(data, ensure_ascii=False),))
            conn.commit()
            conn.close()
        except Exception as e:
            CUS_LOGGER.error(f"写入节点日志失败: {e}")
    @staticmethod
    def set_kill_num(num):
        log_emitter.kill_num_signal.emit(num)

    @staticmethod
    def record_map_visit(map_id):
        """
        记录并返回地图访问次数（使用SQLite数据库）

        参数:
            map_id: 地图编号

        返回:
            int: 该地图的累计访问次数
        """
        db_file = "config/backup/map_visits.db"
        os.makedirs("config/backup", exist_ok=True)

        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 创建表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS map_visits (
                map_id TEXT PRIMARY KEY,
                visit_count INTEGER DEFAULT 0
            )
        ''')

        # 查询并更新
        cursor.execute('SELECT visit_count FROM map_visits WHERE map_id = ?', (str(map_id),))
        result = cursor.fetchone()

        if result:
            new_count = result[0] + 1
            cursor.execute('UPDATE map_visits SET visit_count = ? WHERE map_id = ?', (new_count, str(map_id)))
        else:
            new_count = 1
            cursor.execute('INSERT INTO map_visits (map_id, visit_count) VALUES (?, ?)', (str(map_id), new_count))

        conn.commit()
        conn.close()

        return new_count
