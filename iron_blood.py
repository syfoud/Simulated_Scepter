import os
import shutil
import random
from tool import EXTRA
import time
import cv2 as cv
import yaml
import json
import sqlite3
from tool.GLOBAL import key_mouse_manager, factor
from route import PATHS
from simul import SimulatedUniverse
from tool.log import CUS_LOGGER, log_emitter
from tool.public_ocr import load_actions, merge_text
from tool.utils.Error import NoMatchError
from tool.utils.analysis_map import match_multiple_targets, build_rightward_graph, compute_start_point_from_crop, \
    max_weight_path, display_matches, evaluate_best_single_replacement, compute_all_max_steps
from tool.utils.image_tool import find_image_by_name
from tool.utils.minimap_util import MINIMAP_RADIUS, get_minimap, re_get_position
from tool.utils.ocr_num import match_numbers_in_region, extract_number
from tool.utils.tool import find_latest_modified_file
from tool.window_recorder import WindowRecorder


class IronBloodUniverse(SimulatedUniverse):
    def __init__(
            self):
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, mode="r", encoding="UTF-8") as file:
                self.opt = json.load(file)
        super().__init__(find=True,speed=False,consumable=False, slow=False,debug=self.opt.get("debug", True), nums=self.opt.get("max_run_time", 0))
        self.plane_floor = -1
        self.need_record = False
        self.default_json_path = "actions/insect.json"
        self.default_json = load_actions(self.default_json_path)
        
        config_file = "config/config/event_info.yml"
        example_file = "config/config/info_example.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)
        
        with open(config_file, "r", encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["event"]
        self.action_history = []
        self.steps=None
        self.nodes=None
        self.replace_idx=None
        self.next_node = None
        self.max_limited = None
        self.kill_count =0
        self.need_end=False
        self.record = self.opt.get("recording_iron_blood", True)
        self.recorder = WindowRecorder('logs/video/', fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=self.opt.get("record_add_label", True), offsets=[10, 50, 10, 10], overlay_map=self.opt.get("record_add_label", True) and self._show_map, simul_instance=self)
        self.early_stop=self.opt.get("early_stop", False)
        self.first_plane_count=self.opt.get("first_plane", 14)
        self.second_plane_count=self.opt.get("second_plane", 31)
        self.del_record_time=self.opt.get("del_record_time", 31)
        self.max_interact_time=self.opt.get("max_interact_time", 40)
        self.area=""
        self.now_map=-1
        CUS_LOGGER.info("宇宙的中心有一团火种,它愈烧愈旺,直至燃尽整片星河。")
    
    def restart_recording(self):
        if self.record and self.cut_video and self.YKItDYvq3FpnOYx:
            self.max_limited=0 if self.max_limited is None else self.max_limited
            need_del=self.del_record_time and self.del_record_time>self.kill_count+self.max_limited
            CUS_LOGGER.debug(f"是否可删除{need_del},限制数目{self.del_record_time}，当前数目{self.kill_count+self.max_limited}")
            self.recorder.stop_recording(need_del)
            time.sleep(0.8)
            self.recorder.start_recording(self.count)
            self.update_state("re_start")
    def end_of_university(self):
        super().end_of_university()
        self.need_end=False
        self.init_map()
        self.max_limited = 0 if self.max_limited is None else self.max_limited
        if self.kill_count>=39:
            CUS_LOGGER.info("恭喜，您获得了铁血战士！")
            CUS_LOGGER.info("寰宇或为您的意志撼动，但「毁灭」的道路，注定无法手捧鲜花……")
            self.stop()


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
                with open(file_name, "r", encoding="utf-8", errors="ignore") as fh:
                    s = fh.readlines()
                    try:
                        new_cnt = int(s[0].strip("\n"))
                    except:
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
            # 追加记录轮回次数和击杀数到另一个文件
            if self.debug:
                record_file = "config/backup/kill_record.txt"
                try:
                    os.makedirs("config/backup", exist_ok=True)
                    with open(record_file, "a", encoding="utf-8") as file:
                        file.write(f"轮回次数:{self.count}, 击杀数:{self.kill_count}\n")
                        file.close()
                except Exception as e:
                    CUS_LOGGER.error(f"写入击杀记录文件失败{e}")
        self.count = new_cnt
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
            #上次交互时间
            self.last_interact_time = bk_lst_changed
            # 刚进图，初始化一些数据
            if not self.need_end:
                ocr_text = self.ts.find_with_box(box=[55, 164, 12, 40],forward=True,re_screen=False)
                self.area=merge_text(ocr_text) if len(ocr_text) else ""
                CUS_LOGGER.debug(f"当前区域{self.area}")
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
                    self.get_event_only_minimap()
                elif "休整" in self.area:
                    self.get_rest_only_minimap()
                elif "交易" in self.area:
                    self.get_shop_only_minimap()
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
    def map_data_load(self,create=True):
        create = self.debug and create
        self.big_map_init = True
        # 寻路模式，匹配最接近的地图
        self.stop_move = False
        find = True
        record=False
        #参考线太少毫无定位价值，则直接采用无地图寻路
        if self.get_blank_state()>250:
            tm=time.time()
            max_map,max_sim=-1,-1
            while time.time()-tm<2:
                self.now_map, self.now_map_sim = self.match_scr(get_minimap(self.get_screen(), radius=MINIMAP_RADIUS,copy=True))
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
            if (self.debug and self.now_map_sim < 0.5) or self.now_map_sim < 0.35:
                CUS_LOGGER.warning(f"相似度过低,疑似未找到匹配地图,匹配地图{self.now_map}")
                if create:
                    self.map_file =PATHS["image"]+ "/nmaps/my_" + str(random.randint(0, 99999)) + "/"
                    if not os.path.exists(self.map_file):
                        os.mkdir(self.map_file)
                find = False
                if self.debug:
                    record=True
            elif self.now_map !=-1 and "m" in str(self.now_map):
                CUS_LOGGER.warning(f"未完成的地图{self.now_map}")
                self.map_file = PATHS["image"] + "/nmaps/" + self.now_map + "/"
                record = True
            if find:
                files,x,y,map_num,self.upx,self.upy,target_path = find_latest_modified_file(f"{PATHS['image']}/nmaps/{self.now_map}/")
                self.big_map = cv.imread(files, cv.IMREAD_GRAYSCALE)
                self.debug_map =None
                self.now_loc = (x, y)
                self.start_pos =(x, y)
                self.pos_predictor.position=self.now_loc
                self.pos_predictor.set_now_map(map_num)
                if target_path is not None:
                    self.target = self.get_target(target_path,self.upx,self.upy)
                    self.pos_map=cv.imread(target_path)
                    CUS_LOGGER.debug("已从地图获取目标路径点%s" % self.target)
                self.rotation, d = self.pos_predictor.update_minimap_data(self.screen)
                self.init_ang = 270 + d
            elif (not find) and self.first_save_map and create:
                # 录制模式，保存初始小地图
                self.first_save_map=False
                CUS_LOGGER.warning("未找到匹配地图")
                cv.imwrite(self.map_file + "init.jpg", get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True))
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
            CUS_LOGGER.info(f"继续，燃烧下去。只要我们不曾熄灭……逐火就不会终结…")
            return
        else:
            self.update_floor(1)
    def select_fate(self):
        self.click_text(text="毁灭",box=[1263, 1317, 791, 821])
    def select_head(self):
        self.click_text(text="击败该首领",box=[1108, 1385, 267, 290])
        self.click_text(text="确认选择",box=[1633, 1733, 961, 990])
    def try_analysis_map(self,mode=1):
        if self.debug:
            self.save_screen(not_now=True)
        image = self.screen
        matches = match_multiple_targets(image, mode)
        CUS_LOGGER.debug(f"当前模式{mode},找到 {len(matches)} 个匹配:")
        if len(matches)==0:
            CUS_LOGGER.warning("未匹配到任何图标，可能是误识别")
            raise NoMatchError
        if mode==2:
            start=compute_start_point_from_crop(image)
            if start is None:
                start = compute_start_point_from_crop(image,th=0.5)
        elif mode==3:
            start = compute_start_point_from_crop(image,[1003,929,1035,965])
            if start is None:
                start = compute_start_point_from_crop(image, [1003, 929, 1035, 965],th=0.5)
        else:
            start=None
        CUS_LOGGER.debug(f"当前起点坐标{start}")
        for i, m in enumerate(matches):
            CUS_LOGGER.debug(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}")
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
        path, total_weight, end_idx = max_weight_path(self.nodes, self.edges, start_idx)
        if not path:
            CUS_LOGGER.error("未找到有效路径，可能是起点位于最右端或图构建失败")
            raise NoMatchError
        self.start_nodes=path[0]
        if path:
            weight_ranges = {
                'event': (0, 1), 'wait': (0, 0), 'trade': (0, 0), 'trade2': (0, 0), 'adventure': (0, 0),
                'reward': (0, 1),'reward2': (0, 1), 'battle': (1, 3), 'elite': (1, 1), 'bugevent': (0, 1),
                'bugbattle': (1, 1), 'head': (1, 1), 'boss': (1, 1), 'blank': (0, 0)
            }
            if len(path)>1:
                self.next_node=path[1]
            CUS_LOGGER.debug(f'路径理论期望值：total_weight={total_weight:.3f}')
            CUS_LOGGER.debug(f'路径理论最小值：{sum(weight_ranges.get(n['name'], (0, 0))[0] for n in path)}')
            CUS_LOGGER.debug(f'路径理论最大值：{sum(weight_ranges.get(n['name'], (0, 0))[1] for n in path)}')
            self.max_limited=0
            self.max_change_count=0
            best_path, _, _, _, _, _ = evaluate_best_single_replacement(
                self.nodes, self.edges, start_idx, t=0.3 if self.plane_floor == 3 else 0.2)
            for i,n in enumerate(best_path):
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
                CUS_LOGGER.debug(f'替换后路径总权重：{best_weight:.3f} (原权重：{total_weight:.3f})')
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
                CUS_LOGGER.debug(f'\n原路径理论期望值：{total_weight:.3f} (min={orig_min}, max={orig_max})')
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
        for _ in range(5):
            self.click_text(text="进入位面", box=[907, 1009, 857, 891])
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
        if len(res)==0:
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
            elif '三八面骰' in strange or '银河大乐透' in strange:
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
            can_use_list=list({0, 1, 2} - set(black_index_list))
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
        if "肉体" in text:
            try:
                self.try_analysis_map(mode=2)
            except NoMatchError:
                return
            if self.replace_idx is not None:
                x,y=int(self.nodes[self.replace_idx]["cx"]),int(self.nodes[self.replace_idx]["cy"])
                key_mouse_manager.click(x,y)
                key_mouse_manager.wait()
                self.click_text(text="确认目标", box=[1635, 1735, 968, 996])
            else:
                CUS_LOGGER.info("所以你才变成了这副模样：残缺的神像…悲哀的薪柴。")
                self.click_text(text="放弃", box=[1221, 1276, 967, 998])
        else:
            #不是肉体帝候一律放弃
            self.click_text(text="放弃", box=[1221, 1276, 967, 998])
    def try_get_kill_count(self):
        screen = self.get_screen()
        num1 = extract_number(match_numbers_in_region(screen))
        try:
           if num1 is not None:
                num1 = int(num1)
           else:
                return None
        except (ValueError, TypeError):
            return None
        if num1 is None or num1 % 8 != 0:
            return None
        time.sleep(0.5)
        screen2 = self.get_screen()
        num2 = extract_number(match_numbers_in_region(screen2))
        if num2 is not None:
            try:
                num2 = int(num2)
            except (ValueError, TypeError):
                return None
        else:
            return None
        if num2 % 8 == 0 and num2 == num1:
            return num1 // 8
        return None
    def select_go(self):
        max_retries = 5
        kill = None
        for attempt in range(max_retries):
            kill = self.try_get_kill_count()
            if kill is not None:
                self.kill_count = kill
                CUS_LOGGER.debug(f"识别成功，击杀数{self.kill_count}")
                break
            else:
                CUS_LOGGER.warning(f"第{attempt+1}次完整识别与复核失败，重试")
                time.sleep(2)   # 等待后重试整个流程
        if kill is None:
            CUS_LOGGER.error("多次尝试仍无法获取击杀数，放弃本次计数")
            return
        CUS_LOGGER.debug(f"当前击杀数{self.kill_count}")
        self.set_kill_num(str(self.kill_count))
        key_mouse_manager.clean()
        key_mouse_manager.keyUp("w")
        key_mouse_manager.wait()
        if self.click_text(text="选择移动目标", box=[1609, 1759, 965, 996],click=False,allow_fail=True):
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
    def calculated_roll(self):
        if self.nodes is None or self.plane_floor==-1:
            self.click_target(find_image_by_name("inmap"), 0.9, flag=False, click=True)
            key_mouse_manager.wait()
            return
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
        self.init_map()
        self.mini_state = 1

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