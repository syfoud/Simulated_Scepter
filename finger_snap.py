import os
import shutil
import time

import yaml

from iron_blood import IronBloodUniverse
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.utils.analysis_map import (
    build_rightward_graph2,
    compute_all_max_steps,
    compute_start_point_from_crop,
    detect_corner_markers,
    detect_infectable_nodes,
    display_matches,
    evaluate_best_single_replacement,
    match_multiple_targets,
    max_weight_path,
)
from tool.utils.Error import NoBossError, NoMatchError
from tool.utils.image_tool import find_image_by_name
from tool.utils.ocr_num import (
    extract_number,
    match_cheat_count_in_region,
    match_numbers_in_region,
    match_roll_count_in_region,
)


class FingerSnap(IronBloodUniverse):
    def __init__(self):
        super().__init__()
        self.countdown=15
        CUS_LOGGER.info("令她感伤的是，永恒的生命没能让她积累无穷的智慧，反倒是那些曾被她视作珍瑰的事物，开始变得模糊，一去不返。。。")
        config_file = "config/config/event_info2.yml"
        example_file = "config/config/info_example.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)

        with open(config_file, encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["event"]
    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            need_del=self.del_record_time and self.del_record_time>self.countdown
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.countdown}")
            self.recorder.stop_recording(need_del)
            time.sleep(0.8)
            self.recorder.start_recording(self.count)
            self.update_state("re_start")
        self.countdown = 15
        self.fail_match_count=0
    def select_fate(self):
        self.click_text(text="丰饶", box=[824, 877, 784, 814])
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
                CUS_LOGGER.info("寰宇或为您的意志撼动，但「毁灭」的道路，注定无法手捧鲜花……")
            elif self.count>1000:
                CUS_LOGGER.info("…不必考量本心，不必渴求胜利，只须知道，铁血战士——让人感到愤怒！")
            elif self.count>100:
                CUS_LOGGER.info("无所谓，旅途本就会改变一个人。")
            self.stop()
            CUS_LOGGER.info("恭喜，您获得了弹指一挥！")
        else:
            CUS_LOGGER.info(f'{factor}再度踏上轮回……')

    def select_doing(self):
        text = self.ts.find_with_box(box=[557, 747, 447, 474], forward=True, re_screen=False)
        text = merge_text(text) if len(text) else ""
        CUS_LOGGER.debug(f"当前效果{text}")
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996], click=False, allow_fail=True):
            CUS_LOGGER.info("要用爱铭记我。")
            return
        if "丰饶" in text:
            #一律放弃
            self.click_text(text="放弃", box=[1221, 1276, 967, 998])
    def select_go(self):
        num = extract_number(match_numbers_in_region(self.screen))
        if num is not None:
            num=int(num)
            if num%5==0:
                self.countdown=num//5
            else:
                CUS_LOGGER.warning("不能整除5的参数")
                return
        else:
            CUS_LOGGER.warning("未知的被动效果参数")
            return
        time.sleep(2)#阻塞式等待播完动画，有待优化
        num = extract_number(match_numbers_in_region(self.get_screen()))
        if num is None or int(num)%5!=0:
            return
        else:
            num = int(num)
            countdown=num // 5
            if countdown!=self.countdown:
                return
        CUS_LOGGER.debug(f"当前倒计时{self.countdown}")
        self.set_kill_num(str(self.countdown))
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
                if self.countdown==0:
                    self.need_end=True
            self.new_node=True
        else:
            self.click_text(text="确认移动", box=[1611, 1759, 964, 998])
            self.new_node=True
    def initing_map(self):
        if not self.debug:
            CUS_LOGGER.error("本功能为实验性功能，当前仅供开发人员测试，现已终止程序")
            self.stop()
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
            if self.plane_floor==1 and False:
                CUS_LOGGER.warning("如果不能将此世从「毁灭」中拯救它，那就让寰宇在愤怒中燃烧吧......")
                self.need_end=True
        self.save_screen(save_path=f"/temp/map{self.plane_floor}/")
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
        key_mouse_manager.wait()
        return
    def try_analysis_map(self,mode=1):
        # if self.debug:
        #     self.save_screen(not_now=True)
        image = self.screen
        matches = match_multiple_targets(image, mode)
        CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
        if len(matches)==0:
            CUS_LOGGER.warning("未匹配到任何地图图标却错误进入寻路阶段，可能是误识别")
            self.save_screen(not_now=True,save_path="/temp/bigmaperror/")
            self.save_screen(save_path="/temp/bigmaperror/")
            CUS_LOGGER.warning("刷新截图缓冲区后最后一次尝试匹配地图图标")
            matches = match_multiple_targets(image, mode)
            CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配")
            if len(matches) == 0:
                raise NoMatchError
        # 检测角标（pig/reinforce/alienation等），关联到最近节点
        corner_results = detect_corner_markers(image, matches)
        if corner_results:
            CUS_LOGGER.debug(f'检测到 {len(corner_results)} 个角标')
            for cr in corner_results:
                CUS_LOGGER.debug(f"  {cr['name']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']}({matches[cr['node_idx']]['name']}) dist={cr['node_dist']}")
        # 检测青绿色可传染节点
        infectable_indices = detect_infectable_nodes(self.screen, matches)
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
            if len(path)>1:
                self.next_node=path[1]
                self.max_limited=0
            self.max_change_count=0
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
            display_matches(image, matches, path=path, highlight_idx=highlight, save_path=True,
                         font_size_override=14, alt_path=alt_path)
        self.replace_idx = None
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
            if "毁灭" in text:
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
