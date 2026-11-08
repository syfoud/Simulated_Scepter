import json
import os
import random
import sqlite3
import time

import cv2 as cv
import numpy as np

from route import PATHS
from core.common.config import load_runtime_settings
from core.common.runtime import set_forground, sprint
from core.any_fate.utils import FateUtils
from core.any_fate.text_key import FATES
from tool.settings import load_settings
from tool.storage import load_module_settings
from tool.storage import resource_path
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER, log_emitter
from tool.mask import MASK, crop_region
from tool.thread import ThreadWithException
from tool.public_ocr import load_actions, merge_text
from tool.utils.analysis_map import (
    build_rightward_graph,
    compute_all_max_steps,
    compute_start_point_from_crop,
    detect_corner_markers,
    display_matches,
    evaluate_best_single_replacement,
    match_multiple_targets,
    max_weight_path, build_rightward_graph2,
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
    match_cheat_count_in_region,
    match_locked_roll_count_in_region,
    match_roll_count_in_region,
)
from tool.utils.tool import find_latest_modified_file, get_center, get_dis
from tool.window_recorder import WindowRecorder
from tool.utils.ocr_num import match_skill_numbers_in_region
from tool.silver_wolf_manager import SilverWolfManager


class AnyFateUniverse(FateUtils):
    """任意命途寰宇蝗灾：各命途通用的寻路、骰子、事件等公共流程。"""

    def __init__(self):
        self.opt = load_settings() | load_runtime_settings()
        self.opt.update(load_module_settings(__file__))
        # 任意命途：从设置读取命途并重建祝福优先级
        fate = self.opt.get("any_fate", "巡猎")
        if fate not in FATES:
            CUS_LOGGER.warning(f"未知命途「{fate}」，已回退为巡猎")
            fate = "巡猎"
        super().__init__(
            fate=fate,
            debug=self.opt.get("debug", True),
            max_run_time=self.opt.get("max_run_time", 0),
        )
        CUS_LOGGER.info(f"任意命途寰宇蝗灾已就绪，当前命途：{self.fate}")
        self.plane_floor = -1
        self.need_record = False
        # 录图模式下每张新地图只保存一次初始小地图；普通寻路也会读它，所以必须有初值
        self.first_save_map = True
        # 同一张地图的连续暂离次数：因超时暂离时 +1，换图/换位面/新一局归零
        self.fail_count = 0
        # 本局是否出现过同一张地图连续暂离 3 次；出现后本局录像必须保留
        self.keep_round_video = False
        # 是否需要暂离；只在成功识别到「暂离」文本后清除，避免网络/动画导致请求丢失
        self.need_away = False
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
            templates = {}
            if os.path.isdir(map_root):
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
            self.record_map_contexts[map_kind] = (map_root, templates)
        if self.record_event_map_enabled:
            roots = "、".join(
                context[0] for context in self.record_map_contexts.values()
            )
            CUS_LOGGER.debug(f"特殊地图录图模式已开启，各类地图将分别保存至{roots}")
        self.default_json_path = str(resource_path(__file__, "actions/insect.json"))
        self.default_json = load_actions(self.default_json_path)

        event_any_fate = resource_path(__file__, "config/event_any_fate.json")
        with open(event_any_fate, encoding="utf-8", errors="ignore") as f:
            self.event_prior = json.load(f)["event"]
        self.steps=None
        self.nodes=None
        self.replace_idx=None
        self.next_node = None
        self.max_limited = None
        self.run_start_time = time.time()
        self.elapsed_time = 0 # 本轮演算持续时间
        self.attack_time = 0 # 上次空打一拳时间
        self.need_end=False
        self.record = self.opt.get("recording_iron_blood", True)
        self.recorder = WindowRecorder(output_path=PATHS["video"], fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=self.opt.get("record_add_label", True), offsets=[10, 50, 10, 10], overlay_map=self.opt.get("record_add_label", True) and self._show_map, simul_instance=self)
        self.auto_attack_breakable=self.opt.get("auto_attack_breakable", False)
        self.del_record_time=self.opt.get("del_record_time", 31)
        self.max_interact_time=self.opt.get("max_interact_time", 40)
        self.area=""
        self.now_map=-1
        self.new_node = True
        self.node_count=0
        self.fail_match_count = 0
        self.ruanmei2 = False  # 本轮是否遭遇过「阮·梅（其二）」
        self.chaoyan_seen = False  # 本轮是否进过「超验之镜」（不可重复）
        self.special_interaction_failures = {}
        self.native_special_map_root = None
        self.loaded_map_root = None
        self.current_role = 1  # 当前控制角色序号
        self.start_nodes = None # 当前路径起始节点，try_analysis_map中更新
        self.silver_wolf_manager = SilverWolfManager(self)
        self.now_area=[]
        self.cheat_target = None  # 本次作弊要选的骰面效果名，由各模式在点「作弊」按钮前写入
        self.last_interact_time = time.time() # 上次有效交互时间（移动、施法、交互等），用于判定是否暂离
        CUS_LOGGER.info("宇宙的中心有一团火种,它愈烧愈旺,直至燃尽整片星河。")

    def restart_recording(self):
        super().restart_recording()
        self.fail_match_count=0
        self.node_count=0
        self.now_area=[]
        # 新一局重新统计连续暂离；录像已在 super() 里按上一局的 keep_round_video 处理完
        self.fail_count = 0
        self.keep_round_video = False
        # 「超验之镜」标记由 select_event 写入、各模式建图都按它给战斗降权，漏清会让之后每一轮都在用错的权重
        self.chaoyan_seen = False
        self.ruanmei2 = False

    def leave_universe(self, leave_away=False, leave_end=False, keep_status=False):
        """统一处理离开模拟宇宙：手动暂离、超时暂离、提前结算、冒险后正常离开。

        Args:
            leave_away: 权杖发起暂离时为 True；动作脚本识别到「暂离」文本时保持 False，因为此时暂停菜单已经打开。
            调用方需要先置 need_away=True，失败重试时靠它保留请求。
            leave_end: 权杖发起提前结算时为 True；调用方需要先置 need_end=True。
            keep_status: 暂离后不重置区域与地图；冒险节点交互完直接离开不属于异常，也不累计暂离次数。

        Returns:
            True 表示已处理完；False 表示暂停菜单没打开，请求保留到下一轮重试。
        """
        if leave_away or leave_end:
            # 代码发起时必须自己按 esc 并等待菜单；动作脚本触发时菜单已经打开
            found = self.click_text(text="暂离", box=[1321, 787, 1383, 821], click=False, allow_fail=True)
            if not found:
                key_mouse_manager.clean()
                key_mouse_manager.wait()
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.press("esc")
                key_mouse_manager.wait()
                deadline = time.time() + 3
                while time.time() < deadline:
                    if self.click_text(text="暂离", box=[1321, 787, 1383, 821], click=False, allow_fail=True):
                        found = True
                        break
                    key_mouse_manager.wait()
            if not found:
                CUS_LOGGER.debug("未识别到暂离文本，保留退出请求等待重试")
                return False
        timeout_area = self.area
        if leave_end or self.need_end:
            # 结算界面出现后由 settle_university 清除 need_end，这里只点「结束并结算」
            self.update_state("exit")
            key_mouse_manager.click_point(1393, 948)
            key_mouse_manager.wait()
            key_mouse_manager.click_point(1147, 676)
            key_mouse_manager.wait()
            CUS_LOGGER.info(f"{factor}将跨越旧世界的余烬，不断燃烧……")
            return True
        self.initial_angle = None
        key_mouse_manager.click_point(1359, 811)
        key_mouse_manager.wait()
        self.update_state("ui")
        if not keep_status:
            self.area = ""
            self.init_map()
        if (leave_away or self.need_away) and not keep_status:
            # 只统计同一张地图上的超时暂离
            self.fail_count += 1
            if self.fail_count >= 3:
                # 同一节点反复暂离超过 3 次说明出现异常，结束时保留录像便于复盘
                self.keep_round_video = True
            CUS_LOGGER.error(f"当前第{self.plane_floor}位面，区域{timeout_area}，地图{self.now_map}，第{self.fail_count}次长时间无有效交互，尝试暂离")
        self.need_away = False
        self.last_interact_time = time.time()
        CUS_LOGGER.info(f"纵使神火已经如此炽烈，以至于…每次回归起点的瞬间，它便会顷刻将{factor}烧尽…… ")
        return True

    def keep_video_reasons(self, manual_stop=False):
        """在通用原因之外，再加上「同一张地图反复暂离」这一条。"""
        reasons = super().keep_video_reasons(manual_stop)
        if getattr(self, "keep_round_video", False):
            reasons.append("同一张地图连续暂离达到 3 次")
        return reasons

    def end_of_university(self):
        super().end_of_university()
        self.run_start_time = time.time()  # 开始下一局计时
        # 结算界面已经出现，提前结束与本局暂离的请求都在这里清掉
        self.need_end=False
        self.need_away=False
        self.silver_wolf_manager.silver_wolf_slot = None  # 重置银狼位置缓存
        self.init_map()

    # 切换指定位置的角色
    def switch_current_role(self, num):
        if self.current_role != num:
            key_mouse_manager.press(f"role_{num}")
            self.current_role = num
            CUS_LOGGER.debug(f"已切换至{num}号位角色")
            key_mouse_manager.sleep(0.6)
            return True
        else:
            return False

    def is_pig_node(self):
        """当前节点是否为祝福扑满。"""
        if self.start_nodes is None:
            return False
        corner_marker = (self.start_nodes.get('orig') or {}).get('corner_marker')
        return bool(corner_marker) and corner_marker.get('name') in ('pig1', 'pig2')

    def switch_to_configured_role(self):
        """按 silver_wolf_switch 配置切换到指定角色位。"""
        switch_target = self.opt.get("silver_wolf_switch", 1)
        CUS_LOGGER.debug(f"按设置切至{switch_target}号位")
        self.switch_current_role(switch_target)
        self.quan = 0
        self.bai_e = 0

    def use_e(self, face=False, fixed=False):
        """使用秘技；银狼秘技勾选，一号位为黄泉/白厄且秘技点不足银狼释放时，改用普通攻击以保留秘技点。"""
        if not fixed and self.silver_wolf_manager.should_skip_skill():
            CUS_LOGGER.debug("银狼秘技：为保留秘技点，本次改为普通攻击")
            key_mouse_manager.click_point(960, 540)
            key_mouse_manager.wait()
            return
        super().use_e(face=face, fixed=fixed)

    def normal(self):
        bk_lst_changed = self.last_interact_time
        self.last_interact_time = time.time()
        self.ts.forward(self.get_screen())
        res,state = self.run_static()
        if self.state=="run":
            CUS_LOGGER.info("那朵微弱的火苗，启程之初便已种进他的心里。")
            # 检查黄泉和白厄
            if not self.quan and self.check("huangquan",1809,315):
                self.quan = 1
            elif not self.bai_e and self.check("bai_e",1800,314):
                self.bai_e = 1
            #上次交互时间
            self.last_interact_time = bk_lst_changed
            # 本局是否需要暂离：长时间没有有效交互则暂离并重进。
            # 必须在走动和施放秘技之前判定：秘技施放动画期间按 esc 无效。
            if (time.time() - self.last_interact_time >= self.max_interact_time and not self.need_record):
                self.need_away = True
            # 刚进图，初始化一些数据
            if not (self.need_end or self.need_away):
                if not self.area:
                    ocr_text = self.ts.find_with_box(box=[55, 12, 164, 40],forward=True,re_screen=False)
                    self.area=merge_text(ocr_text) if len(ocr_text) else ""
                    CUS_LOGGER.debug(f"当前区域{self.area}")
                # 当前节点为祝福扑满且非精英区域时，根据开关决定切人策略
                pig = self.is_pig_node() and "战斗" in self.area
                if pig:
                    CUS_LOGGER.info("梦中那刺骨的愤怒与对自我的憎恨仍在震动着他的心。")
                if self.opt.get("silver_wolf_enable", False):
                    if not self.silver_wolf_manager.activate():
                        slot = self.silver_wolf_manager.silver_wolf_slot
                        if slot == 1 and pig and self.opt.get("pig_switch_2_role", False):
                            self.switch_to_configured_role()
                        else:
                            self.switch_current_role(num=1)
                elif pig and self.opt.get("pig_switch_2_role", False):
                    self.switch_to_configured_role()
                else:
                    self.switch_current_role(num=1)
                if "黑塔的办公" not in self.area:
                    # 空打一拳，5秒内不重复操作
                    if self.auto_attack_breakable and not self.big_map_init and time.time() - self.attack_time >= 5:
                        key_mouse_manager.click_point(960, 540)
                        CUS_LOGGER.debug("尝试空打一拳")
                        self.attack_time = time.time()
                        key_mouse_manager.sleep(0.6)
                    if self.opt.get("silver_wolf_enable", False):
                        slot = self.silver_wolf_manager.silver_wolf_slot
                        if slot in (1, 2, 3, 4) and self.current_role == slot:
                            bean = self.silver_wolf_manager.has_bean_icon(slot)
                            skill_num = match_skill_numbers_in_region(self.screen)
                            self.skill_num = skill_num if (skill_num is not None) else 5
                            if slot == 1:
                                cast = not bean and (
                                    self.skill_num >= 2
                                    or (self.skill_num == 1 and ("战斗" not in self.area or pig))
                                )
                                release = (
                                    bean and self.skill_num == 1
                                    and "战斗" in self.area and not pig
                                )
                            else:
                                cast = not bean and self.skill_num >= 1
                                release = False
                            if cast:
                                key_mouse_manager.sleep(0.6) # 实测在网络延迟较高的情况下银狼有概率释放不出秘技，因此增加0.6s延迟。后续或可更改为实时检测银狼秘技施放情况
                                key_mouse_manager.press("technique")
                                CUS_LOGGER.debug("已施放银狼秘技")
                                key_mouse_manager.sleep(0.6)
                            elif release:
                                key_mouse_manager.press("technique")
                                CUS_LOGGER.debug("已解除银狼秘技")
                                key_mouse_manager.sleep(0.6)
                key_mouse_manager.wait()
                battle_map_root = os.path.join(PATHS["image"], "nmaps")
                if (("战斗" in self.area or "精英" in self.area or "首领" in self.area)
                        and self.loaded_map_root not in (None, battle_map_root)):
                    self.init_map()
                if "战斗" in self.area:
                    if self.navigate_battle():
                        return 1
                elif "精英" in self.area or "首领" in self.area:
                    if self.navigate_battle(True):
                        return 1
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
                    self.get_adventure()
                elif "空白" in self.area:
                    # 空白节点可能是任意类型，先查小地图标志再决定寻路方式
                    if self.check_minimap_icon("mini_event"):
                        if self.record_special_map_or_navigate(self.get_event_only_minimap):
                            return 1
                    elif self.check_minimap_icon("mini_shop", 0.925):
                        if self.record_special_map_or_navigate(self.get_shop_only_minimap):
                            return 1
                    elif self.check_minimap_icon("mini_rest"):
                        if self.record_special_map_or_navigate(self.get_rest_only_minimap):
                            return 1
                    else:
                        # 无事件/交易/休整标志，按战斗类型寻路兜底
                        if self.navigate_battle():
                            return 1
                else:
                    #背景有光污染，未能成功识别区域名
                    self.area=""
                    key_mouse_manager.turn(1)
                    key_mouse_manager.wait()
            else:
                # 暂离或提前结算都走统一出口；失败时退出请求保留，下一轮重试
                self.leave_universe(leave_away=not self.need_end, leave_end=self.need_end)
                return 1
            return 2
        key_mouse_manager.wait()
        if res != '':
            return state
        else:
            return 0

    def check_minimap_icon(self, icon_name, threshold=0.85):
        """检查小地图上是否存在指定图标标志。"""
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True, center_radius=90)
        icon = find_image_by_name(icon_name)
        best_val = -1
        for scale in [1.00, 1.05, 1.10, 1.15, 1.20, 1.25]:
            mini_icon = cv.resize(icon, None, fx=scale, fy=scale, interpolation=cv.INTER_CUBIC)
            result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
            _, max_val, _, _ = cv.minMaxLoc(result)
            if max_val > best_val:
                best_val = max_val
        return best_val > threshold

    def navigate_battle(self, fixed=False):
        """战斗/精英/首领节点的通用寻路：加载地图并按目标点移动。

        Args:
            fixed: 是否为固定目标（精英/首领）节点。

        Returns:
            True 表示已停止或加载失败，调用方应直接返回；False 表示寻路完成。
        """
        if not self.big_map_init:
            key_mouse_manager.clean()
            key_mouse_manager.keyUp("move_w")
            key_mouse_manager.wait()
            if self._stop:
                return True
            self.find, self.need_record, state = self.map_data_load()
            if fixed:
                CUS_LOGGER.info("面对「纷争」的半神……你绝无可能以和平的姿态取走这枚火种。")
            else:
                CUS_LOGGER.info(f"{factor}将燃烧…会燃尽。成为这一世的盗火行者。杀死神明和伙伴，夺走火种。")
            if self._stop or not state:
                return True
        if self.need_record:
            self.recording_map()
        elif self.find:
            self.get_path_with_big_map(fixed)
        else:
            self.get_path_only_minimap(fixed)
        return False

    def get_record_map_context(self):
        """根据当前区域返回其专属录图目录和地图模板集合。"""
        if "事件" in self.area or "奖励" in self.area:
            map_kind = "event"
        elif "休整" in self.area:
            map_kind = "rest"
        elif "交易" in self.area:
            map_kind = "trade"
        elif "空白" in self.area:
            # 空白节点可能是任意类型，按实际匹配到的小地图标志决定
            if self.check_minimap_icon("mini_event"):
                map_kind = "event"
            elif self.check_minimap_icon("mini_shop", 0.925):
                map_kind = "trade"
            elif self.check_minimap_icon("mini_rest"):
                map_kind = "rest"
            else:
                return None
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
            key_mouse_manager.keyUp("move_w")
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
        if not interaction_targets or self.target_loc is None:
            current_interactions = set()
        else:
            current = min(
                interaction_targets,
                key=lambda target: (
                    (target[0][0] - self.target_loc[0]) ** 2
                    + (target[0][1] - self.target_loc[1]) ** 2
                ),
            )
            current_interactions = {
                target for target in interaction_targets
                if ((target[0][0] - current[0][0]) ** 2
                    + (target[0][1] - current[0][1]) ** 2) <= 64
            }
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

    def map_data_load(self, create=False, map_root=None, image_maps=None, target_mode="battle"):
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
        if self.get_blank_state(save_debug_dir=os.path.join(PATHS["temp"], "blank_state"))>250:
            tm=time.time()
            max_map,max_sim=-1,-1
            while time.time()-tm<2:
                local = deal_minimap(
                    get_minimap(self.get_screen(), radius=MINIMAP_RADIUS, copy=True),
                    is_minimap=True,
                )
                local = cv.resize(local, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC)
                best_sim = -1
                best_map = -1
                for map_name, search_image in image_maps.items():
                    if (search_image.shape[0] < local.shape[0]
                            or search_image.shape[1] < local.shape[1]):
                        continue
                    result = cv.matchTemplate(search_image, local, cv.TM_CCOEFF_NORMED)
                    _, similarity, _, _ = cv.minMaxLoc(result)
                    if similarity > best_sim:
                        best_sim = similarity
                        best_map = map_name
                self.now_map, self.now_map_sim = best_map, best_sim
                if self.now_map_sim>max_sim:
                    max_map=self.now_map
                    max_sim=self.now_map_sim
                if self.now_map_sim > 0.7:
                    break
            self.now_map,self.now_map_sim=max_map,max_sim
            if self.click_text(text="确认",box=[1361, 713, 1417, 744],click=False,allow_fail=True):
                self.big_map_init = False
                key_mouse_manager.wait()
                time.sleep(3)
                return find,record,False
            CUS_LOGGER.debug(f"地图编号：{self.now_map}  相似度：{self.now_map_sim}")
            if (self.debug and self.now_map_sim < 0.4) or self.now_map_sim < 0.35:
                CUS_LOGGER.warning(f"相似度过低,疑似未找到匹配地图,匹配地图{self.now_map}")
                if create:
                    while True:
                        map_name = "my_" + str(random.randint(0, 99999))
                        map_file = os.path.join(map_root, map_name)
                        try:
                            os.makedirs(map_file)
                            self.now_map = map_name
                            self.map_file = map_file + os.sep
                            break
                        except FileExistsError:
                            continue
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
                key_mouse_manager.press("move_s")
                key_mouse_manager.wait()
                key_mouse_manager.keyDown("move_w")
        else:
            if self.click_text(text="确认",box=[1361, 713, 1417, 744],click=False,allow_fail=True):
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
        self.area = ""
        con = self.click_text(text="继续进度",box=[1610, 937, 1762, 1023],click=False,ocr_line=False,warning=False)
        if not con:
            #点击最低难度
            key_mouse_manager.click_point(120, 155)
        key_mouse_manager.click_point(1712, 971)
        if con:
            CUS_LOGGER.info("继续，燃烧下去。只要我们不曾熄灭……逐火就不会终结…")

    def select_fate(self):
        self.click_text(text=self.fate, box=[159, 782, 1761, 816], allow_fail=True)

    def select_head(self):
        self.click_text(text="击败该首领",box=[1108, 267, 1385, 290])
        self.click_text(text="确认选择",box=[1633, 961, 1733, 990])

    # 节点图是逐节点渲染出来的：识别开始得太早会漏掉尚未出现的节点，得到一张「缺节点」的图，
    # 期望值随之偏低（实测可为 0 或正常值的一半），使开局期望被误判为过低而提前退出，
    # 留下用时偏短的「假账」记录。因此识别必须使用最新截图，并等到连续多次匹配结果一致
    # （渲染稳定）才采信；等待期间只做开销较小的图标匹配，稳定后再做一次完整的角标检测与寻路。
    # 下面这组状态码是 analyze_map_until_stable 的返回值，也是写进 kill_record 的失败原因：
    # 正数表示识别成功，负数表示失败原因，便于事后分辨「图没识别出来」和「期望值本来就低」。
    MAP_ANALYSIS_OK = 1  # 识别成功
    MAP_ANALYSIS_TIMEOUT = -1  # 等待节点图渲染稳定超时
    MAP_ANALYSIS_NO_MATCH = -2  # 始终匹配不到地图图标
    MAP_ANALYSIS_NO_BOSS = -3  # 匹配到图标但没有首领/头目节点
    MAP_ANALYSIS_NO_PATH = -4  # 匹配到图标但构建不出有效路径
    MAP_ANALYSIS_NO_INIT = -5  # 本局没走到开局节点图识别（例如在模拟宇宙里直接开启权杖）
    MAP_ANALYSIS_STATUS = {
        MAP_ANALYSIS_OK: "识别成功",
        MAP_ANALYSIS_TIMEOUT: "等待节点图渲染稳定超时",
        MAP_ANALYSIS_NO_MATCH: "始终匹配不到地图图标",
        MAP_ANALYSIS_NO_BOSS: "未匹配到首领/头目节点",
        MAP_ANALYSIS_NO_PATH: "未找到有效路径",
        MAP_ANALYSIS_NO_INIT: "本局未进行开局节点图识别",
    }

    def map_match_signature(self, matches):
        """节点图标匹配结果的结构指纹，用于判断节点图是否还在生成。

        Args:
            matches: match_multiple_targets 的返回值。

        Returns:
            tuple: 按（图标名, 量化坐标）排序后的元组；节点图还没出现时为空元组。
        """
        # 坐标量化到 4 像素：抵消渲染抖动，又不至于把相邻两个节点混为同一个
        return tuple(sorted(
            (m['name'], int(m['location'][0] // 4), int(m['location'][1] // 4))
            for m in matches
        ))

    def wait_map_rendered(self, mode=1):
        """等节点图渲染稳定，返回本次等待的状态码与稳定帧。

        节点图是从左向右逐个生成的画面，渲染途中识别会漏掉还没出现的节点；
        替换精英节点的动画中途也会停顿一两帧。这里只做开销较小的图标匹配，
        连续三次匹配到完全相同的节点才算渲染结束。

        Args:
            mode: 识别模式，含义同 try_analysis_map。

        Returns:
            tuple: (状态码, 稳定帧)。状态码为 MAP_ANALYSIS_OK 时第二个元素是
                (image, matches)，即判定稳定的那一帧与它的匹配结果，可以直接交给
                try_analysis_map 复用，不必重新截图、重新匹配；其余情况第二个元素
                为 None，状态码为 MAP_ANALYSIS_NO_MATCH（等待期间一次都没匹配到
                地图图标）或 MAP_ANALYSIS_TIMEOUT。
        """
        deadline = time.time() + 10  # 节点图通常一两秒渲染完，这里给性能较差的机器留足时间
        previous_signature = None
        stable_rounds = 0
        seen_match = False
        while time.time() < deadline:
            round_start = time.time()
            image = self.get_screen()
            matches = match_multiple_targets(image, mode)
            signature = self.map_match_signature(matches)
            if not signature:
                # 节点图还没渲染出来
                previous_signature = None
                stable_rounds = 0
            elif signature == previous_signature:
                seen_match = True
                stable_rounds += 1
                if stable_rounds >= 3:
                    # 连续三次一致才采信：替换精英节点的动画中途会停顿一两帧
                    CUS_LOGGER.debug(f"节点图已渲染稳定，共 {len(signature)} 个节点")
                    return self.MAP_ANALYSIS_OK, (image, matches)
            else:
                seen_match = True
                previous_signature = signature
                stable_rounds = 1
            # 单次匹配本身就要几百毫秒，已经构成间隔，不再叠加固定等待
            sleep_time = max(0.0, 0.2 - (time.time() - round_start))
            if time.time() + sleep_time >= deadline:
                break
            time.sleep(sleep_time)
        status = self.MAP_ANALYSIS_TIMEOUT if seen_match else self.MAP_ANALYSIS_NO_MATCH
        CUS_LOGGER.warning(f"等待节点图渲染稳定超时（{self.MAP_ANALYSIS_STATUS[status]}）")
        return status, None

    def analyze_map_until_stable(self, mode=1, path_mode=2, captured=None):
        """等节点图渲染稳定后识别一次开局期望，返回本次识别的状态码。

        调用方（例如「进入位面」后推断开局期望）必须依据返回值决定能否使用
        self.expectation_weight：返回值不是 MAP_ANALYSIS_OK 时说明节点图没能
        稳定识别，此时期望值不可信，不允许据此提前退出演算。

        Args:
            mode: 识别模式，含义同 try_analysis_map。
            path_mode: 构图方式，含义同 try_analysis_map。
            captured: 可选的 (image, matches) 稳定帧。调用方已经调用过
                wait_map_rendered、并希望把耗时的完整识别推迟到点击之后
                （例如先点「进入位面」让游戏播入场动画，识别与动画重叠）时传入，
                此时本方法不再等待也不会重新截图；不传则自己等待渲染稳定。

        Returns:
            int: MAP_ANALYSIS_OK 表示已经识别到稳定的节点图，self.expectation_weight
                为可信结果（可能为 0）；其余负数表示失败原因，见 MAP_ANALYSIS_STATUS。
        """
        if captured is None:
            status, captured = self.wait_map_rendered(mode)
            if status != self.MAP_ANALYSIS_OK:
                self.expectation_weight = 0
                return status
        image, matches = captured
        # 节点图稳定后再完整识别一次：角标检测、建图寻路只有对稳定的图才有意义
        self.fail_match_count = 0
        self.expectation_weight = 0
        try:
            if self.try_analysis_map(mode, path_mode, image=image, matches=matches):
                return self.MAP_ANALYSIS_OK
            status = self.MAP_ANALYSIS_NO_PATH
        except NoMatchError:
            status = self.MAP_ANALYSIS_NO_MATCH
        except NoBossError:
            status = self.MAP_ANALYSIS_NO_BOSS
        CUS_LOGGER.warning(
            f"节点图已渲染稳定但识别失败（{self.MAP_ANALYSIS_STATUS.get(status, '未知原因')}），"
            "本次识别结果不予采信")
        self.expectation_weight = 0
        return status

    def try_analysis_map(self,mode=1,path_mode=2,image=None,matches=None):
        """识别当前节点图并算出路径理论期望值。

        Args:
            mode: 识别模式：1 进入位面前的总览图，2 选择移动目标，3 地图更新。
            path_mode: 1 用 build_rightward_graph，其余用 build_rightward_graph2。
            image: 可选，复用调用方刚截取的画面；不传则重新截图。
            matches: 可选，复用调用方对 image 做好的匹配结果；不传则自己匹配。
                与 image 一起传可以在「先点击、后识别」时避开已经切走的画面。

        Returns:
            bool: 是否找到有效路径。返回 False 时 self.expectation_weight 不可信。

        Raises:
            NoMatchError: 匹配不到地图图标。
            NoBossError: 匹配到地图图标但没有首领/头目节点。
        """
        # 默认必须重新截图：self.screen 可能是上一轮循环留下的旧画面，
        # 而节点图是一次性渲染完成的，用旧画面识别会漏掉后出现的节点。
        if image is None:
            image = self.get_screen()
        if matches is None:
            matches = match_multiple_targets(image, mode)
            if len(matches)==0:
                self.click_text(text="点击空白处关闭", box=[875, 776, 1047, 807])
                CUS_LOGGER.warning("未匹配到任何地图图标却错误进入寻路阶段，可能是误识别")
                CUS_LOGGER.warning("刷新截图缓冲区后最后一次尝试匹配地图图标")
                image = self.get_screen()
                matches = match_multiple_targets(image, mode)
                if len(matches) == 0:
                    self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "bigmaperror"))
                    self.save_screen(save_path=os.path.join(PATHS["temp"], "bigmaperror"))
                    raise NoMatchError
        CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
        # 检测角标（pig/reinforce/alienation等），关联到最近节点
        corner_results = detect_corner_markers(image, matches, mode)
        if corner_results:
            CUS_LOGGER.debug(f'检测到 {len(corner_results)} 个角标')
            for cr in corner_results:
                CUS_LOGGER.debug(f"  {cr['name']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']}({matches[cr['node_idx']]['name']}) dist={cr['node_dist']}")
        if mode==2:
            # 把当前操控角色位交给 analysis_map 优先尝试；检测结果与
            # current_role 不一致时（例如 silver_wolf_manager 在秘技点
            # 耗尽时直接按 "1" 切回一号位，未经过 switch_current_role），
            # 以检测结果为准更新 current_role，使该属性始终反映实际状态。
            center, details = compute_start_point_from_crop(image, return_details=True, preferred_slot=self.current_role)
            if center is None:
                center, details = compute_start_point_from_crop(image, th=0.7, return_details=True,preferred_slot=self.current_role)
            start = center
            if details is not None and details['slot'] != self.current_role:
                CUS_LOGGER.debug(f"角色位与 current_role 不一致：current_role={self.current_role} 检测={details['slot']}，同步为检测结果")
                self.current_role = details['slot']
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
        fuc = build_rightward_graph if path_mode == 1 else build_rightward_graph2
        weights = {"battle_weight": float(self.opt.get("battle_weight", 1.2))} if path_mode == 1 else {}
        if mode == 3:
            self.nodes, self.edges, start_idx = fuc(
                matches, start=start,
                max_gap=110, max_overlap=50, max_dy=130,
                plane=self.plane_floor, chaoyan_seen=self.chaoyan_seen, **weights
            )
        else:
            self.nodes, self.edges, start_idx = fuc(
                matches, start=start,
                plane=self.plane_floor, chaoyan_seen=self.chaoyan_seen, **weights
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
                return False
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
                CUS_LOGGER.info('替换评估：未找到有益的单节点替换')
                highlight = None
                alt_path = None
            else:
                b = self.replace_idx
                k = self.steps.get(b, -1)
                CUS_LOGGER.debug(f"最佳单节点替换：索引={b}, 名称={self.nodes[b]['name']}")
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
                CUS_LOGGER.debug(f'原路径理论期望值：{self.expectation_weight:.3f} (min={orig_min}, max={orig_max})')
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
        return True

    def initing_map(self):
        key_mouse_manager.keyUp("move_w")
        if self.click_text(text="振翅",box=[10, 0, 220, 112],click=False,warning=False):
            self.plane_floor=1
        elif self.click_text(text="浪潮",box=[10, 0, 220, 112],click=False,warning=False):
            self.plane_floor=2
        elif self.click_text(text="消褪",box=[10, 0, 220, 112],click=False,warning=False):
            self.plane_floor=3
        else:
            CUS_LOGGER.warning("多么绝妙的巧合。你我都心知肚明。")
            return
        self.fail_count = 0
        self.try_analysis_map(1)
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 857, 1009, 891])
            self.node_count=0
            self.new_node = True
            self.area = ""
        key_mouse_manager.wait()
        return

    def initing_map2(self):
        key_mouse_manager.keyUp("move_w")
        if self.click_text(text="振翅",box=[385, 548, 449, 583],click=False,warning=False):
            self.plane_floor=1
        elif self.click_text(text="浪潮",box=[385, 548, 449, 583],click=False,warning=False):
            self.plane_floor=2
        elif self.click_text(text="消褪",box=[385, 548, 449, 583],click=False,warning=False):
            self.plane_floor=3
        else:
            CUS_LOGGER.warning("以神礼观众之名，我见到————「毁灭」，于斯合题！")
            return
        CUS_LOGGER.debug(f"当前地图位面{self.plane_floor}")
        self.fail_count = 0
        self.try_analysis_map(3)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        return

    def select_strange(self):
        img = self.get_small_interaction_img(MASK["strange_name"], fresh=True)
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
            elif '齿星系' in strange or '分裂咕咕钟' in strange or '血锦之纪' in strange or '星际大乐透' in strange or '机械齿轮' in strange:
                black_index_list.append(i)
                if '机械齿轮' in strange:
                    black_first = i
                elif '星际大乐透' in strange and black_first==-1:
                    black_first = i
                elif '分裂咕咕钟' in strange and black_first==-1:
                    black_first = i
        if strange_index!=-1:
            CUS_LOGGER.debug(f"优先选择第{strange_index}个奇物")
            key_mouse_manager.click_point(*self.calc_point(MASK["strange_name"], res[0][strange_index]))
            key_mouse_manager.click_point(1658, 962)
            key_mouse_manager.wait()
        else:
            can_use_list=[i for i in range(len(res[0])) if i not in black_index_list]
            if len(can_use_list)>0:
                CUS_LOGGER.debug(f"任意选择第{can_use_list[0]}个奇物")
                key_mouse_manager.click_point(*self.calc_point(MASK["strange_name"], res[0][can_use_list[0]]))
                key_mouse_manager.click_point(1658, 962)
                key_mouse_manager.wait()
            else:
                CUS_LOGGER.warning(f"极差情况，选择第{black_first}个奇物,齿轮或大乐透")
                key_mouse_manager.click_point(*self.calc_point(MASK["strange_name"], res[0][black_first]))
                key_mouse_manager.click_point(1658, 962)
                key_mouse_manager.wait()

    # 作弊选项窗：点击「作弊」按钮后弹出的窗口。寰宇蝗灾中各命途骰面效果不一样，但窗口布局一致；
    # 要选哪个效果由各模式在点「作弊」按钮前写进 self.cheat_target。
    # 「窗口还在不在」一律现查一次：click_text(text="作弊", box=[923, 230, 996, 270],
    # click=False, allow_fail=True) 只 OCR 窗口顶部标题那一小块、不会点击；
    # 窗口开着的整个期间状态机会反复触发，所以这个判断不能缓存。

    def cheat_option_entries(self):
        """
        识别作弊列表里每个骰面效果的标题（以「【」开头，如【丰饶·慈怀】）；
        返回 [{"raw_text": ..., "box": [左,上,右,下]}]（按阅读顺序）。
        只对窗口内的列表区域做一次区域 OCR，返回的 box 是窗口内的实际像素。
        """
        entries = []
        # 列表区域：窗口内的效果列表（可滚动），连同底部按钮都在框内，不用再细分
        for res in self.ts.find_with_box(
                box=[420, 240, 1500, 960], forward=True, re_screen=True):
            if not isinstance(res, dict):
                continue
            text = (res.get("raw_text") or "").strip()
            # 只认行标题，说明文字一律不要
            if not text.startswith("【"):
                continue
            entries.append({"raw_text": text, "box": [int(v) for v in res["box"]]})
        return entries

    def find_cheat_option(self, keywords):
        """
        在作弊界面选项列表里找目标骰面效果那一行的标题，找不到返回 None。
        """
        keywords = tuple(k for k in keywords if k)
        if not keywords:
            return None
        for entry in self.cheat_option_entries():
            if any(k in entry["raw_text"] for k in keywords):
                return entry
        return None

    def click_cheat_option(self, entry):
        """
        点作弊效果那一行的文字中心，返回被点中的文字。
        位置落在作弊界面选项列表区域外就放弃。
        """
        x = (entry["box"][0] + entry["box"][2]) / 2
        y = (entry["box"][1] + entry["box"][3]) / 2
        # 列表区域，和 cheat_option_entries 里识别时用的同一个框
        left, top, right, bottom = [420, 240, 1500, 960]
        if not (left <= x <= right and top <= y <= bottom):
            CUS_LOGGER.error(f"作弊效果「{entry['raw_text']}」位置 ({x:.0f}, {y:.0f}) 不在作弊界面选项列表区域内，放弃点击")
            return None
        CUS_LOGGER.debug(f"点击作弊效果：「{entry['raw_text']}」")
        key_mouse_manager.click_point(x, y, box=entry["box"])
        key_mouse_manager.wait()
        return entry["raw_text"]

    def cheat_option_selected(self, entry):
        """判断作弊界面选项列表里指定选项是不是真的被选中了：被选中的行整条会高亮成紫色。"""
        screen = self.get_screen()
        # 行卡片左右 [470, 1450]、上下 = 标题 y-8 ~ 标题 y+88，卡片自身高约 100 px。
        x0 = 470
        x1 = min(1450, int(screen.shape[1]))
        title_top = int(entry["box"][1])
        y0 = max(title_top - 8, 0)
        y1 = min(title_top + 88, int(screen.shape[0]))
        if x1 - x0 < 10 or y1 - y0 < 10:
            return False
        patch = np.ascontiguousarray(screen[y0:y1, x0:x1])
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        # 高亮紫在 HSV 里的下界/上界
        mask = cv.inRange(hsv, np.array((120, 60, 60), dtype=np.uint8),
                          np.array((145, 255, 255), dtype=np.uint8))
        ratio = float(mask.mean()) / 255
        CUS_LOGGER.debug(f"作弊效果「{entry['raw_text']}」的高亮紫色占比：{ratio:.2f}")
        # 大于阈值才允许点击确认，经实测占比约 0.41~0.51，而未高亮的为 0，故此处设为0.3
        return ratio >= 0.3

    def select_cheat_option(self, keywords, skip_first_ocr=False):
        """
        在作弊界面选项列表里选中目标骰面效果并校验选中，返回被点中的那段文字；没找到返回 None。

        每屏一次区域 OCR 认行标题；认出目标行就点该行、再用 cheat_option_selected 高亮校验。
        点击没选中就在同一屏重试，最多五次；一屏没认到目标行就往下滚一屏再认。

        skip_first_ocr=True 时先不认、直接把列表往下滚一屏再进循环：目标只可能在列表靠后的位置时
        （铁血战士只用得到最后一行的「肉体帝侯」），第一屏那次识别纯属浪费。
        """

        def scroll_down():
            # 没认出目标行就把列表往下滚三行再看。用滚轮不用拖拽：拖拽松手后有惯性，
            # 列表在截图之后还在滑，按截图坐标点击就会点偏；滚轮没有惯性，滚完等一会儿
            # 画面就停了。落点用识别列表时那个框的中心，往列表上滚，别滚到底部按钮上。
            left, top, right, bottom = [420, 240, 1500, 960]
            key_mouse_manager.scroll_point((left + right) // 2,(top + bottom) // 2,direct=-15,)
            key_mouse_manager.wait()
            key_mouse_manager.sleep(0.3)

        # 列表最多 6 行、一屏能看 3 行；滚一格约 40 px、一行约 155 px，所以一次滚 15 格约三行，
        # 到底会被夹住，多滚无害。不跳过首屏时从顶部往下扫 3 屏够扫完整张表；
        # 跳过首屏时已经先滚掉一屏，扫 2 屏就够。
        CUS_LOGGER.debug(f"作弊：目标骰面{keywords}")
        if skip_first_ocr:
            CUS_LOGGER.debug("跳过首次识别，先把作弊列表往下滚一屏")
            scroll_down()
        for _ in range(2 if skip_first_ocr else 3):
            if self.find_cheat_option(keywords) is None:
                scroll_down()
                continue
            # 认出目标行后就一直在这一屏重选到选中为止，同一屏最多重点 5 次
            retries = 5
            while not self._stop and retries > 0:
                retries -= 1
                entry = self.find_cheat_option(keywords)
                if entry is None:
                    CUS_LOGGER.warning(f"作弊列表里又认不到目标行{keywords}了，再试一次")
                    continue
                selected = self.click_cheat_option(entry)
                if selected is not None and self.cheat_option_selected(entry):
                    return selected
                CUS_LOGGER.warning(f"点了作弊效果「{selected or keywords}」但未检测到高亮，再点一次")
            CUS_LOGGER.error("重试五次仍未点击成功，可能是网络卡顿")
            return None
        CUS_LOGGER.warning(f"作弊界面选项列表未找到目标骰面效果{keywords}")
        return None

    def confirm_cheat_dialog(self, tries=2):
        """点作弊窗的「确认」按钮。"""
        for _ in range(tries):
            # 作弊窗收起有淡出动画，实测必须等 0.05 秒
            time.sleep(0.05)
            if not self.click_text(text="作弊", box=[923, 230, 996, 270], click=False, allow_fail=True):
                CUS_LOGGER.debug("作弊选项窗已关闭")
                return True
            entry = None
            # 底部「确认」的区域；左侧「取消」不在框内
            for res in self.ts.find_with_box(box=[900, 700, 1520, 1030], forward=True, re_screen=True):
                if not isinstance(res, dict) or "确认" not in (res.get("raw_text") or ""):
                    continue
                if entry is None or res["box"][3] > entry["box"][3]:
                    entry = res      # 取框内最下面那个「确认」：按钮在窗口底部
            if entry is None:
                CUS_LOGGER.warning("作弊选项窗里没识别到「确认」按钮，窗口可能已关闭")
                return False
            x = (entry["box"][0] + entry["box"][2]) / 2
            y = (entry["box"][1] + entry["box"][3]) / 2
            key_mouse_manager.click_point(x, y, box=entry["box"])
            key_mouse_manager.wait()
        # 刚点完的「确认」也要等淡出，否则标题还认得出来，会被误判成没关窗
        time.sleep(0.05)
        if self.click_text(text="作弊", box=[923, 230, 996, 270], click=False, allow_fail=True):
            CUS_LOGGER.warning("作弊选项窗未正常关闭，可能仍在淡出，下一轮重新处理")
            return False
        return True

    def cheat(self, skip_first_ocr=False):
        """
        在作弊选项窗里选出作弊目标骰面效果并确认。
        点「作弊」按钮、等窗口弹出都写在各模式的 calculated_roll 里，点完直接回主循环。
        关键字用效果名本身，和列表行标题里的写法一致（如【毁灭·肉体帝侯】）；
        目标由各模式在点「作弊」按钮前写进 self.cheat_target。

        skip_first_ocr 原样转给 select_cheat_option：目标只可能在列表靠后位置时省掉第一屏识别。
        """
        keywords = (self.cheat_target,) if self.cheat_target else ()
        selected = self.select_cheat_option(keywords, skip_first_ocr)
        if selected is None:
            CUS_LOGGER.warning(f"作弊界面选项列表里没有找到目标骰面效果{keywords}，关掉作弊选项窗")
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            self.cheat_target = None
            return
        if self.confirm_cheat_dialog():
            CUS_LOGGER.debug(f"已在作弊界面选择：{selected}")
            self.cheat_target = None
        else:
            # 点中了但没确认成功：保留目标，窗口若还开着等下一轮再确认
            CUS_LOGGER.warning(f"作弊效果「{selected}」已点中，但没确认成功")

    def select_doing(self):
        text = self.ts.find_with_box(box=[557, 447, 747, 474], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"当前效果{text}")
        # 无命途专属效果可处理，放弃
        self.abandon_confirm(confirm=True)
        if self.click_text(text="选择移动目标", box=[1609, 965, 1759, 996], click=False, allow_fail=True):
            CUS_LOGGER.info("是带着无法被改变的过往，背负它走向未来的决心。")
            return

    def choose_bless(self):
        for _ in range(4):
            img_down = self.get_small_interaction_img(MASK["bless_path"], fresh=True)
            if self.ts.split_and_find(self.tk.fates, img_down)[1] or self._stop:
                break
            CUS_LOGGER.debug("未识别到命途")
            if not self.click_text(text="选择祝福",box=[60, 0, 222, 113],click=False,ocr_line=False,warning=False):
                return 1
        img_up = self.get_small_interaction_img(MASK["bless_name"], fresh=True)
        res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, bless_skip=self.tk.skip)
        img_down = self.get_small_interaction_img(MASK["bless_path"])
        res_down = self.ts.split_and_find(self.tk.secondary, img_down, mode="bless")
        if res_up[1] == 2:
            CUS_LOGGER.debug("识别到具体祝福")
            key_mouse_manager.click_point(*self.calc_point(MASK["bless_name"], res_up[0]))
            key_mouse_manager.wait()
        elif res_down[1] >= 2:
            CUS_LOGGER.debug("识别到匹配命途")
            key_mouse_manager.click_point(*self.calc_point(MASK["bless_path"], res_down[0]))
            key_mouse_manager.wait()
        elif self.click_text(text="选择祝福",box=[60, 0, 222, 113],click=False,ocr_line=False,warning=False,allow_fail=True):
            CUS_LOGGER.debug("未识别到具体祝福,随便选一个")
            key_mouse_manager.click_point(*self.calc_point(MASK["bless_name"], res_up[0]))
            key_mouse_manager.wait()
        self.click_text(text="确认",box=[1663, 949, 1719, 979],need_fresh=False,ocr_line=True,warning=True)
        key_mouse_manager.wait()
        return 1

    def select_go(self):
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("move_w")
        key_mouse_manager.wait()
        if self.click_text(text="选择移动目标", box=[1609, 965, 1759, 996],click=False,allow_fail=True):
            if self.click_text(text="点击空白处关闭", box=[876, 1008, 1047, 1035],click=False,allow_fail=True):
                CUS_LOGGER.info("「下一世，真理定会解明，死生……将有序流转。」")
                key_mouse_manager.wait()
                return
            self.try_analysis_map(mode=2)
            if self.next_node is not None:
                self.start_nodes=self.next_node
                x,y=int(self.next_node["cx"]),int(self.next_node["cy"])
                key_mouse_manager.click_point(x,y)
                key_mouse_manager.wait()
                self.click_text(text="确认移动", box=[1611, 964, 1759, 998])
                if self.area != "" and self.now_map!=-1:
                    visit_count = self.record_map_visit(self.now_map)
                    CUS_LOGGER.debug(f"上次地图编号{self.now_map}, 累计访问次数: {visit_count}")
            else:
                CUS_LOGGER.error("未找到下一步路径点")
        else:
            self.click_text(text="确认移动", box=[1611, 964, 1759, 998])
        # 移动后原节点的区域名已失效：init_map 只在 new_node 为真时清 area，
        # 而它通常已被上一节点消费掉，这里必须自己清
        self.area=""
        self.new_node=True
        # 已离开当前地图，同一张地图的暂离计数从头开始
        self.fail_count = 0

    def read_action_counts(self):
        """
        读骰面界面右下角的「重投次数」「作弊次数」，返回 (重投次数, 作弊次数)，认不到的为 None。

        作弊功能要通关寰宇蝗灾才解锁。没解锁时界面上只剩「重投次数」一项、整行居中显示，
        正常那两个点位都认不到数字，所以两边都没认到时再在居中那个位置认一次：
        认到了就是没解锁——提示玩家，然后按 0 次作弊、识别到的重投次数继续往下走。

        先只认不落样本：居中点位认到了就说明那两个点位本来就是空白，不该给模板目录
        添两张空图；三个点位都认不到才回去按老规矩各存一份，方便以后补模板。
        """
        roll_count = match_roll_count_in_region(self.screen, save_unmatched=False)
        cheat_count = match_cheat_count_in_region(self.screen, save_unmatched=False)
        if roll_count is None and cheat_count is None:
            locked_roll = match_locked_roll_count_in_region(self.screen, save_unmatched=False)
            if locked_roll is not None:
                CUS_LOGGER.warning("您当前尚未解锁作弊功能。请及时通关寰宇蝗灾以获得最佳体验")
                CUS_LOGGER.debug(f"当前重投次数: {locked_roll}")
                return locked_roll, 0
            match_roll_count_in_region(self.screen)
            match_cheat_count_in_region(self.screen)
        if roll_count is not None:
            CUS_LOGGER.debug(f"当前重投次数: {roll_count}")
        if cheat_count is not None:
            CUS_LOGGER.debug(f"当前作弊次数: {cheat_count}")
        return roll_count, cheat_count

    def calculated_roll(self):
        if self.nodes is None or self.plane_floor==-1:
            self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
            key_mouse_manager.wait()
            return
        self.read_action_counts()
        if not self.check("fast_roll",1674,100, threshold=0.9):
            self.click_text(text="快速投掷", box=[1700, 80, 1823, 117])
        self.click_text(text="确认效果", box=[1584, 961, 1687, 994])
        self.init_map()
        self.mini_state = 1

    def init_map(self):
        super().init_map()
        self.special_interaction_failures.clear()
        self.native_special_map_root = None
        self.loaded_map_root = None
        CUS_LOGGER.debug(f"是否新节点: {self.new_node}")
        if self.new_node:
            self.fail_count = 0
            self.node_count+=1
            if self.area:
                self.now_area.append(self.area)
            CUS_LOGGER.debug(f"已走过: {self.now_area}")
            self.event = ""
            self.new_node=False

    def strange_shop(self):
        img = self.get_small_interaction_img(MASK["strange_name"], fresh=True)
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
            elif '齿星系' in strange or '分裂咕咕钟' in strange or '血锦之纪' in strange or '星际大乐透' in strange or '机械齿轮' in strange:
                black_index_list.append(i)
        for i in strange_index_list:
            key_mouse_manager.click_point(*self.calc_point(MASK["strange_name"], res[0][i]))
            key_mouse_manager.click_point(1658, 962)
            key_mouse_manager.wait()
            for _ in range(5):
                self.click_text(text="点击空白", box=[872, 729, 1048, 1015],warning=False)
        key_mouse_manager.press("esc")

    # 命途选项卡 →「确定」按钮的手量固定偏移：选项卡是固定尺寸的单行卡片（不折行），所以这个偏移一直准；
    # 事件路径的「确定」贴在会折行的选项文本下方，两处不能共用一个偏移，见 AnyFateUniverse.confirm_point
    def select_secret(self):
        # 点击优先级：对话条金色 ▼ →「选择」栏白色箭头 → 命途选项卡 → 都不在时点「秘闻」
        if self.check("arrow_dialog", mask=MASK["dialog"], fresh=True):
            key_mouse_manager.click_point(self.tx, self.ty, box=self.tb)
            return
        # 图标（白色右箭头、命途选项卡）都在左侧图标列，与 select_event 用同一套区域
        if self.check("arrow", mask=MASK["event_icon"], fresh=True):
            key_mouse_manager.click_point(self.tx, self.ty, box=self.tb)
            return
        success = False
        CUS_LOGGER.info("没错，我们会尽己所能将其诠释：比世界的命运更为沉重之物……")
        for i in range(1,9):
            if self.check(f"fate{i}", mask=MASK["event_icon"], threshold=0.95, fresh=True):
                success=True
                break
        if not success:
            # 两个图标都没匹配上：在「秘闻」文字所在位置点一下
            CUS_LOGGER.info("「救世主」…在命运三相神谕的语境下，这张牌意味着谐调和完美无缺。")
            self.click_text(text="秘闻", box=[197, 887, 233, 906])
            return
        # 命途选项卡已经出现：先用「选项卡 → 确定」的固定偏移快速点一下，再由 confirm_event 用文字识别复核
        CUS_LOGGER.info("原来那浑身着火的恶魔，满脑子幻想的都是要成为「救世主」哪！")
        key_mouse_manager.click_point(self.tx, self.ty, box=self.tb)
        # 固定偏移：x 固定 1696 是按钮中心，y = 选项卡 y + 123
        self.confirm_event(point=(1696, self.ty + 123), timeout=0.5)

    # 寰宇命途（以及铁血战士、弹指一挥）的选项除了普通选项的星号（※），个别事件还会给某个选项
    # 配一张自己的命途图标。只认星号会漏掉这一条，优选项就永远匹配不上，所以这里补上八个命途图标。
    def extra_option_icon_names(self):
        """
        第一遍没命中优选项时额外补认的图标：fate1~fate8。
        """
        return tuple(f"fate{i}" for i in range(1, 9))

    def select_event(self):
        """事件界面：先处理弹窗/推进图标/选项，选项处理完再记节点日志。"""
        screen = self.get_screen()
        if self.check("arrow_dialog", mask=MASK["dialog"]):
            key_mouse_manager.click_point(self.tx, self.ty, box=self.tb)
            return
        for photo in ("arrow", "arrow_1", "shop_herta"):
            if self.check(photo, mask=MASK["event_icon"]):
                key_mouse_manager.click_point(self.tx, self.ty, box=self.tb)
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
            if self._option_shown_at is not None and time.time() - self._option_shown_at < 1.5:
                # 选项面板是淡入的：先出选项文字、后出选项图标，在这不到 1.5 s 的窗口里按兜底点会点错。
                # 所以本帧先不决定，也不 sleep：直接返回，下一帧重新截图重新认，
                # 那时图标已经正常显示，优选项自然就命中了。等满 1.5 s 还没命中才照旧走兜底。
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

        # 节点日志：选项处理完落到这里才记录，避免选项还没点完就写日志
        if self.new_node:
            event_name = self.ts.find_with_box(box=[185, 953, 750, 1008], forward=True, re_screen=False)
            if any(isinstance(ev, dict) and "阮·梅" in ev.get("raw_text", "") and "其二" in ev.get("raw_text", "") for ev in event_name):
                self.ruanmei2 = True#本轮遭遇「阮·梅（其二）」，本轮视频将保留
            if any(isinstance(ev, dict) and "超验" in ev.get("raw_text", "") for ev in event_name):
                self.chaoyan_seen = True#本轮进过「超验之镜」（事件/奖励共用，不可重复），后续奖励遇战权重降为0.2
            if self.area!="" and self.area!="休整" and len(event_name)!=0:
                try:
                    db_file = os.path.join(PATHS["backup"], "node_log.db")
                    os.makedirs(PATHS["backup"], exist_ok=True)
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

    def emergency(self):
        self.nodes = None # 清除地图缓存
        event_name = self.ts.find_with_box(box=[897, 500, 1023, 540], forward=True, re_screen=False)
        if len(event_name)==0:
            self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "event"))
            # self.stop()
            CUS_LOGGER.warning("未识别到突发事件文本，可能是战斗变虫群的突发事件，已截图保存")
        try:
            db_file = os.path.join(PATHS["backup"], "emergency.db")
            os.makedirs(PATHS["backup"], exist_ok=True)
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
        db_file = os.path.join(PATHS["backup"], "map_visits.db")
        os.makedirs(PATHS["backup"], exist_ok=True)
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

    # 放弃骰子效果
    def abandon_confirm(self, confirm=False, allow_fail=False):
        # 停止后不再向键鼠队列加入任何新操作。
        if self._stop:
            return False
        if not self.click_text(
            text="放弃",
            box=[1221, 967, 1276, 998],
            allow_fail=allow_fail,
        ):
            return False
        if not confirm:
            return True
        # 确保“放弃”已实际点击，再开始等待确认弹窗的视觉证据。
        key_mouse_manager.wait()
        if self._stop:
            return False
        appeared = self.wait_flag(
            lambda: not self.click_text(
                text="确认",
                box=[1158, 650, 1220, 690],
                click=False,
                warning=False,
                allow_fail=True,
            ),
            timeout=1.2,
        )
        # 超时、停止或未出现确认弹窗时，均不点击固定坐标
        if self._stop or not appeared:
            return False
        key_mouse_manager.click_point(1147, 676)
        # 此方法的调用点存在后续识图，统一在这里建立同步边界
        key_mouse_manager.wait()
        return True

    def auto_battle(self):
        # 需要打开自动战斗
        key_mouse_manager.press("V")
        if self.mini_state==3:
            self.mini_state=5
        if self.fate == "丰饶":
            if random.randint(0, 6) == 3:
                key_mouse_manager.press("R")
        self.update_state("battle")
        return 1

    def do_interaction(self):
        # is_killed：是否是禁用的交互（复活装置、下载装置）
        is_killed = False
        if self.check("interact", mask=MASK["interact_icon"], threshold=0.96, fresh=True):
            for _ in range(4):
                img = self.get_small_interaction_img(MASK["interact_text"])
                text = self.ts.similar_list(self.tk.interacts, img)
                if text is None:
                    img = self.get_small_interaction_img(MASK["interact_text_2"])
                    text = self.ts.similar_list(self.tk.interacts, img)
                if text is not None:
                    break
                self.get_screen()
            # 使用同一次交互文字裁片的结果识别黑塔。
            if text == "黑塔" or self.ts.similar("黑塔"):
                # 与黑塔交互后30秒内禁止再次交互
                if time.time() - self.quit > 30:
                    self.quit = time.time()
                    key_mouse_manager.press("interact", force=True)
                else:
                    is_killed = 1
            else:
                if self.ts.similar("区域"):
                    # tele：区域-xx  exit：离开模拟宇宙
                    CUS_LOGGER.info("「众人将与一人离别，惟其人将觐见奇迹」")
                    key_mouse_manager.press("interact", force=True)
                    return self.nof()
                is_killed = text in ["复活", "下载"]
                if not is_killed:
                    key_mouse_manager.press("interact", force=True)
            if not is_killed:
                return 1
            else:
                self.update_state("run")

    def select_start_bless(self):
        """选择开局奖励。

        复用本帧整屏 OCR 的结果找包含目标名字的文本框，
        点到该文本框中心；两个目标都没有时点中间。
        """
        # 正常流程里 run_static 已经做过整屏 OCR；缓存为空时补一次 OCR
        if not self.ts.res:
            self.ts.forward(self.get_screen())
        for name in ("神奇宇宙", "巨胃宇宙"):
            for res in self.ts.find_with_box(box=[511, 477, 1409, 519], redundancy=30):
                if name not in res["raw_text"]:
                    continue
                box = res["box"]
                key_mouse_manager.click_point(
                    (box[0] + box[2]) / 2,
                    (box[1] + box[3]) / 2,
                    box=box,
                )
                key_mouse_manager.click_point(948, 965)
                return
        key_mouse_manager.click_point(960, 540)
        key_mouse_manager.click_point(948, 965)

    def click_event_option(self, event_name, row, from_prior=False):
        """
        点击一条选项（row 来自 event_option_rows），位置不在选项面板里就放弃。
        与 click_text / click_box 一致，使用 OCR 返回的选项文本框中心作为点击点。
        from_prior=True 表示优选项命中（正常路径）；
        False 表示优选项都没命中、挑了一个识别到的选项兜底。
        """
        # 选项面板在右侧 [左, 上, 右, 下]（1920x1080 基准）：点击点必须落在里面才算点到了选项。
        left, top, right, bottom = [1320, 110, 1850, 1010]
        x = (row["box"][0] + row["box"][2]) / 2
        y = (row["box"][1] + row["box"][3]) / 2
        text = row["raw_text"]
        # OCR 结果有时会把选项左侧星号识别成「米」字
        if text.startswith("米"):
            text = text[1:]
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
        key_mouse_manager.click_point(x, y, box=row["box"])
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

    def confirm_point(self, row):
        """
        按被点中那条选项的文字行，推算「确定」按钮中心的 1920x1080 像素坐标。
        以选项文字行的底边当基准—，按钮贴在选中选项框的右下角。
        """
        bottom = max(line["box"][3] for line in row.get("lines") or [row])
        # 76 是按钮中心在选项文字行底边下方的距离；x 取按钮中心固定的 1702。
        return 1702, bottom + 76

    def confirm_text_box(self):
        """
        在框内寻找「确定」文字，返回它的屏幕文本框 [x0,y0,x1,y1]，没有返回 None。
        find_with_box(forward=1, re_screen=True) 会重新截一帧、只对这条竖条进行 OCR。
        """
        box = [1590, 240, 1830, 1070]
        for res in self.ts.find_with_box(box=box, forward=True, re_screen=True):
            if isinstance(res, dict) and "确定" in res.get("raw_text", ""):
                return list(res["box"])
        return None

    def click_confirm_text(self, box):
        """点按钮文字框的中心（「确定」「确认」共用，与 click_text 一致，用 1920x1080 像素坐标）。"""
        center_x = (box[0] + box[2]) / 2
        center_y = (box[1] + box[3]) / 2
        key_mouse_manager.click_point(center_x, center_y, box=box)

    def confirm_event(self, event_name=None, point=None, timeout=1.5):
        """
        点掉选项框右下角浮出的「确定」按钮，事件才会真的往下走；优选项命中和兜底共用。
        point 是固定偏移算出来的按钮位置（confirm_point 的 1920x1080 像素坐标）：选项点中后按钮必然
        出现，先直接点这一下（不用识别，省一次 OCR）；点完再 OCR 复核一次——按钮文字还在就说明
        固定偏移没点中，按文字位置补点。point=None（拿不到选项框）时退回纯文字轮询。
        """
        key_mouse_manager.wait()
        if point is not None:
            key_mouse_manager.click_point(*point)
            time.sleep(0.2)  # 等游戏把「确定」按钮收掉，再复核它是不是真被点掉了
            box = self.confirm_text_box()
            if box is None:
                self._option_shown_at = None
                return True
            name = event_name or self.event_name_for_log(getattr(self, "screen", None))
            CUS_LOGGER.warning(f"事件「{name}」按固定偏移没点中「确定」，按文字识别的位置补点")
            self.click_confirm_text(box)
            self._option_shown_at = None
            return True
        tm = time.time()
        while time.time() - tm < timeout:
            box = self.confirm_text_box()
            if box is not None:
                CUS_LOGGER.debug("选项已选中，点击「确定」推进事件")
                self.click_confirm_text(box)
                self._option_shown_at = None
                return True
        return False

    def event_ui_label(self, img=None):
        """读左上角界面标题栏的文字（「事件」/「奇物商店」/「祝福强化」），读不到返回空串。"""
        if img is None:
            img = self.get_screen()
        if img is None:
            return ""
        try:
            return self.ts.ocr_one_row(img, [93, 50, 230, 100]) or ""
        except Exception as e:
            CUS_LOGGER.warning(f"界面标题识别失败：{e}")
            return ""

    def event_name_for_log(self, screen=None):
        """
        读取并缓存当前事件名，供日志使用；读不到时返回「未知事件」。

        事件名只在写日志时才有用，所以这里才去 OCR，且每次事件最多读一次
        （读到的存进 self.event 复用）。离开选项界面（选项区一个字都读不到）时
        会把 self.event 清空，下一个事件重新读。
        """
        if not getattr(self, "event", ""):
            if screen is None:
                screen = self.get_screen()
            if screen is not None:
                try:
                    name = self.ts.ocr_one_row(screen, [190, 960, 800, 1000])
                except Exception as e:  # OCR 失败不该拖垮事件流程，退回空串
                    CUS_LOGGER.warning(f"事件名识别失败：{e}")
                    name = ""
                if name:
                    name = name.strip().replace("事件", "").replace("秘闻", "").replace("修改", "")
                    name = name.strip(" 　，,。.、·:：；;！!？?「」『』[]()（）")
                    if len(name) > 1:
                        self.event = name
        return getattr(self, "event", "") or "未知事件"

    def option_icon_names(self):
        """
        第一遍要匹配的选项图标模板名。模拟宇宙的选项图标只有星号（※）。
        个别事件会给某个选项配别的图标，那种内核自己补。
        """
        return ("star",)

    def event_option_icons(self, names=None):
        """
        找出图标列里**所有**选项图标的中心，返回[{"x","y","score","icon"}]（屏幕坐标，按 y 排序，icon 是模板名）
        check() 只能拿到全局最高分的一个位置：一帧里有 3~5 条选项时只有最靠上的那个图标会被认出来。
        图标既是「选项出现了」的标志，也是每条选项横条的锚点，所以这里自己做多目标匹配，
        与 check() 完全同一个搜索区域（MASK["event_icon"]），逐个模板取所有 > 0.95 的峰值，12 px 内只留最高的那个。
        names：要匹配的图标模板名，默认就是 option_icon_names() 那一遍；补认的模板由
        extra_option_icon_names() 给出，只有第一遍没命中优选项时才会走到（见 select_event）。
        一个星号都没有说明这一帧不是选项界面，补认的模板那时也不匹配。
        """
        names = self.option_icon_names() if names is None else tuple(names)
        region = MASK["event_icon"]
        local = crop_region(self.screen, region)
        left, top = region[0], region[1]
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

    def drop_disabled_options(self, rows):
        """
        丢掉置灰（当前不可用）的选项行，只留正常亮度的选项。

        游戏用置灰表示选项此刻不可用，所以它不能进入优选项匹配和兜底候选，否则会永久卡在事件界面。
        亮度取每个选项标题文字框里最亮的通道值（V = max(R,G,B)）：标题笔画很细，均值会被
        大片深色背景稀释；按通道峰值而不是灰度，金色等彩色标题也不会被误判成置灰。
        一帧里所有选项一样亮（面板淡入、或本来就只认到一条）时全部保留。

        Args:
            rows: event_option_rows 识别出的选项行，每行含 "box"（标题文字的屏幕框）与 "raw_text"。

        Returns:
            亮度达标的选项行，顺序不变；整帧没有亮度信息（全黑）时原样返回。
        """
        if not rows:
            return rows
        h, w = self.screen.shape[:2]
        brightness = []
        for row in rows:
            x1, x2 = max(int(row["box"][0]), 0), min(int(row["box"][2]), w)
            y1, y2 = max(int(row["box"][1]), 0), min(int(row["box"][3]), h)
            patch = self.screen[y1:y2, x1:x2]
            brightness.append(int(patch.max()) if patch.size else 0)
        top = max(brightness)
        if top == 0:
            # 整帧全黑说明没有亮度信息可比较（例如测试里的空白画面），此时不做取舍。
            return rows
        kept = [row for row, value in zip(rows, brightness) if value * 5 >= top * 3]
        dropped = [row for row, value in zip(rows, brightness) if value * 5 < top * 3]
        if dropped:
            CUS_LOGGER.debug(
                "跳过不可用（置灰）的选项：" + "、".join(row["raw_text"] for row in dropped)
            )
        return kept

    def event_option_rows(self, fresh=False, names=None):
        """
        按每条选项左侧的图标（模拟宇宙里就是星号 ※）只 OCR 它右侧的横条，返回识别到且可点的选项行。
        每行 = {"raw_text": 选项文字, "box": 选项文字行的屏幕框,
        "lines": 这一条读到的全部文字行, "icon": 图标位置}。
        选项文字一定在图标右侧，所以只认与图标同一行的选项文字。
        左边包含 ※ 在内：正屏 OCR 会把 ※ 和选项文字并进同一个文本框，
        横条左缘必须容得下它，否则 box_contain 过滤不出来。
        置灰（不能点）的选项在这里就被丢掉，所以调用方拿到的都是能点出反应的选项。
        names：交给 event_option_icons 的图标模板名，默认 option_icon_names() 那一遍。
        """
        panel_right = 1850
        rows = []
        for icon in self.event_option_icons(names):
            band = [
                int(icon["x"] - 30),
                int(icon["y"] - 30),
                panel_right,
                int(icon["y"] + 20),
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
            lines.sort(key=lambda res: res["box"][1])
            row = dict(lines[0])  # 第一行才是选项文字，下面是说明文字
            row["lines"] = lines
            row["icon"] = icon
            rows.append(row)
        rows.sort(key=lambda row: row["box"][1])
        return self.drop_disabled_options(rows)

    def drop_strange(self):
        key_mouse_manager.click_point(1015, 486)
        key_mouse_manager.click_point(1663, 969)
        self.wait_flag(lambda: self.click_text(text="丢弃奇物",box=[10, 0, 220, 112],click=False,ocr_line=False,warning=False), 1.4)

    def drop_bless(self):
        st = set(self.tk.fates) - set(self.tk.secondary)
        clicked = 0
        for i, ft in enumerate(self.tk.secondary[::-1]):
            if ft != self.fate or i == len(self.tk.secondary):
                img_down = self.get_small_interaction_img(MASK["bless_path"], fresh=True)
                if self.debug == 2:
                    CUS_LOGGER.debug(f"St: {list(st)}, Secondary: {self.tk.secondary}")
                res_down = self.ts.split_and_find(list(st), img_down, mode="bless")
                if res_down[1] == 2:
                    key_mouse_manager.click_point(*self.calc_point(MASK["bless_path"], res_down[0]))
                    clicked = 1
                    break
                st.add(ft)
        if not clicked:
            key_mouse_manager.click_point(1015, 486)
        key_mouse_manager.click_point(1689, 962)

    def enhance(self):
        self.quit = time.time()
        for i in [None, (387, 343), (603, 343)]:
            if self.check("enhance_fail",1715,982, fresh=True):
                break
            if i is not None:
                key_mouse_manager.click_point(i[0], i[1])
            key_mouse_manager.click_point(1711, 980)
            tm = time.time()
            while not self.click_text(text="祝福强化",box=[70, 9, 236, 125],click=False,ocr_line=False,warning=False) and time.time() - tm < 7:
                key_mouse_manager.click_point(1524, 858)
        key_mouse_manager.press("esc")

    def confirm_yes(self):
        """
        点掉弹窗上的「确认」按钮。点击位置只取这一帧 OCR 到的「确认」文字块。
        这一帧没认到就不点，等下一帧重新识别。
        """
        # 若处于作弊界面，则不点「确认」
        if self.click_text(text="作弊", box=[923, 230, 996, 270], click=False, allow_fail=True):
            CUS_LOGGER.debug("当前处于作弊选项窗，跳过点击「确认」")
            return 0
        # 在弹窗中找「确认」按钮的文字框 [左,上,右,下]; re_screen=True 让这里每次独立截一帧。
        rows = [
            row for row in self.ts.find_with_box(box=[232, 154, 1690, 928], forward=True, re_screen=True)
            if isinstance(row, dict) and "确认" in (row.get("raw_text") or "")
        ]
        # 弹窗标题里也可能带「确认」（如「确认丢弃祝福「X」？」），按钮永远在标题下方，所以取最靠下的那一块文字。
        box = list(max(rows, key=lambda row: row["box"][3])["box"]) if rows else None
        if box is None:
            CUS_LOGGER.warning("没识别到弹窗的「确认」文字，等下一帧重试")
            return 0
        self.click_confirm_text(box)
        key_mouse_manager.wait()
        return 0

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
        return res

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
        if self.click_text(text="模拟宇宙",box=[1231, 595, 1360, 631],click=False,allow_fail= True):
            CUS_LOGGER.info("已在办公室，打开模拟宇宙")
            key_mouse_manager.press("interact")
            return
        CUS_LOGGER.info("前往黑塔办公室：打开地图")
        key_mouse_manager.press("map")

    def goto_survival_room(self):
        key_mouse_manager.turn(15)
        key_mouse_manager.keyDown("move_w")
        sprint()
        key_mouse_manager.sleep(4)
        key_mouse_manager.keyUp("move_w")
        key_mouse_manager.wait()
        self.update_state("survival_room")

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
        init_time = time.time()
        while True:
            key_mouse_manager.wait()
            CUS_LOGGER.info(f"{factor}请求：「成为回应世界期许，背负众人心愿的人。」")
            if self._stop == 1:
                key_mouse_manager.keyUp("move_w")
                break
            if self.mini_state > 1:
                key_mouse_manager.keyUp("move_w")
                key_mouse_manager.wait()
            self.get_screen()
            have_f=self.check("interact", mask=MASK["interact_icon"], threshold=0.96)
            if not have_f:
                CUS_LOGGER.info("响应：「一个孑然一身的人。」")
                key_mouse_manager.keyDown("move_w")
            if have_f:
                if self.mini_state <=1:
                    key_mouse_manager.keyUp("move_w")
                judge, _ = self.good_f()
                if judge:
                    key_mouse_manager.keyUp("move_w")
                    key_mouse_manager.press("interact")
                    key_mouse_manager.wait()
                    self.should_update_map = False
                    first_visit = self.mini_state <= 1
                    if self.nof(must_be="challenge"):
                        CUS_LOGGER.info(f"最后一次，{factor}回想起那个朝阳初升的时刻，自己曾刻下理想的雏形…")
                        key_mouse_manager.keyUp("move_w")
                        if not self.is_run():
                            break
                        if first_visit:
                            self.mini_state += 2
                            self.need_away = True
                            self.leave_universe(leave_away=True, keep_status=True)
                            self.should_update_map = False
                            return
                        self.should_update_map = True
                        self.is_find_end = self.move_to_end(mode=2, device=1)
                        if self.is_find_end:
                            continue
                        break
                else:
                    CUS_LOGGER.info(f"{factor}为它取另外一个名字——「救世主」。而他自己的名，就此在记忆中零落。")
            if not self.is_run():
                key_mouse_manager.keyUp("move_w")
                self.should_update_map = False
                key_mouse_manager.wait()
                CUS_LOGGER.info("警告：进度无法更新,检测到其它界面,退出循环")
                return
            if time.time()-init_time>run_wait_time:
                CUS_LOGGER.warning("警告：等待时间超时,"+("不" if not self.has_target else "")+"存在「毁灭」目标")
                key_mouse_manager.keyUp("move_w")
                self.mini_state+=2
                if self.mini_state>=7:
                    # self.last_interact_time = 0
                    self.should_update_map = False
                    # key_mouse_manager.press('esc')
                    # key_mouse_manager.wait()
                    # self.update_state("ui")
                    return
                break
        key_mouse_manager.keyUp("move_w")
        self.update_state("check")
        self.should_update_map = False
        return


def create_engine(*, script=False):
    return AnyFateUniverse()
