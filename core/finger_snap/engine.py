import json
import os
import shutil
import time

from route import PATHS
from tool.storage import resource_path
from core.any_fate.engine import AnyFateUniverse
from core.finger_snap.config import (
    EARLY_STOP_FIELDS, MC_SETTING_FIELDS, load_finger_snap_settings,
)
from tool.countdown_evaluator import (
    CountdownDecisionAgent,
    DECISION_MC,
    DECISION_WIN_RATE,
    DECISION_WIN_RATE_DP,
    EFFECT_NAMES,
    EFFECT_NOTHING,
    EFFECT_SELECT,
    MCConfig,
    PHASE_EFFECT,
    PHASE_TARGET,
    format_action,
    parse_effect_text,
)
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from core.simulated.config import config
from core.simulated.text_key import text_keys
from tool.utils.analysis_map import (
    build_rightward_graph2,
    compute_start_point_from_crop,
    detect_corner_markers,
    detect_infectable_nodes,
    match_multiple_targets,
    save_analysis_map_debug,
)
from tool.utils.Error import NoMatchError
from tool.utils.image_tool import find_image_by_name
from tool.utils.ocr_num import (
    extract_number,
    match_numbers_in_region,
)


class FingerSnap(AnyFateUniverse):
    """弹指一挥：丰饶命途专属，累计80倒计时以达成成就。"""

    def __init__(self):
        super().__init__()
        self.fate = "丰饶"
        self.my_fate = config.fates.index(self.fate)
        self.tk = text_keys(self.my_fate)
        self.countdown=15
        model_settings = load_finger_snap_settings()
        mode = model_settings["decision_mode"]
        self.first_plane_threshold = float(model_settings.get("first_plane_threshold", 0.0))
        self.del_record_time = int(model_settings.get("record_keep_count", 31))
        self.countdown_early_stop = model_settings[EARLY_STOP_FIELDS[mode]]
        self.countdown_agent = CountdownDecisionAgent(
            MCConfig(**{key: model_settings[key] for key in MC_SETTING_FIELDS}),
            model_settings["plane_targets"], mode,
            mode != "dp" and self.countdown_early_stop)
        self._cheat_count = self._reroll_count = 0
        self._pending_target = None
        self._pending_cheat_effect = None
        self._cheat_confirmed_effect = None
        self._cheat_requested_effect = None
        self._cheat_requested_at = 0.0
        self._target_decided = False
        CUS_LOGGER.info("令她感伤的是，永恒的生命没能让她积累无穷的智慧，反倒是那些曾被她视作珍瑰的事物，开始变得模糊，一去不返。。。")
        event_finger_snap = resource_path(__file__, "config/event_finger_snap.json")

        with open(event_finger_snap, encoding="utf-8", errors="ignore") as f:
            self.event_prior = json.load(f)["event"]
    def restart_recording(self):
        super().restart_recording()
        self.countdown = 15
        self.countdown_agent.reset()
        self._cheat_count = self._reroll_count = 0
        self._pending_target = None
        self._pending_cheat_effect = None
        self._cheat_confirmed_effect = None
        self._cheat_requested_effect = None
        self._cheat_requested_at = 0.0
        self._target_decided = False
        self.cheat_target = None  # 新轮回清掉上一轮留下的作弊目标

    def stop_round_recording(self):
        """按倒计时决定本轮录像是否删除"""
        need_del=(self.del_record_time and self.del_record_time>self.countdown) and not self.ruanmei2
        CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.countdown}，本轮是否遇到阮梅其二{self.ruanmei2}")
        self.recorder.stop_recording(need_del)
    def select_fate(self):
        self.click_text(text="丰饶", box=[824, 877, 784, 814])
    def update_count(self, read=True):
        """
        更新或读取弹指模块的计数器值（使用 count.txt 的第二行）
        """
        file_name = os.path.join(PATHS["backup"], "count.txt")
        if read:
            new_cnt = 0
            if os.path.exists(file_name):
                with open(file_name, encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                    if len(lines) >= 2:
                        try:
                            new_cnt = int(lines[1].strip())
                        except Exception:
                            pass
            else:
                os.makedirs(PATHS["backup"], exist_ok=True)
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
            lines[1] = str(new_cnt) + "\n"
            try:
                with open(file_name, "w", encoding="utf-8") as file:
                    file.writelines(lines)
                self.count = new_cnt
            except Exception as e:
                CUS_LOGGER.error(f"写入弹指计数失败 {e}")
    def end_of_university(self):
        # 本局的开始时间与用时必须在父类之前取：父类会把 run_start_time 重置为下一局的开始时间
        elapsed = int(time.time() - self.run_start_time)
        start_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.run_start_time))
        super().end_of_university()
        record_file = os.path.join(PATHS["backup"], "countdown.txt")
        try:
            os.makedirs(PATHS["backup"], exist_ok=True)
            total_min = elapsed // 60
            total_sec = elapsed % 60
            line = f"轮回次数:{self.count}, 开始时间:{start_time_str}, 用时:{total_min}分{total_sec}秒,倒计时:{self.countdown:02d}"
            with open(record_file, "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except Exception as e:
            CUS_LOGGER.error(f"写入倒计时记录文件失败{e}")
        if self.countdown>=80:
            if self.count>10000:
                CUS_LOGGER.info("跨越此世的所有恨与爱，为故事写下新的篇章吧♪")
            elif self.count>1000:
                CUS_LOGGER.info("而记忆，化作往昔的涟漪，向着明日荡去。")
            elif self.count>100:
                CUS_LOGGER.info("迷迷，等待。开拓，世界！")
            self.stop()
            CUS_LOGGER.info("恭喜，您获得了弹指一挥！")

    def select_doing(self):
        text = self.ts.find_with_box(box=[557, 747, 447, 474], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"当前效果{text}")
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996], click=False, allow_fail=True):
            CUS_LOGGER.info("要,用爱。。铭记我。。。")
            return
        upstream_target_ready = (
            self.countdown_agent.ready and self.countdown_agent.context
            and self.countdown_agent.context.phase == PHASE_TARGET)
        if not upstream_target_ready and "丰饶" not in text:
            return
        # PHASE_TARGET 只表示策略状态已进入选目标阶段，不代表当前
        # 选点界面已经识图。每次进入（以及上次点击未生效后重试）
        # 都必须用当前截图重建 mode=2 地图，不得沿用路径界面的 self.nodes。
        if not self._target_decided:
            self._pending_target = None
            try:
                if not self.try_analysis_map(mode=2, target_selection=True):
                    return
            except NoMatchError:
                return
            self.countdown_agent.locked_effect = EFFECT_SELECT
            advice = self.countdown_agent.recommend_target()
            if advice is None:
                CUS_LOGGER.debug("慈怀已无可感染节点，放弃本次目标选择。")
                self.abandon_confirm(confirm=True)
                # 若放弃点击没有生效，下次触发仍应重新识图，不永久锁死。
                self._target_decided = False
                return
            if self._log_decision(advice):
                self._pending_target = None
                self._target_decided = False
                return
            self._pending_target = int(advice.action)
            self._target_decided = True
        target = self._pending_target
        if target is None:
            return
        node = next((item for item in self.nodes if item["idx"] == target), None)
        if node is None:
            CUS_LOGGER.error(f"模型推荐感染节点 #{target} 不在当前识图结果中")
            self._pending_target = None
            self._target_decided = False
            return
        key_mouse_manager.click(int(node["cx"]), int(node["cy"]))
        key_mouse_manager.wait()
        # 确认按钮在未选中节点时依然显示，且 OCR 容易误识别为“女弃”。
        # 直接点固定按钮：未选中时按钮禁用不生效，下次仍会重试选点。
        key_mouse_manager.click(1685, 982)
        key_mouse_manager.wait()
        # 不把“已发出点击”当成“界面已成功关闭”。若选点界面
        # 仍然存在，select_doing 下次被调用时必须重新截图、建图和决策。
        self._pending_target = None
        self._target_decided = False
    def select_go(self):
        num = extract_number(match_numbers_in_region(self.screen))
        if num is None:
            CUS_LOGGER.warning("未知的被动效果参数")
            return
        num = int(num)
        if num % 5:
            CUS_LOGGER.warning("不能整除5的参数")
            return
        candidate_countdown = num // 5
        time.sleep(2)  # 阻塞式等待播完动画，有待优化
        confirmed_num = extract_number(match_numbers_in_region(self.get_screen()))
        if (confirmed_num is None or int(confirmed_num) % 5
                or int(confirmed_num) // 5 != candidate_countdown):
            CUS_LOGGER.warning(
                f"被动效果参数二次校验失败，首次={num}，二次={confirmed_num}，"
                f"保留倒计时{self.countdown}")
            return
        self.countdown = candidate_countdown
        CUS_LOGGER.debug(f"当前倒计时{self.countdown}")
        self.set_kill_num(str(self.countdown))
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("move_w")
        key_mouse_manager.wait()
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996],click=False,allow_fail=True):
            if self.click_text(text="点击空白处关闭", box=[876, 1047, 1008, 1035],click=False,allow_fail=True):
                key_mouse_manager.wait()
                return
            if not self.try_analysis_map(mode=2):
                return
            if self._pending_target is not None:
                CUS_LOGGER.debug("已进入路径界面，感染结果已由当前截图同步")
            self._pending_target = None
            self._target_decided = False
            if self.next_node is not None:
                selected_idx = int(self.next_node["idx"])
                self.start_nodes=self.next_node
                x,y=int(self.next_node["cx"]),int(self.next_node["cy"])
                key_mouse_manager.click(x,y)
                key_mouse_manager.wait()
                self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
                self.countdown = self.countdown_agent.apply_path(selected_idx).countdown
                if self.area and self.now_map != -1:
                    visit_count = self.record_map_visit(self.now_map)
                    CUS_LOGGER.debug(f"上次地图编号{self.now_map}, 累计访问次数: {visit_count}")
            else:
                CUS_LOGGER.error("未找到下一步路径点")
        else:
            self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
        # 移动后原节点的区域名已失效：init_map 只在 new_node 为真时清 area，
        # 而它通常已被上一节点消费掉，这里必须自己清
        self.area = ""
        self.new_node=True
    def initing_map(self):
        if not self.debug:
            CUS_LOGGER.error("本功能为实验性功能，当前仅供开发人员测试，现已终止程序")
            return self.stop()
        key_mouse_manager.keyUp("move_w")
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
        self.save_screen(save_path=os.path.join(PATHS["temp"], "map"))
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
            self.node_count = 0
            self.new_node = True
            # 切换位面时没有重投界面出现，需清空区域名缓存
            self.area = ""
        key_mouse_manager.wait()
    def try_analysis_map(self, mode=1, target_selection=False):
        """识别地图，必要时刷新截图复核，补偿慈怀闪光造成的瞬时漏检。

        慈怀状态节点在被识别到时正处于高亮闪光动画中（约 2 帧），闪光峰值期间
        相似度会跌到收集阈值以下，boss/head 节点可能整帧漏检。识别不到 boss/head
        时刷新截图再识别一次，之后按 3 秒窗口反复复核：单次识图耗时随机型而定，
        用时间窗口而不是固定延时可让设备自行决定复核次数；窗口结束仍未识别到
        boss/head 时记一条错误日志并返回，由调用方按原有流程处理，不中断整个流程。

        Args:
            mode: 地图识别模式，1/2/3 分别对应不同位面的图标集合。
            target_selection: 是否处于慈怀选目标阶段。

        Returns:
            bool: 建图并载入决策模型成功返回 True；起点没有可用后继，或识别窗口内
                始终未识别到 boss/head 节点，返回 False。

        Raises:
            NoMatchError: 未匹配到任何地图图标，或建图失败次数过多。
        """
        tm = time.monotonic()
        refresh = False
        while not self._stop:
            # if self.debug:
            #     self.save_screen(not_now=True)
            image = self.get_screen() if refresh else self.screen
            matches = match_multiple_targets(image, mode)
            CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
            if not matches:
                self.click_text(text="点击空白处关闭", box=[875, 1047, 776, 807])
                CUS_LOGGER.warning("未匹配到任何地图图标却错误进入寻路阶段，可能是误识别")
                CUS_LOGGER.warning("刷新截图缓冲区后最后一次尝试匹配地图图标")
                image = self.get_screen()
                matches = match_multiple_targets(image, mode)
                CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
                if not matches:
                    self.save_screen(not_now=True, save_path=os.path.join(PATHS["temp"], "bigmaperror"))
                    self.save_screen(save_path=os.path.join(PATHS["temp"], "bigmaperror"))
                    raise NoMatchError
            # 检测角标（pig/reinforce/alienation等），关联到最近节点
            corner_results = detect_corner_markers(image, matches, mode)
            if corner_results:
                CUS_LOGGER.debug(f'检测到 {len(corner_results)} 个角标')
                for cr in corner_results:
                    CUS_LOGGER.debug(f"  {cr['name']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']}({matches[cr['node_idx']]['name']}) dist={cr['node_dist']}")
            # 检测青绿色可传染节点
            infectable_indices = detect_infectable_nodes(
                image, matches, target_selection=target_selection)
            if infectable_indices:
                CUS_LOGGER.debug(f'检测到 {len(infectable_indices)} 个可传染节点')
                for idx in infectable_indices:
                    CUS_LOGGER.debug(f"  节点{idx}: {matches[idx]['name']} at {matches[idx]['location']}")
            if mode==2:
                # 把当前操控角色位交给 analysis_map 优先尝试；检测结果与
                # current_role 不一致时（例如 silver_wolf_manager 在秘技点
                # 耗尽时直接按 "1" 切回一号位，未经过 switch_current_role），
                # 以检测结果为准更新 current_role，使该属性始终反映实际状态。
                center, details = compute_start_point_from_crop(
                    image, return_details=True, preferred_slot=self.current_role)
                if center is None:
                    center, details = compute_start_point_from_crop(
                        image, th=0.7, return_details=True,
                        preferred_slot=self.current_role)
                start = center
                if details is not None and details['slot'] != self.current_role:
                    CUS_LOGGER.debug(
                        f"角色位与 current_role 不一致："
                        f"current_role={self.current_role} 检测={details['slot']}，"
                        f"同步为检测结果")
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
                inf_str = ' [可传染]' if m.get('infectable', False) else ''
                CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}{cm_str}{inf_str}")
            if self.debug:
                save_analysis_map_debug(
                    image, matches, start=start,
                    tag=f"mode{mode}" + ("_sel" if target_selection else ""))
            boss_head_x = [m['location'][0] for m in matches if m['name'] in ('boss', 'head')]
            if boss_head_x:
                rightmost = max(boss_head_x)
                matches = [m for m in matches if m['location'][0] <= rightmost]
                CUS_LOGGER.debug(f"过滤boss/head右侧节点后，剩余 {len(matches)} 个匹配")
                for i, m in enumerate(matches):
                    CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}")
                break
            # 至少复核一次，之后按 3 秒窗口反复识图：单次识图耗时随机型而定，用
            # 时间窗口而非固定延时让设备自行决定复核次数；窗口结束仍识别不到时把
            # 漏检记成错误日志并返回，交给调用方按原有流程处理，不中断整个流程，
            # 单位为秒。
            if refresh and time.monotonic() - tm >= 3:
                CUS_LOGGER.error(
                    f"识图(模式{mode})在限定时间内未识别到boss/head节点，放弃本次识图")
                return False
            if not refresh:
                CUS_LOGGER.warning(
                    f"识图(模式{mode})未识别到boss/head节点，疑似慈怀闪光造成的瞬时漏检")
                CUS_LOGGER.warning("刷新截图缓冲区后在限定时间内重新匹配地图图标")
            refresh = True
        # 停机标志在识图过程中被置位时不再继续建图：既不做无意义的决策，也避免
        # 循环未跑完时 matches/start 还没赋值。
        if self._stop:
            return False
        if mode == 3:
            self.nodes, self.edges, start_idx = build_rightward_graph2(
                matches, start=start,
                max_gap=110, max_overlap=50, max_dy=130
            )
        else:
            self.nodes, self.edges, start_idx = build_rightward_graph2(
                matches, start=start
            )
        CUS_LOGGER.debug('构建图后的节点 (索引，类型，相似度，中心 x, 中心 y):')
        for n in self.nodes:
            CUS_LOGGER.debug(f"  {n['idx']}: {n['name']} sim={n.get('similarity', 0):.3f} center=({n['cx']:.1f},{n['cy']:.1f})")
        if start_idx is None or not self.nodes or not self.edges.get(start_idx):
            CUS_LOGGER.error("当前起点没有可用后继，可能是识图或建图失败")
            self.fail_match_count += 1
            if self.fail_match_count>=5:
                raise NoMatchError
            time.sleep(1)
            return False
        self.fail_match_count = 0
        node_map = {node["idx"]: node for node in self.nodes}
        infected_indices = tuple(
            node["idx"] for node in self.nodes
            if (node.get("orig") or {}).get("infectable", False))
        preserve_effect = mode in (2, 3) and self.countdown_agent.locked_effect is not None
        self.countdown_agent.load_map(
            self.nodes, self.edges, start_idx, infected_indices,
            self.countdown, self._cheat_count, self._reroll_count,
            self.plane_floor, preserve_effect=preserve_effect)
        self.start_nodes = node_map[start_idx]
        self.path = [self.start_nodes]
        self.next_node = None
        self.replace_idx = None
        if mode == 2 and not target_selection:
            advice = self.countdown_agent.recommend_path()
            if self._log_decision(advice):
                return
            self.next_node = node_map.get(int(advice.action))
            if self.next_node is None:
                raise NoMatchError(f"模型推荐节点 #{advice.action} 不在识图结果中")
            self.path.append(self.next_node)
            self.expectation_weight = advice.expected_countdown
        return True
    def calculated_roll(self):
        if self.nodes is None or self.plane_floor == -1 or not self.countdown_agent.ready:
            self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
            key_mouse_manager.wait()
            return
        if self._cheat_requested_effect is not None:
            # 刚点过「作弊」按钮、作弊还没落地（等作弊窗弹出、选行、确认）。这期间骰面还是旧效果，
            # 既不能拿去核对回显（会误判成回显不一致），也不能重新决策。
            if time.time() - self._cheat_requested_at < 5:
                CUS_LOGGER.debug("已点「作弊」按钮，等作弊窗弹出")
                return
            CUS_LOGGER.warning("点了「作弊」按钮但作弊窗一直没打开，清掉这次请求重新决策")
            self._cheat_requested_effect = None
        roll_count, cheat_count = self.read_action_counts()
        if roll_count is not None:
            self._reroll_count = int(roll_count)
        if cheat_count is not None:
            self._cheat_count = int(cheat_count)
        self.countdown_agent.sync_facts(
            countdown=self.countdown, cheat=self._cheat_count,
            reroll=self._reroll_count)
        if not self.check("fast_roll", 0.1281,0.9074, threshold=0.9):
            self.click_text(text="快速投掷", box=[1700, 1823, 80, 117])
        found = self.ts.find_with_box(
            box=[1339, 1576, 429, 464], forward=True, re_screen=False)
        text = merge_text(found) if found else ""
        observed = parse_effect_text(text)
        parsed = EFFECT_NAMES.get(observed, "未识别")
        CUS_LOGGER.debug(f"当前骰子效果：{text or '未识别'}（解析为：{parsed}）")
        pending_effect = self._pending_cheat_effect
        if pending_effect is not None:
            if observed is None:
                CUS_LOGGER.warning(
                    f"等待作弊效果“{EFFECT_NAMES[pending_effect]}”回显，当前效果无法识别")
                return
            if observed == pending_effect:
                self._pending_cheat_effect = None
                CUS_LOGGER.debug(f"作弊效果“{EFFECT_NAMES[pending_effect]}”已回显，直接确认，不重复决策")
                self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
                self.init_map()
                self.mini_state = 1
                return
            expected = EFFECT_NAMES[pending_effect]
            actual = EFFECT_NAMES[observed]
            if self._cheat_count > 0:
                # 每次确认都真实消耗 1 次作弊次数：还有余额就按同一目标重新选一次，并保留 _pending_cheat_effect
                # 让下一轮继续核对同一个目标的回显。这里只把目标重新锁回去、点开「作弊」按钮就回主循环，
                # 选行交给紧接着的「作弊界面」状态触发的 cheat()。
                CUS_LOGGER.warning(f"作弊效果回显不一致：预期“{expected}”，实际“{actual}”，作弊次数还剩{self._cheat_count}次，重新选择")
                self.countdown_agent.locked_effect = pending_effect
                self._cheat_confirmed_effect = None
                if self.click_text(text="作弊", box=[1261, 1321, 761, 792], allow_fail=True):
                    self._cheat_requested_effect = pending_effect
                    self._cheat_requested_at = time.time()
                return
            self._pending_cheat_effect = None
            CUS_LOGGER.warning(f"作弊效果回显不一致：预期“{expected}”，实际“{actual}”，取消锁定并按实际效果重新决策")
            self.countdown_agent.locked_effect = None
        if observed is None:
            CUS_LOGGER.warning("无法确认骰子效果，本次不消耗资源并按无效果继续")
            self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
            self.countdown_agent.apply_effect_action(EFFECT_NOTHING, "keep")
            self.init_map()
            self.mini_state = 1
            return

        advice = self.countdown_agent.recommend_effect(observed)
        if self._log_decision(advice):
            return
        action = advice.action
        # 第一位面保底阈值：MC/胜率模式下，非keep推荐与keep均分差距≤阈值时改用keep
        if (self.plane_floor == 1
                and self.countdown_agent.decision_mode in (
                    DECISION_MC, DECISION_WIN_RATE, DECISION_WIN_RATE_DP)
                and action != "keep"
                and self.first_plane_threshold > 0):
            keep_alt = next((alt for alt in advice.alternatives if alt[0] == "keep"), None)
            if keep_alt is not None:
                keep_mean = keep_alt[1]
                diff = advice.expected_countdown - keep_mean
                if diff <= self.first_plane_threshold:
                    CUS_LOGGER.debug(
                        f"第一位面策略阈值：推荐{format_action(PHASE_EFFECT, action)}"
                        f"(均分{advice.expected_countdown:.3f})与keep"
                        f"(均分{keep_mean:.3f})差距{diff:.3f}≤阈值"
                        f"{self.first_plane_threshold}，改用keep")
                    action = "keep"
        if action == "reroll":
            self._pending_cheat_effect = None
            self.click_text(text="重投", box=[1599, 1657, 760, 795])
            self.countdown_agent.apply_effect_action(observed, action)
            self._reroll_count = self.countdown_agent.state.reroll_rem
            return
        if isinstance(action, tuple) and action[0] == "cheat":
            target_name = EFFECT_NAMES.get(action[1], action[1])
            if not self.click_text(text="作弊", box=[1261, 1321, 761, 792], allow_fail=True):
                CUS_LOGGER.warning(f"没点到「作弊」按钮（当前骰面效果：{parsed}，目标效果：{target_name}），等下一轮重新决策")
                return
            # 「作弊」按钮点下去后窗口约 0.3 s 弹出，这里记完账就回主循环：
            # 状态机认到「作弊界面」标题后会用 cheat_target 调 cheat() 去选行。
            # 这一刻作弊还没落地（窗口没弹、行没选、确认没点），所以只记「已请求」，
            # 等 cheat() 真的确认了才记 _pending_cheat_effect 去核对回显。
            self.cheat_target = target_name
            self.countdown_agent.apply_effect_action(observed, action)
            self._cheat_requested_effect = int(action[1])
            self._cheat_requested_at = time.time()
            self._cheat_confirmed_effect = None
            self._cheat_count = self.countdown_agent.state.cheat_rem
            return

        self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
        self.countdown_agent.apply_effect_action(observed, action)
        self.init_map()
        self.mini_state = 1

    def cheat(self):
        """
        在作弊选项窗里选中评估模型已决定的具体效果，只在「作弊界面」状态触发时进这里。
        定位关键字一律用效果名本身，和列表行标题里的写法一致（如【丰饶·慈怀】）。
        """
        effect = self.countdown_agent.locked_effect
        if effect is None:
            CUS_LOGGER.error("进入作弊界面时没有待应用的模型效果")
            self.cheat_target = None
            self._cheat_requested_effect = None
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            return
        name = EFFECT_NAMES[effect]
        self.cheat_target = name
        # 防状态机重复触发
        if self._cheat_confirmed_effect == effect:
            CUS_LOGGER.debug(f"作弊效果“{name}”已经确认过，忽略重复触发")
            self.cheat_target = None
            return
        selected = self.select_cheat_option((name,))
        if selected is None:
            # 没选中就不能点确认：确认一个没选中的窗口就是白扔一次作弊次数，
            # 按 esc 关窗不消耗次数，等下一轮重新决策。
            CUS_LOGGER.error(f"作弊选项窗里没选中目标效果“{name}”，取消这次作弊")
            self._pending_cheat_effect = None
            self._cheat_requested_effect = None
            self.countdown_agent.locked_effect = None
            self.cheat_target = None
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            return
        if not self.confirm_cheat_dialog():
            # 没确认成功就是作弊没落地，但行已经点中、次数也可能已经扣了，所以照样按预期效果
            # 记下 pending，下一轮按骰面回显核对；请求标记要清掉，否则会被当成还在等窗口弹出。
            CUS_LOGGER.warning(f"已点中作弊效果“{selected}”，但未能成功确认，等骰面回显核对")
            self._pending_cheat_effect = effect
            self._cheat_requested_effect = None
            self.cheat_target = None
            return
        self._pending_cheat_effect = effect
        self._cheat_confirmed_effect = effect
        self._cheat_requested_effect = None
        self.cheat_target = None
        CUS_LOGGER.debug(f"已在作弊界面选择：{selected}")

    def _log_decision(self, advice):
        decision_mode = self.countdown_agent.decision_mode
        target = self.countdown_agent.target_countdown
        if (self.countdown_early_stop and advice.dp_upper_bound is not None
                and advice.dp_upper_bound < target) and self.gwypzmgzcndqlp:
            self.need_end = True
            CUS_LOGGER.warning(
                f"DP理论最大CD {advice.dp_upper_bound:.0f} 无法达到"
                f"第{self.plane_floor}位面目标CD {target:.0f}，终止本轮演算")
            # 效果与目标界面按原流程收尾；路径界面继续完成选路。
            # 只有回到 normal 主界面后，才由既有结束流程按 Esc 并暂离。
            if advice.context.phase == PHASE_EFFECT:
                self.click_text(text="确认效果", box=[1584, 1687, 961, 994], allow_fail=True)
            elif advice.context.phase == PHASE_TARGET:
                self.abandon_confirm(confirm=True, allow_fail=True)
            else:
                return False
            key_mouse_manager.wait()
            return True
        win_rate = "--" if advice.win_rate is None else f"{advice.win_rate:.4%}"
        mode = {"mc": "MC均分", "win_rate": "MC胜率",
                "win_rate_dp": "MC胜率/全零DP", "dp": "DP"}[decision_mode]
        metric = "理论最大CD" if mode == "DP" else "预测最终CD"
        action = format_action(advice.context.phase, advice.action)
        if advice.action == "reroll" and advice.planned_effect is not None:
            action += f"→期望摇到{EFFECT_NAMES[advice.planned_effect]}"
        samples = (f"DP状态={advice.sample_count:,}" if mode == "DP" else
                   f"控制/评价={advice.control_rollouts:,}/{advice.evaluation_rollouts:,}")
        if decision_mode in (DECISION_WIN_RATE, DECISION_WIN_RATE_DP):
            samples += (
                f"，有效胜率≥"
                f"{self.countdown_agent.config.win_rate_noise_floor_percent:.4f}%")
        if advice.dp_upper_bound is not None and decision_mode != "dp":
            samples += f"，DP上限={advice.dp_upper_bound:.0f}"
        CUS_LOGGER.debug(
            f"[{mode}] {action}，"
            f"{metric}={advice.expected_countdown:.3f}，胜率={win_rate}，"
            f"{samples}")
        for action, mean, rate, count in sorted(
                advice.alternatives, key=lambda item: (-item[1], str(item[0]))):
            CUS_LOGGER.debug(
                f"  {format_action(advice.context.phase, action)}: "
                f"均分={mean:.3f} 胜率={'--' if rate is None else f'{rate:.4%}'} n={count}")
        return False


def create_engine(*, script=False):
    return FingerSnap()
