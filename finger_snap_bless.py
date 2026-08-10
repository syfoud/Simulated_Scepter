"""
丰饶倒计时优化覆盖类，独立于 finger_snap.py（不继承它）。
第二位面：开局勘察(洞/前半场慈怀/前3步奖励) -> 铺满阶段(浇灌/对症) ->
为善阶段；阮2检测在 select_event 里做单点检查；倒计时>=70自动停止。
"""

import os
import time

import cv2
import numpy as np

from iron_blood import IronBloodUniverse
from tool.GLOBAL import key_mouse_manager, factor
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.utils.Error import NoMatchError, NoBossError
from tool.utils.analysis_map import (
    match_multiple_targets, detect_corner_markers, compute_start_point_from_crop,
    max_weight_path, build_rightward_graph2, compute_all_max_steps,
    evaluate_best_single_replacement,
)
from tool.utils.ocr_num import (
    extract_number, match_numbers_in_region,
    match_roll_count_in_region, match_cheat_count_in_region,
)
from tool.utils.image_tool import find_image_by_name


def detect_infectable_nodes(color_image, matches, pad=6, cyan_ratio_threshold=0.20,
                             b_min=120, g_min=95):
    """检测节点周围是否有青绿色光晕（判断该节点当前是否已处于"慈怀"状态）。"""
    if color_image is None or not matches:
        for m in matches:
            m['infectable'] = False
        return []

    infectable_nodes = []
    for i, m in enumerate(matches):
        x, y = m.get('location', (0, 0))
        w, h = m.get('size', (0, 0))
        x1 = max(0, int(x) - pad)
        y1 = max(0, int(y) - pad)
        x2 = min(color_image.shape[1], int(x) + w + pad)
        y2 = min(color_image.shape[0], int(y) + h + pad)
        roi = color_image[y1:y2, x1:x2]
        if roi.size == 0:
            m['infectable'] = False
            continue

        b, g, r = cv2.split(roi.astype(np.float32))
        cyan_mask = (b > r * 1.2) & (g > r * 1.1) & (b > 80) & (g > 60)
        cyan_ratio = cyan_mask.sum() / cyan_mask.size
        b_mean, g_mean = float(b.mean()), float(g.mean())

        is_infectable = (b_mean > b_min and g_mean > g_min and cyan_ratio > cyan_ratio_threshold) \
                        or (g_mean > 130 and b_mean > 100)
        m['infectable'] = is_infectable
        CUS_LOGGER.debug(
            f"[慈怀色值] 节点{i}({m.get('name')}) loc={m.get('location')} "
            f"B={b_mean:.0f} G={g_mean:.0f} cyan_ratio={cyan_ratio:.2f} -> infectable={is_infectable}"
        )
        if is_infectable:
            infectable_nodes.append(i)

    return infectable_nodes


class FingerSnapBless(IronBloodUniverse):

    def __init__(self):
        super().__init__()
        self.countdown = 15
        self._pending_duizheng = False

        # 第二位面专属状态
        self._floor2_step = 0                  # 已走的步数
        self._floor2_survey_done = False        # 是否已经做过开局地图总览判断
        self._floor2_phase = "bless"            # "bless"强制浇灌阶段 / "weishan"强制为善阶段
        self._floor2_bless_rolls = 0            # bless阶段已经骰了几次
        self._floor2_weishan_rolls = 0          # 为善阶段已经骰了几次
        self._floor2_last_confirmed_text = None  # 上一次真正点过"确认效果"的骰面文本，用于识别重复评估
        self._floor2_reward_steps = []  # 最长路径前3步里，奖励关卡所在的步数列表
        self._floor2_reward_check_step = None  # 上面这些步数里最大的一个，走完它之后检查有没有遇到阮2
        self._floor2_reward_check_done = False  # 上面这个检查是否已经做过
        self._floor2_reward_survey_done = False  # "前3步有没有奖励"这项勘察本身是否已经做过（在select_go里做）

    # ------------------------------------------------------------------
    # 从 finger_snap.py 原样搬过来的几个方法（不是靠继承拿到的）
    # ------------------------------------------------------------------

    def select_fate(self):
        self.click_text(text="丰饶", box=[824, 877, 784, 814])

    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            need_del = self.del_record_time and self.del_record_time > self.countdown
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.countdown}")
            self.recorder.stop_recording(need_del)
            time.sleep(0.8)
            self.recorder.start_recording(self.count)
            self.update_state("re_start")
        self.countdown = 15
        self.fail_match_count = 0

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
        self.need_end = False
        self.init_map()
        if self.countdown >= 80:
            if self.count > 10000:
                CUS_LOGGER.info("寰宇或为您的意志撼动，但「毁灭」的道路，注定无法手捧鲜花……")
            elif self.count > 1000:
                CUS_LOGGER.info("…不必考量本心，不必渴求胜利，只须知道，铁血战士——让人感到愤怒！")
            elif self.count > 100:
                CUS_LOGGER.info("无所谓，旅途本就会改变一个人。")
            self.stop()
            CUS_LOGGER.info("恭喜，您获得了弹指一挥！")
        else:
            CUS_LOGGER.info(f'{factor}再度踏上轮回……')

    # ------------------------------------------------------------------
    # 地图识图 + 权重
    # ------------------------------------------------------------------

    def try_analysis_map(self, mode=1):
        image = self.screen
        matches = match_multiple_targets(image, mode)
        CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
        if len(matches) == 0:
            CUS_LOGGER.warning("未匹配到任何地图图标却错误进入寻路阶段，可能是误识别")
            self.save_screen(not_now=True, save_path=f"/temp/bigmaperror/")
            self.save_screen(save_path=f"/temp/bigmaperror/")
            CUS_LOGGER.warning("刷新截图缓冲区后最后一次尝试匹配地图图标")
            matches = match_multiple_targets(image, mode)
            CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
            if len(matches) == 0:
                raise NoMatchError

        infectable_idx = detect_infectable_nodes(image, matches)
        if infectable_idx:
            CUS_LOGGER.debug(f"检测到 {len(infectable_idx)} 个已慈怀节点: {infectable_idx}")

        corner_results = detect_corner_markers(image, matches)
        if corner_results:
            CUS_LOGGER.debug(f'检测到 {len(corner_results)} 个角标')
            for cr in corner_results:
                CUS_LOGGER.debug(f"  {cr['name']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']}({matches[cr['node_idx']]['name']}) dist={cr['node_dist']}")

        if mode == 2:
            start = compute_start_point_from_crop(image)
            if start is None:
                start = compute_start_point_from_crop(image, th=0.7)
        elif mode == 3:
            start = compute_start_point_from_crop(image, mode=mode)
            if start is None:
                start = compute_start_point_from_crop(image, mode, th=0.7)
        else:
            start = None
        CUS_LOGGER.debug(f"当前起点坐标{start}")
        for i, m in enumerate(matches):
            cm = m.get('corner_marker', None)
            cm_str = f' [角标:{cm["name"]}]' if cm else ''
            infect_str = ' [慈怀]' if m.get('infectable') else ''
            CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}{cm_str}{infect_str}")

        boss_head_x = [m['location'][0] for m in matches if m['name'] in ('boss', 'head')]
        if boss_head_x:
            rightmost = max(boss_head_x)
            matches = [m for m in matches if m['location'][0] <= rightmost]
            CUS_LOGGER.debug(f"过滤boss/head右侧节点后，剩余 {len(matches)} 个匹配")
        else:
            raise NoBossError

        if mode == 3:
            self.nodes, self.edges, start_idx = build_rightward_graph2(
                matches, start=start,
                max_gap=110, max_overlap=50, max_dy=130
            )
        else:
            self.nodes, self.edges, start_idx = build_rightward_graph2(
                matches, start=start,
                max_gap=110, max_overlap=50, max_dy=130
            )

        if self.plane_floor == 1:
            # 第一位面目标是尽量保住倒计时——把节点权重换成"踩这一步
            # 对倒计时的实际影响"：已慈怀 +1，普通节点 -3（含boss/head）。
            for n in self.nodes:
                if n['name'] == 'start':
                    continue
                if (n.get('orig') or {}).get('infectable', False):
                    n['weight'] = 1.0
                else:
                    n['weight'] = -3.0
        elif self.plane_floor == 2:
            depth = {start_idx: 0}
            queue = [start_idx]
            while queue:
                cur = queue.pop(0)
                if depth[cur] >= 3:
                    continue
                for nxt in self.edges.get(cur, []):
                    if nxt not in depth:
                        depth[nxt] = depth[cur] + 1
                        queue.append(nxt)

            for n in self.nodes:
                if n['name'] == 'start':
                    continue
                if n['name'] in ('reward', 'reward2'):
                    n['weight'] = 50.0
                    if depth.get(n['idx'], 99) <= 3:
                        n['weight'] += 200.0
                elif n['name'] == 'event':
                    n['weight'] = 5.0
                else:
                    n['weight'] = 1.0

        path, self.expectation_weight, end_idx = max_weight_path(self.nodes, self.edges, start_idx)
        if self.plane_floor == 1:
            CUS_LOGGER.debug(f"[第一位面-倒计时优先] 预计本条路径倒计时变化: {self.expectation_weight:+.0f}")
        if not path:
            CUS_LOGGER.error("未找到有效路径，可能是起点位于最右端或图构建失败")
            self.fail_match_count += 1
            if self.fail_match_count >= 5:
                raise NoMatchError
            else:
                time.sleep(1)
                return
        self.start_nodes = path[0]
        self.path = path
        if path:
            if len(path) > 1:
                self.next_node = path[1]
                self.max_limited = 0
            self.max_change_count = 0
        best_path, best_weight, best_end_idx, self.replace_idx, delta, discounted_delta = evaluate_best_single_replacement(
            self.nodes, self.edges, start_idx, t=0.3 if self.plane_floor == 3 else 0.2)
        self.steps = compute_all_max_steps(self.nodes, self.edges, start_idx)
        self.replace_idx = None

    # ------------------------------------------------------------------
    # 进入位面
    # ------------------------------------------------------------------

    def initing_map(self):
        key_mouse_manager.keyUp("w")
        if self.click_text(text="振翅", box=[10, 220, 0, 112], click=False, warning=False):
            self.plane_floor = 1
        elif self.click_text(text="浪潮", box=[10, 220, 0, 112], click=False, warning=False):
            self.plane_floor = 2
        elif self.click_text(text="消褪", box=[10, 220, 0, 112], click=False, warning=False):
            self.plane_floor = 3
        else:
            CUS_LOGGER.warning("多么绝妙的巧合。你我都心知肚明。")
            return

        if self.plane_floor == 3:
            for _ in range(5):
                self.click_text(text="进入位面", box=[907, 1009, 857, 891])
            key_mouse_manager.wait()
            CUS_LOGGER.info("[停止] 已进入第三位面，倒计时是否达标交给游戏判定，脚本已停止")
            self.stop()
            return

        if self.plane_floor == 2:
            self._floor2_step = 0
            self._floor2_survey_done = False
            self._floor2_phase = "bless"
            self._floor2_bless_rolls = 0
            self._floor2_weishan_rolls = 0
            self._pending_duizheng = False
            self._floor2_last_confirmed_text = None
            self._floor2_reward_steps = []
            self._floor2_reward_check_step = None
            self._floor2_reward_check_done = False
            self._floor2_reward_survey_done = False

        try:
            self.try_analysis_map(1)
        except (NoMatchError, NoBossError) as e:
            CUS_LOGGER.warning(f"[Initing] 开局地图识图失败({type(e).__name__})，本次跳过，等待下次重试")
            return
        if self.early_stop and self.gwypzmgzcndqlp:
            CUS_LOGGER.debug(f"当前一面最低期望{self.first_plane_min_weight}，识别到开局期望{self.expectation_weight}")
        self.save_screen(save_path=f"/temp/map{self.plane_floor}/")
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
        key_mouse_manager.wait()
        return

    # ------------------------------------------------------------------
    # 第二位面：洞检测 / 覆盖率检测 / 开局勘察
    # ------------------------------------------------------------------

    def _reachable_from_start(self):
        """从 self.start_nodes 沿 edges 做可达性 BFS，返回可达节点 idx 集合（不含起点本身）。"""
        if self.start_nodes is None:
            return set()
        start_idx = self.start_nodes["idx"]
        reachable = set()
        stack = [start_idx]
        while stack:
            cur = stack.pop()
            for nxt in self.edges.get(cur, []):
                if nxt not in reachable:
                    reachable.add(nxt)
                    stack.append(nxt)
        return reachable

    def _estimate_hex_spacing(self, points, default=115.0):
        """从当前实际识别到的节点坐标动态估算六边形网格间距（取节点间"""
        if len(points) < 3:
            return default
        dists = []
        for i, (x1, y1) in enumerate(points):
            nearest = None
            for j, (x2, y2) in enumerate(points):
                if i == j:
                    continue
                d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                if nearest is None or d < nearest:
                    nearest = d
            if nearest:
                dists.append(nearest)
        if not dists:
            return default
        dists.sort()
        return dists[len(dists) // 2]

    def _detect_holes(self, surround_threshold=5, tol_ratio=0.22):
        """粗略统计地图里"洞"（被真实格子包围的镂空位置）的数量。"""
        points = [(n['cx'], n['cy']) for n in self.nodes if n['name'] != 'start']
        if len(points) < 4:
            return 0

        spacing = self._estimate_hex_spacing(points)
        tol = max(spacing * tol_ratio, 10.0)
        dirs = [
            (spacing, 0), (-spacing, 0),
            (spacing * 0.5, spacing * 0.866), (-spacing * 0.5, spacing * 0.866),
            (spacing * 0.5, -spacing * 0.866), (-spacing * 0.5, -spacing * 0.866),
        ]

        def _has_point_near(x, y):
            for px, py in points:
                if (px - x) ** 2 + (py - y) ** 2 <= tol ** 2:
                    return True
            return False

        candidate_raw = []
        for px, py in points:
            for dx, dy in dirs:
                nx, ny = px + dx, py + dy
                if not _has_point_near(nx, ny):
                    candidate_raw.append((nx, ny))

        unique_slots = []
        for nx, ny in candidate_raw:
            if not any((nx - ux) ** 2 + (ny - uy) ** 2 <= tol ** 2 for ux, uy in unique_slots):
                unique_slots.append((nx, ny))

        hole_count = 0
        for sx, sy in unique_slots:
            occupied_dirs = sum(1 for dx, dy in dirs if _has_point_near(sx + dx, sy + dy))
            if occupied_dirs >= surround_threshold:
                hole_count += 1
        return hole_count

    def _is_floor2_covered(self):
        """当前可达范围内是否已经没有未慈怀的候选节点了（"铺满"判定）。"""
        reachable = self._reachable_from_start()
        if not reachable:
            return True
        node_map = {n["idx"]: n for n in self.nodes}
        for idx in reachable:
            n = node_map.get(idx)
            if n and not (n.get("orig") or {}).get("infectable", False):
                return False
        return True

    def _floor2_front_half_blessed_only(self):
        """命途增益开局送的初始慈怀区域是不是都挤在地图前半场（离起点近"""
        real_nodes = [n for n in self.nodes if n["name"] != "start"]
        if not real_nodes:
            return False
        blessed_x = [n["cx"] for n in real_nodes if (n.get("orig") or {}).get("infectable", False)]
        if len(blessed_x) < 2:
            return False
        xs = [n["cx"] for n in real_nodes]
        mid = (min(xs) + max(xs)) / 2
        return all(x < mid for x in blessed_x)

    def _floor2_mark_reward_steps_in_first3(self):
        """路线（self.path，已经是按第二位面权重表算出来的最长路径）"""
        if not self.path:
            return []
        return [
            step for step, n in enumerate(self.path[1:4], start=1)
            if n["name"] in ("reward", "reward2")
        ]

    def _floor2_check_holes_and_blessed(self):
        """检查"洞"和"初始2个慈怀区域是否都在前半场"，决定要不要直接重开。"""
        holes = self._detect_holes()
        CUS_LOGGER.info(f"[Floor2勘察] 检测到洞数量约为 {holes}")
        if holes > 2:
            CUS_LOGGER.info("[Floor2勘察] 洞数量超过2个，直接重开")
            self.need_end = True
            return
        if self._floor2_front_half_blessed_only():
            CUS_LOGGER.info("[Floor2勘察] 初始2个慈怀区域都在前半场，直接重开")
            self.need_end = True
            return

    def _floor2_check_reward_in_first3(self):
        """检查最长路径前3步有没有奖励，决定要不要直接重开；有奖励的话"""
        start_edge_count = len(self.edges.get(self.start_nodes["idx"], [])) if self.start_nodes else -1
        path_desc = [f"{n['name']}({n['cx']:.0f},{n['cy']:.0f})" for n in (self.path or [])]
        CUS_LOGGER.info(
            f"[Floor2勘察] 起点可达边数={start_edge_count}，"
            f"当前算出的path(共{len(self.path or [])}个节点)：{path_desc}"
        )
        reward_steps = self._floor2_mark_reward_steps_in_first3()
        if not reward_steps:
            CUS_LOGGER.info("[Floor2勘察] 最长路径前3步没有奖励关卡，直接重开")
            self.need_end = True
            return

        self._floor2_reward_steps = reward_steps
        self._floor2_reward_check_step = max(reward_steps)
        CUS_LOGGER.info(
            f"[Floor2勘察] 通过检查，前3步的奖励关卡在第{reward_steps}步，"
            f"走完第{self._floor2_reward_check_step}步后检查是否遇到阮2"
        )

    # ------------------------------------------------------------------
    # 骰子结算
    # ------------------------------------------------------------------

    def cheat(self):
        if self.plane_floor != 2:
            key_mouse_manager.drag(0.5, 0.4, 0.5, 0.8)
            key_mouse_manager.click(571, 622)
            self.click_text("确认", box=[1168, 1223, 811, 841], allow_fail=True)
            return

        want_text = self._floor2_bless_target() if self._floor2_phase == "bless" else "为善"
        found = False
        for attempt in range(4):
            if self.click_text(text=want_text, click=True, warning=False, allow_fail=True):
                CUS_LOGGER.info(f"[作弊选择] 已选中效果: {want_text}")
                found = True
                break
            key_mouse_manager.drag(0.5, 0.7, 0.5, 0.35, duration=0.3)
            key_mouse_manager.wait()
        if not found:
            CUS_LOGGER.warning(f"[作弊选择] 滚动{attempt + 1}次仍未找到目标效果({want_text})，放弃指定")
        self.click_text("确认", box=[1168, 1223, 811, 841], allow_fail=True)

    def _open_full_map(self):
        """骰子界面右下角有个图标（跟 calculated_roll 基类里"""
        self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
        key_mouse_manager.wait()
        time.sleep(1.5)
        self.get_screen()

    def _close_full_map(self):
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()

    def _floor2_pre_roll_check(self):
        """第一次骰子判断前：打开完整地图，检测洞+初始2个慈怀区域是否都"""
        self._open_full_map()
        ok = False
        try:
            self.try_analysis_map(mode=2)
            self._floor2_check_holes_and_blessed()
            ok = True
        except (NoMatchError, NoBossError) as e:
            CUS_LOGGER.warning(f"[Floor2勘察] 打开地图后仍识图失败({type(e).__name__})")
        self._close_full_map()
        return ok

    def _floor2_is_covered_via_map(self):
        """铺满阶段第4/5次骰子后，判断是否已铺满：打开地图拿一份完整、"""
        self._open_full_map()
        covered = False
        try:
            self.try_analysis_map(mode=2)
            covered = self._is_floor2_covered()
        except (NoMatchError, NoBossError) as e:
            CUS_LOGGER.warning(f"[Floor2铺满检查] 打开地图后仍识图失败({type(e).__name__})，按未铺满处理")
        self._close_full_map()
        return covered

    def _floor2_bless_target(self):
        """铺满阶段用作弊强制指定骰面时该找哪个效果：不管第几次，都指定"""
        return "浇灌"

    def _calculated_roll_floor1(self):
        """从 finger_snap.py 的 calculated_roll 原样搬过来，第一位面用"""
        if self.nodes is None or self.plane_floor == -1:
            self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
            key_mouse_manager.wait()
            return
        roll_count = match_roll_count_in_region(self.screen)
        if roll_count is not None:
            CUS_LOGGER.debug(f"当前重投次数: {roll_count}")
        cheat_count = match_cheat_count_in_region(self.screen)
        if cheat_count is not None:
            CUS_LOGGER.debug(f"当前作弊次数: {cheat_count}")
        if not self.check("fast_roll", 0.1281, 0.9074, threshold=0.9):
            self.click_text(text="快速投掷", box=[1700, 1823, 80, 117])
        if self.plane_floor in [2, 3]:
            text = self.ts.find_with_box(box=[1339, 1576, 429, 464], forward=True, re_screen=False)
            text = merge_text(text) if len(text) else ""
            CUS_LOGGER.info(f"拿去吧…我背负的一切。(当前效果{text})")
            if "毁灭" in text:
                cheating = not self.check("zero", 0.3046, 0.3324, threshold=0.95)
                redo = not self.check("zero", 0.1297, 0.3315, threshold=0.95)
                CUS_LOGGER.debug(f"决策可用动作{cheating},{redo}")
                if cheating or redo:
                    best_path, best_weight, best_end_idx, self.replace_idx, delta, discounted_delta = evaluate_best_single_replacement(
                        self.nodes, self.edges, self.start_nodes['idx'], t=0.3 if self.plane_floor == 3 else 0.2)
                    CUS_LOGGER.debug(f"期权最佳代替节点{self.replace_idx},计算替换后最佳路径{best_path}，当前节点{self.start_nodes}")
                    if len(best_path) > 1:
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

    def calculated_roll(self):
        if self.plane_floor != 2:
            self._calculated_roll_floor1()
            return

        if self.need_end:
            self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
            self.init_map()
            self.mini_state = 1
            return

        if not self._floor2_survey_done:
            if self._floor2_pre_roll_check():
                self._floor2_survey_done = True
            if self.need_end:
                self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
                self.init_map()
                self.mini_state = 1
                return

        if not self.check("fast_roll", 0.1281, 0.9074, threshold=0.9):
            self.click_text(text="快速投掷", box=[1700, 1823, 80, 117])

        text = self.ts.find_with_box(box=[1339, 1576, 429, 464], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"[Floor2骰面] 阶段={self._floor2_phase} 当前效果={text}")

        if text and text == self._floor2_last_confirmed_text:
            CUS_LOGGER.warning(f"[Floor2骰面] 检测到跟上次相同的骰面文本({text})，怀疑确认没生效，重新点一次确认")
            self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
            self.init_map()
            self.mini_state = 1
            return

        if self._floor2_phase == "bless":
            if self._floor2_bless_rolls == 0:
                want_ok = ("浇灌" in text) or ("对症" in text)
            else:
                want_ok = "浇灌" in text
        else:
            want_ok = "为善" in text

        if not want_ok:
            cheating = not self.check("zero", 0.3046, 0.3324, threshold=0.95)
            redo = not self.check("zero", 0.1297, 0.3315, threshold=0.95)
            CUS_LOGGER.debug(f"[Floor2骰面] 不满足要求，作弊可用={cheating}，重投可用={redo}")
            if redo:
                self.click_text(text="重投", box=[1599, 1657, 760, 795])
                return
            elif cheating:
                self.click_text(text="作弊", box=[1261, 1321, 761, 792])
                return
            else:
                CUS_LOGGER.warning(f"[Floor2骰面] 作弊/重投用完了还没换到想要的骰面({text})，重开")
                self.need_end = True
                self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
                self.init_map()
                self.mini_state = 1
                return

        self._floor2_last_confirmed_text = text
        self.click_text(text="确认效果", box=[1584, 1687, 961, 994])
        self.init_map()
        self.mini_state = 1

        if self._floor2_phase == "bless":
            self._floor2_bless_rolls += 1
            if self._floor2_bless_rolls >= 4:
                covered = self._floor2_is_covered_via_map()
                if covered or self._floor2_bless_rolls >= 5:
                    self._floor2_phase = "weishan"
                    CUS_LOGGER.info(
                        f"[Floor2] 铺满阶段结束（第{self._floor2_bless_rolls}次骰子，"
                        f"当前可达范围已铺满={covered}），切换为强制为善"
                    )
                else:
                    CUS_LOGGER.info(
                        f"[Floor2] 第{self._floor2_bless_rolls}次骰子后仍未铺满，继续强制浇灌"
                    )
        elif self._floor2_phase == "weishan":
            self._floor2_weishan_rolls += 1
            CUS_LOGGER.info(f"[Floor2] 为善第{self._floor2_weishan_rolls}次已确认")
            if self._floor2_weishan_rolls >= 4:
                CUS_LOGGER.info("[停止] 为善阶段已经骰满4次，脚本停止等待手动接管")
                self.stop()

    # ------------------------------------------------------------------
    # 事件识别（阮2）
    # ------------------------------------------------------------------

    _REWARD_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "floor2_reward_events.txt")

    def _log_reward_event(self, node_type, text):
        """把奖励格子遇到的事件名追加写到脚本同目录下的txt文件里，"""
        try:
            with open(self._REWARD_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t"
                    f"第{self._floor2_step}步\t类型={node_type}\t事件名={text}\n"
                )
        except Exception as e:
            CUS_LOGGER.warning(f"[奖励记录] 写入失败: {e}")

    def select_event(self):
        if self.plane_floor == 2 and self.new_node:
            event_name = self.ts.find_with_box(box=[191, 750, 963, 998], forward=True, re_screen=False)
            text = merge_text(event_name) if len(event_name) else ""
            node_type = self.start_nodes.get("name") if self.start_nodes else None
            CUS_LOGGER.debug(f"[Floor2事件-预检] 节点类型={node_type} 文本={text}")

            if node_type in ("reward", "reward2"):
                self._log_reward_event(node_type, text)

            if "阮" in text:
                CUS_LOGGER.info(f"[阮2] 检测到目标事件: {text}，交互前停止程序等待手动处理")
                self.stop()
                return
        super().select_event()

    # ------------------------------------------------------------------
    # 骰面效果处理（慈怀/对症/自动生效）
    # ------------------------------------------------------------------

    def select_doing(self):
        text = self.ts.find_with_box(box=[557, 747, 447, 474], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"当前效果{text}")

        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996], click=False, allow_fail=True):
            return

        if "慈怀" in text:
            self._open_full_map()
            try:
                self.try_analysis_map(mode=2)
            except (NoMatchError, NoBossError) as e:
                CUS_LOGGER.warning(f"[慈怀] 打开地图后识图失败({type(e).__name__})，放弃本次")
                self._close_full_map()
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
                self.click_text(text="确定", box=[1584, 1687, 961, 994], allow_fail=True)
                return

            clean_start = self.start_nodes

            def _type_priority(name):
                if name in ("reward", "reward2"):
                    return 2
                if name == "event":
                    return 1
                return 0

            target = None
            best_weight = float("-inf")
            best_priority = -1
            best_distance = float("inf")
            start_idx = clean_start["idx"] if clean_start else None
            if start_idx is not None:
                start_cx = clean_start["cx"]
                reachable = self._reachable_from_start()
                candidates = [
                    n for n in self.nodes
                    if n["idx"] in reachable
                    and not (n.get("orig") or {}).get("infectable", False)
                ]
                for n in candidates:
                    orig_weight = n["weight"]
                    n["weight"] = 1.0
                    _, total_weight, _ = max_weight_path(self.nodes, self.edges, start_idx)
                    n["weight"] = orig_weight
                    priority = _type_priority(n["name"])
                    distance = n["cx"] - start_cx
                    is_better = (
                        total_weight > best_weight + 1e-6
                        or (
                            abs(total_weight - best_weight) <= 1e-6
                            and priority > best_priority
                        )
                        or (
                            abs(total_weight - best_weight) <= 1e-6
                            and priority == best_priority
                            and distance < best_distance
                        )
                    )
                    if is_better:
                        best_weight = total_weight
                        best_priority = priority
                        best_distance = distance
                        target = n
                CUS_LOGGER.debug(
                    f"[慈怀-全图搜索] 可达且未慈怀的候选节点{len(candidates)}个，"
                    f"最优选择预计路径权重={best_weight:+.1f}，节点类型={target['name'] if target else None}"
                )

            offset = None
            if target is not None and clean_start is not None:
                offset = (target["cx"] - clean_start["cx"], target["cy"] - clean_start["cy"])

            self._close_full_map()

            if offset is None:
                CUS_LOGGER.info("[慈怀] 未找到可施加的未慈怀节点，放弃本次")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
                self.click_text(text="确定", box=[1584, 1687, 961, 994], allow_fail=True)
                return

            self.get_screen()
            sel_start = compute_start_point_from_crop(self.screen)
            if sel_start is None:
                sel_start = compute_start_point_from_crop(self.screen, th=0.7)
            if sel_start is None:
                CUS_LOGGER.warning("[慈怀] 在选择界面上定位起点失败，放弃本次")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
                self.click_text(text="确定", box=[1584, 1687, 961, 994], allow_fail=True)
                return

            x = int(sel_start[0] + offset[0])
            y = int(sel_start[1] + offset[1])
            key_mouse_manager.click(x, y)
            key_mouse_manager.wait()
            self.click_text(text="确认目标", box=[1635, 1735, 968, 996])
            CUS_LOGGER.info(f"[慈怀] 已选中最优节点，换算后点击坐标({x},{y})")

        elif "对症" in text:
            self._pending_duizheng = True
            CUS_LOGGER.info("[对症] 检测到待触发状态，下一步移动落点选择将纳入对症收益评估")

        elif any(k in text for k in ("浇灌", "为善", "归心", "可憎")):
            CUS_LOGGER.info(f"[自动生效] {text}，无需操作")

        elif "丰饶" in text:
            self.click_text(text="放弃", box=[1221, 1276, 967, 998])
            self.click_text(text="确定", box=[1584, 1687, 961, 994], allow_fail=True)

    def _spatial_neighbors(self, node, radius=160.0):
        """粗略估算某节点在地图上的"相邻"节点，用于对症效果的落点评估。"""
        cx, cy = node['cx'], node['cy']
        neighbors = []
        for n in self.nodes:
            if n is node or n['name'] == 'start':
                continue
            d = ((n['cx'] - cx) ** 2 + (n['cy'] - cy) ** 2) ** 0.5
            if d <= radius:
                neighbors.append(n)
        return neighbors

    # ------------------------------------------------------------------
    # 移动
    # ------------------------------------------------------------------

    def select_go(self):
        if (
            self.plane_floor == 2
            and self._floor2_reward_check_step is not None
            and not self._floor2_reward_check_done
            and self._floor2_step >= self._floor2_reward_check_step + 1
        ):
            self._floor2_reward_check_done = True
            CUS_LOGGER.info(
                f"[Floor2] 前3步标记的奖励关卡（第{self._floor2_reward_steps}步）"
                f"已经走完并且多走了一步，没有触发阮2，直接重开"
            )
            self.need_end = True

        num = extract_number(match_numbers_in_region(self.screen))
        if num is not None:
            num = int(num)
            if num % 5 == 0:
                self.countdown = num // 5
            else:
                CUS_LOGGER.warning("不能整除5的参数")
                return
        else:
            CUS_LOGGER.warning("未知的被动效果参数")
            return
        time.sleep(2)
        num = extract_number(match_numbers_in_region(self.get_screen()))
        if num is None or int(num) % 5 != 0:
            return
        else:
            num = int(num)
            countdown = num // 5
            if countdown != self.countdown:
                return
        CUS_LOGGER.debug(f"当前倒计时{self.countdown}")

        if self.countdown >= 70:
            CUS_LOGGER.info(f"[停止] 当前倒计时{self.countdown}已经达到70，脚本停止等待手动接管")
            self.stop()
            return

        self.set_kill_num(str(self.countdown))
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("w")
        key_mouse_manager.wait()
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996], click=False, allow_fail=True):
            if self.click_text(text="点击空白处关闭", box=[876, 1047, 1008, 1035], click=False, allow_fail=True):
                CUS_LOGGER.info("「下一世，真理定会解明，死生……将有序流转。」")
                key_mouse_manager.wait()
                return
            for attempt in range(3):
                try:
                    self.try_analysis_map(mode=2)
                    break
                except (NoMatchError, NoBossError) as e:
                    CUS_LOGGER.warning(
                        f"[select_go] 寻路识图失败({type(e).__name__})，"
                        f"第{attempt + 1}/3次重新识别"
                    )
                    if attempt >= 2:
                        CUS_LOGGER.error("[select_go] 重新识别仍然失败，跳过本次，等待下次触发")
                        key_mouse_manager.keyUp("w")
                        return
                    time.sleep(1)
                    self.get_screen()

            if self.plane_floor == 2 and not self._floor2_reward_survey_done:
                if self.path and len(self.path) > 1:
                    self._floor2_reward_survey_done = True
                    self._floor2_check_reward_in_first3()
                else:
                    CUS_LOGGER.warning(
                        f"[Floor2勘察] 路径退化（长度{len(self.path) if self.path else 0}），"
                        f"本次识图作废，不计入判断，下次再试"
                    )

            if self._pending_duizheng and self.start_nodes is not None:
                node_map = {n["idx"]: n for n in self.nodes}
                step_candidates = [
                    node_map[i] for i in self.edges.get(self.start_nodes["idx"], [])
                    if i in node_map
                ]
                if step_candidates:
                    if self.plane_floor == 1:
                        best = None
                        best_total = float("-inf")
                        for cand in step_candidates:
                            changed = []
                            for nb in self._spatial_neighbors(cand):
                                if not (nb.get("orig") or {}).get("infectable", False):
                                    changed.append((nb, nb["weight"]))
                                    nb["weight"] = 1.0
                            _, total, _ = max_weight_path(self.nodes, self.edges, cand["idx"])
                            for nb, orig_w in changed:
                                nb["weight"] = orig_w
                            if total > best_total:
                                best_total = total
                                best = cand
                        if best is not None:
                            CUS_LOGGER.info(
                                f"[对症] 改选落点 {best['name']}@({best['cx']:.0f},{best['cy']:.0f})，"
                                f"模拟对症生效后预计总权重={best_total:+.1f}"
                            )
                            self.next_node = best
                    else:
                        best = None
                        best_key = None
                        for cand in step_candidates:
                            unblessed = sum(
                                1 for nb in self._spatial_neighbors(cand)
                                if not (nb.get("orig") or {}).get("infectable", False)
                            )
                            key = (unblessed, cand["weight"])
                            if best_key is None or key > best_key:
                                best_key = key
                                best = cand
                        if best is not None:
                            CUS_LOGGER.info(
                                f"[对症-Floor2] 改选落点 {best['name']}@({best['cx']:.0f},{best['cy']:.0f})，"
                                f"未慈怀邻居数={best_key[0]}"
                            )
                            self.next_node = best
                self._pending_duizheng = False

            if self.next_node is not None:
                self.start_nodes = self.next_node
                x, y = int(self.next_node["cx"]), int(self.next_node["cy"])
                key_mouse_manager.click(x, y)
                key_mouse_manager.wait()
                self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
                if self.area != "" and self.now_map != -1:
                    visit_count = self.record_map_visit(self.now_map)
                    CUS_LOGGER.debug(f"上次地图编号{self.now_map}, 累计访问次数: {visit_count}")
                if self.plane_floor == 2:
                    self._floor2_step += 1
                    self._floor2_last_confirmed_text = None
                    CUS_LOGGER.debug(f"[Floor2] 当前步数={self._floor2_step}")
            else:
                CUS_LOGGER.error("未找到下一步路径点")
            if self.early_stop and self.gwypzmgzcndqlp:
                if self.plane_floor != 3 and self.countdown == 0:
                    self.need_end = True
            self.new_node = True
        else:
            self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
            self.new_node = True

        if (
            self.plane_floor == 1
            and not self.need_end
            and self.start_nodes is not None
            and self.start_nodes.get("name") in ("boss", "head")
            and self.countdown < 15
        ):
            CUS_LOGGER.warning(
                f"[提前重开] 第一位面即将结束，当前倒计时{self.countdown}<15，"
                f"安全余量不足，提前重开本轮"
            )
            self.need_end = True