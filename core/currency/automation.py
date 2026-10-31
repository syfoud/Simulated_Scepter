import os
import re
import time

import cv2
import numpy as np
import pyautogui

from core.currency.config import config
from core.currency.investment_selection import choose_fallback_investment
from core.currency.investment_state import InvestmentSelectionTracker, SelectionKind
from core.currency.preparation import (
    AREA_BOXES,
    BENCH_BOXES,
    TEAM_CAPACITY,
    BattlePreparation,
    Deployment,
    plan_deployment,
)
from core.currency.run_history import (
    RUN_END_ACTION,
    CurrencyRunHistory,
    get_newly_unlocked_investment,
)
from core.currency.settings import load_currency_settings, resolve_priority
from core.currency.utils import CurrencyUtils, set_forground
from route import PATHS
from tool import GLOBAL
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import load_actions, merge_text
from tool.settings import load_settings
from tool.storage import resource_path
from tool.utils.Error import NormalEndError
from tool.utils.tool import get_hwnd_and_text


def count_color(patch):
    """人数数字的主色：占比够大且最亮的颜色。

    数字比背景亮得多；未满员时是青色，满员后整行变成灰色，按最亮的显著颜色取色可以跟着变。
    取不到时返回 None。
    """
    bright = patch.max(axis=2) >= 140
    colors = patch[bright].reshape(-1, 3) // 16 * 16
    if not colors.size:
        return None
    values, counts = np.unique(colors, axis=0, return_counts=True)
    significant = counts >= max(8, counts.sum() * 0.02)
    values = values[significant]
    if not values.size:
        return None
    return values[np.argmax(values.max(axis=1))]


def count_mask(patch):
    """按人数数字的主色取笔画，背景、图标和星点都不会落进来。"""
    color = count_color(patch)
    if color is None:
        return np.zeros(patch.shape[:2], dtype=bool)
    return np.abs(patch.astype("int16") - color.astype("int16")).max(axis=2) <= 40


def count_shows_full(patch):
    """人数数字不再是青色（满员后变成灰色）时说明人数已满。

    Returns:
        True 已满、False 未满、None 取不到主色。
    """
    color = count_color(patch)
    if color is None:
        return None
    blue, green, red = (int(channel) for channel in color)
    return not (blue - red > 60 and green - red > 60)


def split_count_line(patch):
    """按斜杠把人数裁片切成左右两段，两段各只含一个数字。

    斜杠是唯一从一端移到另一端的细笔画字形，据此把它和两侧数字分开。

    Returns:
        (左段, 右段)；找不到斜杠时返回 None。
    """
    mask = count_mask(patch)
    groups = []
    start = None
    for index, column in enumerate(mask.any(axis=0)):
        if column and start is None:
            start = index
        elif not column and start is not None:
            groups.append((start, index))
            start = None
    if start is not None:
        groups.append((start, mask.shape[1]))
    for left, right in groups:
        rows = [np.flatnonzero(row) for row in mask[:, left:right]]
        rows = [row for row in rows if row.size]
        if not rows:
            continue
        width = right - left
        widths = np.array([row.size for row in rows])
        centers = np.array([row.mean() for row in rows])
        steps = np.diff(centers)
        moving = bool((steps >= 0).all() or (steps <= 0).all())
        if (
            moving
            and max(widths[0], widths[-1]) <= width * 0.5
            and np.median(widths) <= width * 0.35
            and abs(centers[-1] - centers[0]) >= width * 0.5
        ):
            return patch[:, :left], patch[:, right:]
    return None


def read_count_number(recognizer, patch):
    """识别人数裁片一侧的数字；识别结果不是一个数字时返回 None。"""
    digits = re.findall(r"\d+", recognizer.ocr_one_row(patch))
    if len(digits) != 1:
        return None
    return int(digits[0])


class SimulatedCurrency(CurrencyUtils):
    def static_completed(self, name, result):
        if name == "开始退出" and result == 0:
            self.latched_events.discard(name)
        self._on_static_action_completed(name)


    SPECIAL_INVESTMENTS = ("黄金投资", "白银投资")
    DIFFICULTY_MAX_STEPS = 120
    DIFFICULTY_SELECTED_EFFECT_BOX = [700, 350, 1200, 465]
    DIFFICULTY_DOWN_POSITION = (960, 844)
    ENVIRONMENT_TITLE_BOX = [897, 80, 1018, 114]
    ENVIRONMENT_CONFIRM_BOX = [1053, 967, 1108, 998]
    # 上阵人数裁片：避开左侧人物图标，右侧留出两位数上限的宽度。
    TEAM_COUNT_BOX = [884, 202, 1150, 280]
    BLESS_REFRESH_POSITIONS = ((384, 869), (868, 869), (1380, 869))

    def __init__ (self, find, debug, speed, consumable, slow, nums = -1, bonus = False):
        super ().__init__ (speed)
        key_mouse_manager.set_config (config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy)
        # 普通位面选择、立即奖励和延迟奖励的状态
        self.investment_tracker = InvestmentSelectionTracker()
        self.run_history = CurrencyRunHistory()
        # 停止运行标志
        self._stop = True
        # 调试级别
        self.debug = debug
        # 设置全局调试模式标志，供 UILogHandler 使用
        GLOBAL.DEBUG_MODE = bool (self.debug)
        # 启动时时间
        self.init_time = time.time ()
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        # 事件与行为存储路径
        self.default_json_path = str(resource_path(__file__, "actions/currencywar.json"))
        self.default_json = load_actions(self.default_json_path)
        # 策略最大刷新次数
        self.max_refresh = 1
        # 运行次数
        self.count = 0
        # 是否需要退出
        self.exit_requested = False
        # 是否已开始退出
        self.exit_started = False

        priority = load_currency_settings()["priority"]

        self.prior_envir = priority["prior_envir"][:]
        self.envir = [[] for _ in range(4)]

        for index in range(1, 5):
            self.envir[index - 1] = priority[f"envir_{index}"][:]

        self.ENVIR_BOXES = [[266, 375, 610, 413], [780, 375, 1134, 414], [1314, 373, 1645, 413]]
        self.BLESS_BOXES = [[298, 472, 608, 513], [783, 472, 1095, 513], [1298, 472, 1605, 513]]

        if debug != 2:
            # 似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False

        CUS_LOGGER.debug (f"开始运行,初始计数：{self.count}")
        self.last_interact_time = time.time ()

        # 首次运行时用默认配置补全游戏与脚本设置。
        load_settings()

        self.preparation = BattlePreparation()
        currency_settings = load_currency_settings()  # 模板去重可能已迁移角色优先级。
        self.front_priority, self.back_priority = resolve_priority(
            currency_settings["deployment"]
        )
        if not self.front_priority and not self.back_priority:
            CUS_LOGGER.warning(
                "尚未配置前台或后台角色优先级，备战角色只会作为补位进入前台空位；"
                "请先在货币战争设置里配置"
            )

        # 本局默认退出位面，以及 prior 投资环境出现后可能使用的退出位面
        self.set_exit_plane = currency_settings["exit_after_plane"]
        self.exit_plane = self.set_exit_plane
        self.prior_exit_plane = currency_settings["prior_exit_plane"]
        self.exit_if_no_prior = currency_settings["exit_if_no_prior"]

        # 记录本局是否刷出了必选（prior）投资环境
        self.prior_environment_found = False
        self.has_fresh = False
        exit_plane_text = "不退出" if self.set_exit_plane is None else f"第{self.set_exit_plane}面"
        CUS_LOGGER.info(f"货币战争退出位面设置为: {exit_plane_text}")

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
                cnt += 1
                if cnt == 1200:
                    set_forground () # 将游戏窗口设为前台
                hwnd,Text = get_hwnd_and_text ()
            if self._stop:
                break
            self.loop ()
        CUS_LOGGER.info ("已停止任务")

    def loop (self):
        CUS_LOGGER.info ("开始OCR识别，等待触发文字")
        silent_time = time.time ()
        shot_saved = False
        while not self._stop:
            self.ts.forward (self.get_screen())
            name, _ = self.run_static ()
            if name:
                silent_time = time.time ()
                shot_saved = False
                continue
            # 无人命中超过10秒时记录整屏文字并留一张截图；战斗中长时间无触发属正常，跳过
            if time.time() - silent_time > 10:
                silent_time = time.time()

                # startbattle 是一个允许长时间无 OCR 触发的等待状态
                if self.state == "startbattle":
                    continue

                # 其他状态保持原来的 10 秒异常诊断逻辑
                screen_text = " ".join(
                    res["raw_text"]
                    for res in self.ts.find_with_box(
                        [0, 0, 1920, 1080],
                        redundancy=0
                    )
                )
                CUS_LOGGER.warning("连续10秒无任何触发，当前屏幕文字：%s", screen_text)
                if not shot_saved:
                    shot_saved = True
                    shot = os.path.join(
                        PATHS["temp"],
                        "currencywar",
                        f"unknown_screen_{time.strftime('%Y%m%d_%H%M%S')}.png",
                    )
                    cv2.imwrite(shot, np.array(self.screen))
                    CUS_LOGGER.warning("已保存无触发界面截图：%s", shot)

    def goto_currency (self):
        """
        不在货币战争中，通过星际和平指南传送至货币战争
        """
        CUS_LOGGER.info("前往货币战争")
        key_mouse_manager.press("interastral_peace_guide")

    def is_one (self):
        try:
            text_list = self.ts.find_with_box(
                self.DIFFICULTY_SELECTED_EFFECT_BOX,
                forward=1,
            )
            merged = merge_text (text_list)
            CUS_LOGGER.debug(f"OCR 识别结果: {merged}")
            return "开局时获得" in merged
        except Exception:
            CUS_LOGGER.info("正在选择难度1")
            return False

    def select_difficulty_start (self):

        if self.state != "difficulty_select":
            CUS_LOGGER.info(f"停止选择难度，当前状态：{self.state}")
            return True

        key_mouse_manager.clean()
        for attempt in range(self.DIFFICULTY_MAX_STEPS + 1):
            if self._stop:
                CUS_LOGGER.info("检测到停止标志，停止选择难度")
                return True
            if self.state != "difficulty_select":
                CUS_LOGGER.info(f"停止选择难度，当前状态：{self.state}")
                return True
            self.get_screen()
            if self.is_one ():
                CUS_LOGGER.info ("已识别到难度1")
                return self.complete_difficulty_selection()

            if attempt == self.DIFFICULTY_MAX_STEPS:
                break

            CUS_LOGGER.info(
                f"尚未识别到难度1，执行第{attempt + 1}/"
                f"{self.DIFFICULTY_MAX_STEPS}次向下选择"
            )
            key_mouse_manager.click_point(*self.DIFFICULTY_DOWN_POSITION)
            key_mouse_manager.wait()

        CUS_LOGGER.warning("达到向下选择上限，仍未识别到难度1；停止点击并等待下一轮识别")
        return False

    def handle_difficulty_selection(self):
        if self.state not in (None, "difficulty_select"):
            return 0

        self.update_state("difficulty_select")
        self.get_screen()

        if self.is_one():
            CUS_LOGGER.info("已处于目标难度，直接开始对局")
            return self.complete_difficulty_selection()

        CUS_LOGGER.info("未处于目标难度，开始选择难度")
        return self.select_difficulty_start()

    def complete_difficulty_selection(self):
        if self.state != "difficulty_select":
            CUS_LOGGER.info(f"难度选择已结束，当前状态：{self.state}")
            return True

        key_mouse_manager.clean()
        key_mouse_manager.click_point(1692, 965, force=True) # “开始对局”按钮坐标
        key_mouse_manager.wait()
        self.exit_plane = self.set_exit_plane
        self.prior_environment_found = False
        self.exit_requested = False
        self.exit_started = False
        # 刷新额度按对局计：上一局无论刷没刷出必选，本局都要重新给一次。
        self.has_fresh = False
        self.run_history.start_run()
        CUS_LOGGER.info("货币战争对局计时开始")
        return True

    def auto_battle(self):
        # 需要打开自动战斗
        key_mouse_manager.press("V")



    def select_envir (self):
        CUS_LOGGER.info ("=== 进入投资环境选择阶段===")
        # self.ts.forward (self.get_screen ())
        boxes = self.ENVIR_BOXES
        def match_prior (texts):
            for pri in self.prior_envir:
                for idx, text in enumerate (texts):
                    if pri in text:
                        CUS_LOGGER.info (f"检测到必选环境: {pri}，选择选项{idx+1}")
                        return True, idx
            return False, -1
        texts = self.recognize_options (self.ENVIR_BOXES)
        CUS_LOGGER.info (f"OCR 识别结果: {texts}")
        matched, selected_idx = match_prior (texts)

        if not matched and not self.has_fresh:
            CUS_LOGGER.info ("未匹配到必选环境，点击刷新按钮")
            key_mouse_manager.click_point(672, 984)  # 刷新按钮坐标
            key_mouse_manager.wait()
            self.has_fresh=True
            return
        # 构建完整的优先级列表（按顺序）
        elif not matched:
            self.has_fresh=False
            # 顺序：prior_envir + envir[0] + envir[1] + ... + envir[4]
            prior_list = self.prior_envir[:] # 复制最高优先级列表
            for envir in self.envir: # 遍历envir列表，将每个子列表的元素按顺序添加到prior_list中
                prior_list.extend(envir)
            # 按优先级匹配选项
            selected_idx = -1 # 初始化为-1，表示未匹配
            for pri in prior_list:
                for idx, text in enumerate(texts):
                    # 判断当前选项文字中是否包含优先级关键词（使用 in 进行子串匹配）
                    if pri in text:
                        selected_idx = idx
                        CUS_LOGGER.info(f"匹配到优先级投资环境: {pri}，选择选项{idx+1}")
                        break
                if selected_idx != -1:
                    break  # 已匹配到，跳出外层循环
            # 如果都未匹配，默认选中间
            if selected_idx == -1:
                selected_idx = 1
                CUS_LOGGER.warning("未匹配到任何优先级投资环境，默认选择中间")

        self.max_refresh = 1
        self._apply_environment_effects(texts)

        # 点击选中的选项（点击其中心位置）
        # 计算每个选项的中心像素坐标
        centers = []
        for box in boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            centers.append((cx, cy))

        selected_text = texts[selected_idx] if selected_idx < len(texts) else ""
        key_mouse_manager.click_point(*centers[selected_idx], box=boxes[selected_idx])
        key_mouse_manager.wait()

        self._confirm_environment_selection()

        if "蓝海" in selected_text and not self._select_blue_ocean_extra_environment():
            CUS_LOGGER.warning("蓝海额外投资环境未完成，本轮不推进状态")
            return 0

        self.investment_tracker.reset()
        self.update_state("1-1")
        CUS_LOGGER.info ("投资环境选择完成")
        return 1

    def _apply_environment_effects(self, texts):
        """根据当前显示的投资环境应用特殊效果。"""

        if any(
            prior in text
            for prior in self.prior_envir
            for text in texts
        ):
            if not self.prior_environment_found:
                self.prior_environment_found = True

                # 必选环境指定的退出位面优先于默认设置，包括默认的“不退出”。
                if self.prior_exit_plane is not None:
                    self.exit_plane = self.prior_exit_plane
                    CUS_LOGGER.info(
                        f"检测到必选环境，退出位面调整为第{self.exit_plane}面"
                    )
                else:
                    self.exit_plane = self.set_exit_plane
                    CUS_LOGGER.info(
                        "检测到必选环境，但退出位面设置为不调整"
                    )

        if any("银金彩" in text for text in texts):
            self.max_refresh = 3
            CUS_LOGGER.info(
                "检测到银金彩，已将投资策略刷新次数调整至3次"
            )

    def _confirm_environment_selection(self):
        # 普通环境与蓝海额外环境的确认按钮位置相同。
        box = self.ENVIRONMENT_CONFIRM_BOX
        key_mouse_manager.click_point((box[0] + box[2]) // 2, (box[1] + box[3]) // 2, box=box)
        key_mouse_manager.wait()

    def _select_blue_ocean_extra_environment(self, max_attempts=6):
        CUS_LOGGER.info("蓝海生效，等待选择唯一的额外投资环境")
        centers = [
            ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
            for box in self.ENVIR_BOXES
        ]

        for attempt in range(max_attempts):
            if not self.click_text(
                text="投资环境",
                box=self.ENVIRONMENT_TITLE_BOX,
                click=False,
                allow_fail=True,
            ):
                continue

            self.ts.forward(self.get_screen())
            texts = self.recognize_options(self.ENVIR_BOXES)
            available = [idx for idx, text in enumerate(texts) if text.strip()]
            if len(available) != 1:
                CUS_LOGGER.info(
                    f"蓝海额外环境尚未稳定显示：{texts}，"
                    f"第{attempt + 1}/{max_attempts}次等待"
                )
                continue

            selected_idx = available[0]
            selected_text = texts[selected_idx]

            self._apply_environment_effects([selected_text])

            key_mouse_manager.click_point(*centers[selected_idx], box=self.ENVIR_BOXES[selected_idx])
            key_mouse_manager.wait()
            self._confirm_environment_selection()

            CUS_LOGGER.info(
                f"蓝海额外投资环境选择完成：{selected_text}"
            )
            return True

        return False

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

    def _refresh_investment_options(self, previous_texts, max_attempts=2):
        pending = list(range(len(self.BLESS_REFRESH_POSITIONS)))
        latest_texts = list(previous_texts)

        for attempt in range(max_attempts):
            for idx in pending:
                key_mouse_manager.click_point(*self.BLESS_REFRESH_POSITIONS[idx])
                key_mouse_manager.wait()

            self.ts.forward(self.get_screen())
            latest_texts = self.recognize_options(self.BLESS_BOXES)
            pending = [
                idx
                for idx in pending
                if not (
                    previous_texts[idx].strip()
                    and latest_texts[idx].strip()
                    and previous_texts[idx] != latest_texts[idx]
                )
            ]
            if not pending:
                break
            if attempt + 1 < max_attempts:
                CUS_LOGGER.warning(
                    "以下投资策略未确认刷新，将仅重试这些位置："
                    + ", ".join(str(idx + 1) for idx in pending)
                )

        return latest_texts

    def select_bless (self):
        """选择投资策略，并区分普通位面选择与黄金/白银投资奖励。"""

        selection = self.investment_tracker.begin_selection()
        kind_text = {
            SelectionKind.NORMAL: "普通位面",
            SelectionKind.IMMEDIATE_BONUS: "立即奖励",
            SelectionKind.DELAYED_BONUS: "延迟奖励",
        }[selection.kind]
        CUS_LOGGER.info(
            f"=== 进入投资策略选择：{kind_text}，"
            f"已完成{self.investment_tracker.plane_count}面 ==="
        )
        self.ts.forward (self.get_screen ())
        boxes = self.BLESS_BOXES

        centers = []
        for box in boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            centers.append((cx, cy))

        selected_idx = -1
        texts = ["", "", ""]
        roi_boxes = [
            [617, 219, 641, 241],
            [1116, 219, 1141, 241],
            [1616, 219, 1639, 241],
        ]

        for attempt in range (self.max_refresh + 1):
            self.ts.forward (self.get_screen ())
            texts = self.recognize_options (boxes)
            CUS_LOGGER.info (f"OCR 识别结果: {texts}")

            icon_presence = [False] * len(roi_boxes)
            for idx, box in enumerate(roi_boxes):
                x1, y1, x2, y2 = box
                roi = self.screen[y1:y2, x1:x2]
                has_icon, std = self.detect_has_icon(roi)
                icon_presence[idx] = bool(has_icon)
                CUS_LOGGER.info(
                    f"选项{idx+1} 是否有图标: {has_icon} (标准差: {std:.2f})"
                )
                if has_icon:
                    selected_idx = idx
                    CUS_LOGGER.info(
                        f"第{attempt}次检测到未解锁图标，选中选项{idx+1}"
                    )
                    break

            if selected_idx != -1:
                break

            if attempt < self.max_refresh:
                CUS_LOGGER.info(f"第 {attempt+1} 次未匹配，点击刷新")
                self._refresh_investment_options(texts)
            else:
                selected_idx = choose_fallback_investment(texts, icon_presence)
                if selected_idx == 1:
                    CUS_LOGGER.warning("刷新后仍未找到未解锁图标，默认选中间")
                else:
                    CUS_LOGGER.warning(
                        "中间选项为无图鉴图标的轮回不止，改选左侧以保留跨局资源"
                    )

        selected_text = texts[selected_idx] if selected_idx < len(texts) else ""
        unlocked_investment = get_newly_unlocked_investment(
            texts,
            icon_presence,
            selected_idx,
        )
        special_investment = next(
            (name for name in self.SPECIAL_INVESTMENTS if name in selected_text),
            None,
        )
        if special_investment:
            CUS_LOGGER.info(
                f"检测到{special_investment}：登记1次立即奖励和下一边界1次延迟奖励"
            )

        key_mouse_manager.click_point(*centers[selected_idx], box=boxes[selected_idx])

        self.click_text (text = "确认", box = [948, 968, 1005, 999], click = True)
        CUS_LOGGER.info ("投资策略选择完成")
        self.ts.forward (self.get_screen())

        self.investment_tracker.complete_selection(
            selection,
            grants_bonus=special_investment is not None,
        )
        if (
            unlocked_investment
            and self.run_history.record_unlocked_investment(unlocked_investment)
        ):
            CUS_LOGGER.info(f"本局新解锁投资策略：{unlocked_investment}")
        exit_plane_text = "不退出" if self.exit_plane is None else str(self.exit_plane)
        CUS_LOGGER.info(
            f"投资进度：普通位面={self.investment_tracker.plane_count}/"
            f"{exit_plane_text}，立即奖励={self.investment_tracker.immediate_count}，"
            f"延迟奖励={self.investment_tracker.delayed_count}"
        )

        if self.investment_tracker.should_exit(self.exit_plane):
            CUS_LOGGER.info(f"达到退出位面（{self.exit_plane}面），尝试重开")
            self.exit_requested = True
            self.update_state("exit")

        return 1

    def read_team_count(self):
        """读取上阵人数及人数上限；OCR 暂未识别完整时返回 None。

        画面上的数字是前台与后台之和，上限随对局进度增长，超过前台落点数仍合法。
        整行识别容易把斜杠读成数字（灰色满员时的“7/7”会读成“777”），所以按斜杠切成
        左右两段各识别一次；切不开或数字没认全时退回整行识别。满员后数字由青色变灰，
        这个颜色本身也是满员的依据：认不出数字但颜色已变灰时按满员处理。人数裁片从左侧
        人物图标右侧开始，右侧留出两位数上限的宽度。
        """
        box = self.TEAM_COUNT_BOX
        patch = self.screen[box[1]:box[3], box[0]:box[2]]
        counts = None
        halves = split_count_line(patch)
        if halves is not None:
            placed = read_count_number(self.ts, halves[0])
            capacity = read_count_number(self.ts, halves[1])
            if placed is not None and capacity is not None:
                counts = placed, capacity
            else:
                CUS_LOGGER.debug("上阵人数左右分开识别不完整：%r/%r", placed, capacity)
        if counts is None:
            text = self.ts.ocr_one_row(self.screen, box)
            match = re.search(r"(\d+)\s*[/／]\s*(\d+)", text)
            if match is not None:
                counts = tuple(map(int, match.groups()))
            elif count_shows_full(patch):
                # 满员时数字是灰色；认不出数字也不该继续补位，按“已满、上限未知”处理。
                CUS_LOGGER.debug("人数数字已变灰（满员），但没认出数字；按满员处理")
                return 1, 1
            else:
                CUS_LOGGER.debug("上阵人数识别未得到有效数字：%r", text)
                return None
        placed, capacity = counts
        if not 0 < capacity <= TEAM_CAPACITY or placed > capacity:
            CUS_LOGGER.debug("上阵人数超出有效范围：%s/%s", placed, capacity)
            return None
        return counts

    def prepare_battle(self):
        """先补满阵容，再按优先级替换，截图确认完成后才允许出战。

        每次只执行一个拖拽并重新采集，避免备战栏压缩后使用过期的格子坐标。
        返回 1 表示已准备好，0 表示仍需准备；识别和落位失败均不放行。
        """
        if self._stop or self.exit_requested:
            return 0
        if self.state == "battle_ready":
            self.update_state("currency_main")
        if self.state == "1-1":
            self.handle_1_1_reward()
        # 同一轮限制补位和身份确认次数；未完成时留待下一次触发继续。
        blocked = set()  # 按身份阻止本轮重试，不依赖会压缩变动的备战格序号。
        for _ in range(2 * len(BENCH_BOXES) + 1):
            if self._stop or self.exit_requested:
                return 0
            self.ts.forward(self.get_screen())
            counts = self.read_team_count()
            if counts is None:
                CUS_LOGGER.debug("上阵人数未能识别，等待下一轮")
                return 0
            slots = self.preparation.scan_bench(self.screen)
            vacancies = self.preparation.read_areas(self.screen)
            front_occupied = len(AREA_BOXES["front"]) - len(vacancies["front"])
            deployed = self.preparation.deployed_templates(self.screen, vacancies)
            moves = plan_deployment(
                [slot for slot in slots if slot.template not in blocked],
                vacancies, counts, self.front_priority, self.back_priority,
                self.preparation.read_members(vacancies, counts[0]),
                deployed=deployed,
            )
            sources = {slot.index: slot.template for slot in slots if slot.kind == "character"}
            if not moves:
                if front_occupied == 0:
                    CUS_LOGGER.debug("前台尚无角色，继续等待备战")
                    return 0
                self.update_state("battle_ready")
                CUS_LOGGER.info("阵容已就位，可以出战！")
                return 1
            move = moves[0]
            result = self.deploy_character(move, slots, counts)
            if result is None:
                blocked.add(sources[move.source])
                continue
            after_slots, outgoing, verified = result
            if outgoing is None:
                if not verified:
                    return 0
                continue
            incoming = next(slot.template for slot in slots if slot.index == move.source)
            priority = self.front_priority if move.area == "front" else self.back_priority
            ranks = {name: index for index, name in enumerate(priority)}
            if ranks.get(incoming, len(ranks)) < ranks.get(outgoing, len(ranks)):
                if not verified:
                    return 0
                continue
            # 接管已有阵容时，先核对交换回来的人物；原角色更优则立即换回，保留已确认身份。
            previous = next(slot for slot in after_slots if slot.kind == "character" and slot.template == outgoing)
            restore = Deployment(previous.index, move.area, move.target, incoming)
            restored = self.deploy_character(restore, after_slots, counts)
            if restored is None or restored[1] != incoming or not restored[2]:
                return 0
            CUS_LOGGER.debug("原上阵角色优先级更高，已恢复：%s", outgoing)
        return 0

    def deploy_character(self, move, slots, counts):
        """执行一次补位或交换，核对人数、落点和备战栏角色变化。

        Returns:
            身份变化可确认时返回 (备战快照, 被换回的角色或 None, 人数及落点是否核对通过)，
            无身份变化或停止时返回 None。人数未确认时保留身份，但不放行出战。
        """
        if self._stop or self.exit_requested:
            return None
        source = BENCH_BOXES[move.source]
        target = AREA_BOXES[move.area][move.target]
        CUS_LOGGER.debug(
            "准备拖拽角色：备战格%d -> %s第%d格（%s）", move.source + 1,
            "前台" if move.area == "front" else "后台", move.target + 1,
            "补位" if move.outgoing is None else "替换",
        )
        key_mouse_manager.drag_point(
            (source[0] + source[2]) // 2, (source[1] + source[3]) // 2,
            (target[0] + target[2]) // 2, (target[1] + target[3]) // 2,
        )
        key_mouse_manager.sleep(0.5)  # 等待交换或落位动画及人数刷新。
        key_mouse_manager.wait()
        if self._stop or self.exit_requested:
            return None
        self.ts.forward(self.get_screen())
        after_slots = self.preparation.scan_bench(self.screen)
        vacancies = self.preparation.read_areas(self.screen)
        after_count = self.read_team_count()
        if self._stop or self.exit_requested:
            return None
        # 补位都会让人数加一，交换不改变人数；补位和交换都不改变人数上限。
        expected = (counts[0] + 1, counts[1]) if move.outgoing is None else counts
        confirmed, outgoing = self.preparation.confirm_move(move, slots, after_slots)
        if confirmed:
            verified = move.target not in vacancies[move.area] and after_count == expected
            if not verified:
                CUS_LOGGER.debug("角色身份变化已确认，等待人数与落点核对：%s，人数=%s", move, after_count)
            return after_slots, outgoing, verified
        # 一次无效拖拽不能撤销其他已确认角色，否则下一轮会重复拖动同名份。
        CUS_LOGGER.debug("角色拖拽未确认，本轮跳过该动作：%s，人数=%s", move, after_count)
        return None

    def start_battle(self):
        """仅在可出战状态点击出战，等待输入完成后进入战斗状态。"""
        key_mouse_manager.click_point(1818, 750)
        key_mouse_manager.wait()
        self.update_state("startbattle")
        return 1

    def handle_1_1_reward(self):
        """处理1-1投资环境选择后的奖励界面。"""

        if self.prior_environment_found or not self.exit_if_no_prior:
            self.preparation.reset_members()
            CUS_LOGGER.debug("进入1-1，等待备战识别")
            self.update_state("startbattle")
            return 1

        CUS_LOGGER.info("未刷出必选投资环境，准备提前退出")
        self.exit_requested = True
        self.update_state("exit")
        return 1

    def is_battle_started(self):
        '''用于检测是否处于战斗状态，返回bool值'''
        if self.click_text(
            text="伤害",
            box=[1793, 209, 1833, 231],
            click=False,
            allow_fail=True,
        ):
            CUS_LOGGER.debug("检测到已进入战斗")
            return True

        return False


    def exit(self):
        """执行当前货币战争对局的统一退出流程。"""

        if self.exit_started:
            return 1

        CUS_LOGGER.info("执行货币战争退出流程")

        # 先检查是否已经进入“放弃并结算”页面
        self.ts.forward(self.get_screen())
        if self.click_text(
            text="放弃并结算",
            box=[707, 728, 831, 756],
            click=False,
            allow_fail=True,
        ):
            CUS_LOGGER.debug("检测到退出页面")
            self.exit_started = True
            return 1

        # 虽然正常情况下exit的时候不会在战斗状态，但是万一呢
        if self.is_battle_started():
            CUS_LOGGER.debug("当前处于战斗中，按 ESC 并点击撤退")
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            key_mouse_manager.click_point(1223, 985) # 点击撤退
            key_mouse_manager.wait()
            self.ts.forward(self.get_screen())

            if self.click_text(
                text="放弃并结算",
                box=[707, 728, 831, 756],
                click=False,
                allow_fail=True,
            ):
                CUS_LOGGER.debug("检测到退出页面")
                self.exit_started = True
                return 1
            else:
                CUS_LOGGER.debug("未检测到退出页面，将重试")
                return 0

        max_attempts = 15
        timeout = 6
        deadline = time.monotonic() + timeout

        for attempt in range(max_attempts):
            if time.monotonic() >= deadline:
                break

            if self._stop:
                CUS_LOGGER.info("检测到停止标志，提前退出检测终止")
                return 0

            self.ts.forward(self.get_screen())

            if self.click_text(
                text="放弃并结算",
                box=[707, 728, 831, 756],
                click=False,
                allow_fail=True,
            ):
                CUS_LOGGER.debug("检测到退出页面")
                self.exit_started = True
                return 1

            CUS_LOGGER.debug(
                f"未检测到退出页面，第 {attempt + 1}/{max_attempts} 次按 ESC"
            )

            key_mouse_manager.press("esc")
            key_mouse_manager.wait()

        CUS_LOGGER.warning("未能确认进入“放弃并结算”页面，本次退出尝试失败，将在下一轮重试")
        return 0

    def handle_battle_finished(self):
        if self.exit_requested:
            self.update_state("exit")
        else:
            self.update_state("currency_main")
        return 1


    def _on_static_action_completed(self, action_name: str) -> None:
        if action_name != RUN_END_ACTION:
            return

        # 本局结束，恢复下一局使用的默认退出配置
        self.exit_plane = self.set_exit_plane
        self.prior_environment_found = False

        try:
            record = self.run_history.finish_run()
        except OSError as error:
            CUS_LOGGER.error(f"货币战争对局记录写入失败：{error}")
            return

        if record is None:
            CUS_LOGGER.warning("未找到本局开始记录，跳过货币战争对局统计")
        else:
            CUS_LOGGER.info(f"货币战争对局记录完成：{record}")


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
