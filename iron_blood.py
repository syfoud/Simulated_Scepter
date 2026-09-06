import datetime
import os
import shutil
import time

import yaml

from any_fate import AnyFateUniverse
from simul import SimulatedUniverse
from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.simul.config import config
from tool.simul.text_key import text_keys
from tool.utils.Error import NoBossError, NoMatchError
from tool.utils.analysis_map import evaluate_best_single_replacement
from tool.utils.image_tool import find_image_by_name
from tool.utils.ocr_num import (
    extract_number,
    match_cheat_count_in_region,
    match_numbers_in_region,
    match_roll_count_in_region,
)


class IronBloodUniverse(AnyFateUniverse):
    """铁血战士：毁灭命途专属，累计「肉体帝候」击杀数达成成就。"""

    def __init__(self):
        super().__init__()
        self.kill_count = 0
        self.early_stop = self.opt.get("early_stop", False)
        self.first_plane_count = self.opt.get("first_plane", 14)
        self.second_plane_count = self.opt.get("second_plane", 31)
        self.first_plane_min_weight = self.opt.get("first_plane_min_weight", 6)
        self.fate = "毁灭"
        self.my_fate = config.fates.index(self.fate)
        self.tk = text_keys(self.my_fate)
        # 铁血战士使用毁灭专属事件优先级
        config_file = "config/config/event_info2.yml"
        example_file = "config/config/info_example.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)
        with open(config_file, encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["event"]

    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            need_del=self.del_record_time and self.del_record_time>self.kill_count
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.kill_count}")
            self.recorder.stop_recording(need_del, battle_count=self.kill_count)
            time.sleep(0.8)
            self.recorder.start_recording(self.count + 1)
            self.update_state("re_start")
        self.kill_count = 0
        self.fail_match_count=0
        self.node_count=0
        self.chaoyan_seen = False  # 新轮回重置「超验之镜」已进过标记

    def end_of_university(self):
        SimulatedUniverse.end_of_university(self)
        elapsed = int(time.time() - self.run_start_time)
        record_file = "config/backup/kill_record.txt"
        try:
            if self.plane_floor==3:
                self.kill_count+=1
            os.makedirs("config/backup", exist_ok=True)
            with open(record_file, "a", encoding="utf-8") as file:
                now_lunhuirizhi = datetime.datetime.now()
                timestamp_lunhuirizhi = now_lunhuirizhi.strftime("%Y年%m月%d日%H点%M分%S秒")
                file.write(f"{timestamp_lunhuirizhi}, 轮回次数:{self.count}, 击杀数:{self.kill_count:02d}, 用时:{elapsed // 60}分{elapsed % 60}秒\n")
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
        更新或读取计数器值（铁血战士使用 count.txt 的第一行）
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

    def select_fate(self):
        self.click_text(text="毁灭",box=[1263, 1317, 791, 821])

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
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
            self.node_count=0
        key_mouse_manager.wait()
        return

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
