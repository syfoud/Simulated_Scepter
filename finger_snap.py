import os
import shutil
import time

import yaml

from any_fate import AnyFateUniverse
from tool.countdown_config import (
    EARLY_STOP_FIELDS, MC_SETTING_FIELDS, load_finger_snap_settings,
)
from tool.countdown_evaluator import (
    CountdownDecisionAgent,
    DECISION_MC,
    DECISION_WIN_RATE,
    DECISION_WIN_RATE_DP,
    EFFECT_CHEAT_TEXT,
    EFFECT_NAMES,
    EFFECT_NOTHING,
    EFFECT_SELECT,
    MCConfig,
    PHASE_EFFECT,
    PHASE_TARGET,
    format_action,
    parse_effect_text,
)
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.simul.config import config
from tool.simul.text_key import text_keys
from tool.utils.analysis_map import (
    build_rightward_graph2,
    compute_start_point_from_crop,
    detect_corner_markers,
    detect_infectable_nodes,
    match_multiple_targets,
    save_analysis_map_debug,
)
from tool.utils.Error import NoBossError, NoMatchError
from tool.utils.image_tool import find_image_by_name
from tool.utils.ocr_num import (
    extract_number,
    match_cheat_count_in_region,
    match_numbers_in_region,
    match_roll_count_in_region,
)


class FingerSnap(AnyFateUniverse):
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
        self._target_decided = False
        CUS_LOGGER.info("令她感伤的是，永恒的生命没能让她积累无穷的智慧，反倒是那些曾被她视作珍瑰的事物，开始变得模糊，一去不返。。。")
        config_file = "config/config/event_info3.yml"
        example_file = "config/config/info_example.yml"
        if not os.path.exists(config_file) and os.path.exists(example_file):
            shutil.copy2(example_file, config_file)

        with open(config_file, encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["event"]
    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            need_del=(self.del_record_time and self.del_record_time>self.countdown) and not self.ruanmei2
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.countdown}，本轮阮梅其二{self.ruanmei2}")
            self.recorder.stop_recording(need_del)
            time.sleep(0.8)
            self.recorder.start_recording(self.count + 1)
            self.update_state("re_start")
        self.countdown = 15
        self.countdown_agent.reset()
        self._cheat_count = self._reroll_count = 0
        self._pending_target = None
        self._pending_cheat_effect = None
        self._target_decided = False
        self.fail_match_count=0
        self.node_count = 0
        self._ruanmei_er2_seen = False
    def select_fate(self):
        self.click_text(text="丰饶", box=[824, 877, 784, 814])
    def update_count(self, read=True):
        """
        更新或读取弹指模块的计数器值（使用 count.txt 的第二行）
        """
        file_name = "config/backup/count.txt"
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
            lines[1] = str(new_cnt) + "\n"
            try:
                with open(file_name, "w", encoding="utf-8") as file:
                    file.writelines(lines)
                self.count = new_cnt
            except Exception as e:
                CUS_LOGGER.error(f"写入弹指计数失败 {e}")
    def end_of_university(self):
        self.update_count(False)
        self.my_cnt += 1
        tm = int((time.time() - self.init_time) / 60)
        remain_round = self.nums - self.my_cnt
        if remain_round > 0:
            remain = int(remain_round * (time.time() - self.init_time) / self.my_cnt / 60)
        else:
            remain = 0
            remain_round = "∞"
            CUS_LOGGER.info(f'当仁不让。{factor}将肩负世界，直至此身焚灭。')
        CUS_LOGGER.info(
            f"世界演算模拟完成！本轮已迭代次数：{self.my_cnt},总计已迭代次数:{self.count} 剩余:{remain_round}次, 已执行：{tm // 60}小时{tm % 60}分钟  平均{tm // self.my_cnt}分钟一次" + (
                f"预计剩余{remain // 60}小时{remain % 60}分钟" if remain != 0 else ""))
        if self.check_bonus == 0 and self.my_cnt >= self.nums > 0:
            self.end = 1
        self.update_floor(1)
        self.update_state("end")
        elapsed = int(time.time() - self.run_start_time)
        record_file = "config/backup/countdown.txt"
        try:
            os.makedirs("config/backup", exist_ok=True)
            with open(record_file, "a", encoding="utf-8") as file:
                file.write(f"轮回次数:{self.count}, 倒计时:{self.countdown}, 用时:{elapsed // 60}分{elapsed % 60}秒\n")
        except Exception as e:
            CUS_LOGGER.error(f"写入倒计时记录文件失败{e}")
        self.run_start_time = time.time()  # 开始下一局计时
        self.need_end=False
        self.init_map()
        if self.countdown>=80:
            if self.count>10000:
                CUS_LOGGER.info("跨越此世的所有恨与爱，为故事写下新的篇章吧♪")
            elif self.count>1000:
                CUS_LOGGER.info("而记忆，化作往昔的涟漪，向着明日荡去。")
            elif self.count>100:
                CUS_LOGGER.info("迷迷，等待。开拓，世界！")
            self.stop()
            CUS_LOGGER.info("恭喜，您获得了弹指一挥！")
        else:
            CUS_LOGGER.info(f'{factor}再度踏上轮回……')

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
            except (NoMatchError, NoBossError):
                return
            self.countdown_agent.locked_effect = EFFECT_SELECT
            advice = self.countdown_agent.recommend_target()
            if advice is None:
                CUS_LOGGER.debug("慈怀已无可感染节点，放弃本次目标选择。")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
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
        key_mouse_manager.keyUp("w")
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
            self.new_node=True
        else:
            self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
            self.new_node=True
    def initing_map(self):
        if not self.debug:
            CUS_LOGGER.error("本功能为实验性功能，当前仅供开发人员测试，现已终止程序")
            return self.stop()
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
        self.save_screen(save_path=f"/temp/map{self.plane_floor}/")
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
            self.node_count = 0
        key_mouse_manager.wait()
    def try_analysis_map(self, mode=1, target_selection=False):
        # if self.debug:
        #     self.save_screen(not_now=True)
        image = self.screen
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
                self.save_screen(not_now=True, save_path="/temp/bigmaperror/")
                self.save_screen(save_path="/temp/bigmaperror/")
                raise NoMatchError
        # 检测角标（pig/reinforce/alienation等），关联到最近节点
        corner_results = detect_corner_markers(image, matches)
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
        else:
            raise NoBossError
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
        roll_count = match_roll_count_in_region(self.screen)
        if roll_count is not None:
            self._reroll_count = int(roll_count)
            CUS_LOGGER.debug(f"当前重投次数: {roll_count}")
        cheat_count = match_cheat_count_in_region(self.screen)
        if cheat_count is not None:
            self._cheat_count = int(cheat_count)
            CUS_LOGGER.debug(f"当前作弊次数: {cheat_count}")
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
            self._pending_cheat_effect = None
            if observed == pending_effect:
                CUS_LOGGER.debug(
                    f"作弊效果“{EFFECT_NAMES[pending_effect]}”已回显，直接确认，不重复决策")
                self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
                self.init_map(self.new_node)
                self.mini_state = 1
                return
            CUS_LOGGER.warning(
                f"作弊效果回显不一致：预期“{EFFECT_NAMES[pending_effect]}”，"
                f"实际“{EFFECT_NAMES[observed]}”，取消锁定并按实际效果重新决策")
            self.countdown_agent.locked_effect = None
        if observed is None:
            CUS_LOGGER.warning("无法确认骰子效果，本次不消耗资源并按无效果继续")
            self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
            self.countdown_agent.apply_effect_action(EFFECT_NOTHING, "keep")
            self.init_map(self.new_node)
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
            self.click_text(text="作弊", box=[1261, 1321, 761, 792])
            self.countdown_agent.apply_effect_action(observed, action)
            self._pending_cheat_effect = int(action[1])
            self._cheat_count = self.countdown_agent.state.cheat_rem
            return

        self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
        self.countdown_agent.apply_effect_action(observed, action)
        self.init_map(self.new_node)
        self.mini_state = 1

    def cheat(self):
        """在作弊界面选择评估模型已决定的具体效果。"""
        effect = self.countdown_agent.locked_effect
        if effect is None:
            CUS_LOGGER.error("进入作弊界面时没有待应用的模型效果")
            key_mouse_manager.press("esc")
            return
        name = EFFECT_NAMES[effect]
        candidates = (EFFECT_CHEAT_TEXT[effect],)
        selected = None
        for attempt in range(2):
            selected = next((candidate for candidate in candidates
                             if self.click_text(text=candidate, allow_fail=True,need_fresh=True)), None)
            if selected:
                break
            key_mouse_manager.drag(0.5, 0.4, 0.5, 0.6)
            key_mouse_manager.wait()
        if not selected:
            CUS_LOGGER.error(f"作弊界面未找到推荐效果“{name}”，重试")
            self._pending_cheat_effect = None
            self.countdown_agent.locked_effect = None
            key_mouse_manager.press("esc")
            return
        self.click_text("确认", box=[1168, 1223, 811, 841], allow_fail=True)
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
                self.click_text(text="放弃", box=[1221, 1276, 967, 998], allow_fail=True)
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
