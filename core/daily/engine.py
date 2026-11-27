"""日常内核：只实现需要读配置或读数值的界面判断与动作。

界面识别与流程推进由 `actions/daily_relic.json` 的状态机完成，本内核只提供
脚本能调用的方法。每个方法处理当前画面的一个判断与一个动作：不循环、不
睡眠、不重试，做完立即返回，由状态机的下一轮轮询重新识别画面。
"""

import logging
import re
import time
from pathlib import Path

import numpy as np

from core.common.ocr import is_edit_distance_at_most_one
from core.common.runtime import ScriptKernel, set_forground
from core.daily.relic_targets import (
    INNER_TARGETS,
    OUTER_TARGETS,
    RUNS_CHOICES,
    SUPPORT_ROLE_CHOICES,
    SUPPORT_SLOT_CHOICES,
)
from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import clean_text, load_actions
from tool.storage import load_module_settings
from tool.utils.minimap_util import MINIMAP_RADIUS, get_minimap

# 生存索引左侧菜单的固定顺序，从上到下；用目标与可见分类的相对位置判断滚动方向。
MENU_ITEMS = (
    "培养目标",
    "饰品提取",
    "拟造花萼",
    "凝滞虚影",
    "侵蚀隧洞",
    "历战余响",
)
# 指南窗口左上角第二行是当前页签，实测三处判断都落在这个区域里（生存索引/每日实训）。
TAB_LINE_BOX = [101, 63, 203, 99]
# 指南页顶部页签的落点：左起第一个是「每日实训」（带红点角标），第二个是「生存索引」。
# 两张截图实测：每日实训页时第一个页签高亮 x 298~430，生存索引页时第二个高亮 x 417~549。
TAB_DAILY = [364, 215]
# 第二个页签是「生存索引」：换分类、刷新列表时都要点它。
TAB_INDEX = [483, 215]
# 手机页面右下角「指南」图标的位置（真实坐标，供点指南与判断手机页面用）。
GUIDE_ICON_BOX = [1319, 784, 1364, 809]

# 消耗品列表的格子中心：列 x、行 y（数量标签在格子底部，实测列距 133、行距 157）。
SNACK_GRID_X = (158, 291, 424)
SNACK_GRID_Y = (168, 325, 482, 639, 796)
# 页面 → 状态：认出哪一页就把状态校正到哪一位。页面锚点统一放在内核里，
# 脚本只写 state_only，不再把这些坐标各写一份。顺序按「越具体越靠前」排，
# 因为「星际和平指南」标题在指南系的所有子页都会出现，只能放最后。
# 各状态的先后次序：只允许「往前跳」，不允许回退。
STAGE_ORDER = {
    "relic_entry": 0,
    "relic_guide": 1,
    "relic_index": 2,
    "relic_refresh": 2,
    "relic_refresh_back": 2,
    "relic_list": 3,
    "relic_prepare": 4,
    "relic_challenge": 5,
    "relic_outer_challenge": 5,
    "relic_team": 5,
    "relic_support_list": 6,
    "relic_support_outer": 6,
    "relic_team_start": 7,
    "relic_skill": 8,
    "relic_approach": 9,
    "relic_done": 10,
}
# 页面锚点 → 该页面对应的状态：认出比当前更靠后的页面时直接跳过去。
PAGE_ANCHORS = (
    ("relic_guide", "星际和平指南", [103, 39, 221, 66]),
    ("relic_index", "生存索引", [101, 63, 203, 99]),
    ("relic_list", "位面饰品快速提取", [900, 317, 1189, 354]),
    ("relic_prepare", "位面饰品提取", [101, 43, 251, 74]),
    ("relic_prepare", "侵蚀隧洞", [102, 48, 204, 84]),
    ("relic_team", "队伍", [103, 39, 145, 65]),
    ("relic_support_list", "支援列表", [248, 74, 348, 103]),
    ("relic_support_list", "支援角色", [384, 76, 472, 103]),
    # 副本内的战斗场景：左上角是「差分宇宙」。认出它就说明已经在副本里了，
    # 内外圈共用这一个锚点，直接用接敌流程继续，不必退回入口重找。
    ("relic_skill", "差分宇宙", [57, 14, 148, 42]),
)
# 运行模式 → 左侧菜单里要点击的分类名。
MODULE_CATEGORY = {"inner": "饰品提取", "outer": "侵蚀隧洞"}
# 支援角色页「替换几号位」四个位置的落框，按号位顺序；两边的页面布局不同：
# 内圈是页面底部一排小按钮，外圈是页面中部一排角色位。
SUPPORT_SLOTS = {
    "inner": ([631, 805, 684, 831], [720, 803, 777, 832],
              [821, 805, 873, 834], [908, 802, 959, 833]),
    "outer": ([745, 497, 791, 522], [1056, 529, 1108, 559],
              [1357, 496, 1439, 537], [1671, 524, 1740, 570]),
}


class DailyKernel(ScriptKernel):
    """日常内核。"""

    def __init__(self):
        super().__init__()
        self.config = load_module_settings(__file__)["daily_relic"]
        self._validate_config()
        # 本张挑战在准备页设定的次数；None 表示还没按配置与开拓力算过。
        self.count_target = None
        # 列表滚动的固定方向（-8 向下、8 向上），一次挑战内不再翻转。
        self.list_direction = None
        # 刚切到副本列表时已经观察过的帧数：先确认列表换过来了再决定滚动方向。
        self.list_settle = 0
        # 开始接敌的时间；超过 180 秒还没进战斗就报错停下。
        self.approach_time = None
        # 各识别区域上次滚动后的文字与连续未变化的帧数，用于判断列表是否已经滚到底。
        self.list_texts = {}
        self.list_misses = {}
        # 挑战次数已经点过几轮，用于判断点按是否失效。
        self.count_clicks = 0
        # 支援角色页内的点击阶段：0 仅好友开关、1 替换位置、2 支援角色。
        self.support_phase = 0
        # 准备页副本不符时已经刷新列表的次数，避免无限刷新。
        self.refresh_count = 0
        # 上一次按 ESC 的时间；两次 ESC 之间至少隔 5 秒。
        self.esc_time = None
        # 上一次状态机命中的事件名，用于只在变化时打一条日志。
        self.last_action = None
        # 上一次按指南键的时间；两次之间至少隔 10 秒，避免慢机器上连按把页面按关。
        self.guide_time = None
        # 上一次原地攻击的时间。
        self.attack_time = None
        # 委托页连续没认出可领奖励的帧数，用于区分「没奖励」与「页面还没渲染」。
        self.commission_misses = 0
        # 每日实训已点击「领取」的次数与上一次落框，避免对同一张卡片连点。
        self.claim_clicks = 0
        self.claimed_box = None
        self.claim_waits = 0
        # 活跃度连续读不到的次数，用于区分被提示挡住和真读不出来。
        self.progress_retries = 0
        # 消耗品筛选步骤、已点格数与上一次读到的物品名。
        self.snack_phase = 0
        self.snack_index = 0
        self.snack_last_name = None
        self.snack_same = 0
        # 每类「只在内容变化时打一条」的 debug 上次内容。
        self.last_debug = {}
        # 上一轮算出的「进入」落框，用来判断列表是否已经停止滚动。
        self.enter_box = None
        # 上一轮算出的分类落框，同样用来跳过滚动途中那一帧的坐标。
        self.category_box = None
        # 初始状态：从任意界面起步，入口阶段由「退回入口」按 5 秒间隔逐级退回。
        self.update_state("relic_entry")
        # 普通模式的模块按钮直接启动本内核：装载模块自带的动作脚本；
        # 调试模式里选了别的脚本时由运行入口覆盖。
        script = Path(__file__).parent / "actions" / "daily_relic.json"
        self.default_json = load_actions(script)
        self.default_json_path = str(script)

    def _validate_config(self):
        """启动前校验运行模式与支援相关配置，非法值直接报中文错误。

        界面上这些都只能在合法范围里选，但配置文件能手改；不校验的话会跑到一半才
        抛 KeyError / IndexError，现场看不出是哪个配置写错了。

        Raises:
            ValueError: 运行模式、支援替换位置、支援角色序号或秘技顺序不合法。
        """
        module = self.config["module"]
        if module not in MODULE_CATEGORY:
            raise ValueError(f"运行模式只能是 inner 或 outer，当前配置为 {module!r}")
        # 两种模式的支援配置都校验：现在用不到的那份也可能被手改，切模式时才炸更难看。
        for mode in MODULE_CATEGORY:
            slot = int(self.config[f"{mode}_support_slot"])
            if slot not in SUPPORT_SLOT_CHOICES:
                raise ValueError(f"{mode} 的支援替换位置只能是 {SUPPORT_SLOT_CHOICES}，当前配置为 {slot}")
            index = int(self.config[f"{mode}_support_index"])
            if index not in SUPPORT_ROLE_CHOICES:
                raise ValueError(f"{mode} 的支援角色序号只能是 {SUPPORT_ROLE_CHOICES}，当前配置为 {index}")
        order = str(self.config["inner_skill_order"])
        if not set(order) <= {"1", "2", "3", "4"}:
            raise ValueError(f"秘技顺序只能包含 1~4，当前配置为 {order!r}")

    def prepare_script(self):
        """运行前把游戏窗口切到前台，再启动键鼠线程。

        后台模式截图不抢焦点，但鼠标点击仍落在最前面的窗口上，
        所以在真正下发输入前必须先让游戏回到前台。
        """
        set_forground()
        super().prepare_script()

    def _stopped(self):
        """是否已经收到停止任务或停止内核的信号。

        Returns:
            True 表示不应再下发任何输入。
        """
        return self._stop or get_global_stop_flag()

    def press_esc(self):
        """退回上一级；两次 ESC 之间至少隔 5 秒。

        ESC 是开关式的：刚打开手机页面又按一次就会关掉。这里给 ESC 单独限速——
        5 秒内状态机照常识别，手机页面、指南页面等标志一出现就由对应事件点击推进；
        只有 5 秒过去仍没有任何标志时才补按一次 ESC。

        Returns:
            True 表示这次真的按下了 ESC。
        """
        if self._stopped():
            return False
        now = time.monotonic()
        if self.esc_time is not None and now - self.esc_time < 5:
            return False
        key_mouse_manager.press("esc")
        self.esc_time = now
        return True

    def back_out(self):
        """入口阶段的兜底退回：画面其实已经到更靠后的页面时，先按当前页面推进，别按 ESC。

        顺序很关键——状态机每轮只执行第一个命中事件，而本方法所在的兜底事件靠 state_only 触发，
        永远会命中；因此先让 fast_forward 判一次：只要画面已经在更靠后的页面，就把状态跳过去，
        这一轮不再按 ESC；确实还停在未知界面时才退回上一级。
        """
        if self._stopped():
            return
        before = self.state
        self.fast_forward()
        if self.state != before:
            return
        if self.press_esc():
            self._log_once("back_out", "没认出已知界面，按 ESC 退回上一级（当前 %s）", self.state)

    def open_guide(self):
        """在大世界按「星际和平指南」键打开指南页，跳过手机页面。

        键位取用户配置里的逻辑名 interastral_peace_guide，改键也跟得上。
        指南键是开关式的：老机器上页面加载慢，连按第二下会把刚打开的页面关掉，
        所以这里最多 10 秒按一次——按完等页面加载，等不到再补按。
        """
        if self._stopped():
            return
        if self._text_visible("星际和平指南", [103, 39, 221, 66]):
            self.update_state("relic_guide")
            return
        now = time.monotonic()
        if self.guide_time is not None and now - self.guide_time < 10:
            return
        self.guide_time = now
        CUS_LOGGER.debug("按指南键打开指南页")
        key_mouse_manager.press("interastral_peace_guide")
        self.update_state("relic_guide")

    def retry_guide(self):
        """指南页还没出现时才补按指南键，且必须确认还停在大世界。

        停在手机页面或别的界面时按指南键没有意义，还可能把页面按乱：那种情况交给
        「手机页面点指南」或「退回入口」继续，这里直接不动。
        """
        if self._stopped():
            return
        if self._text_visible("星际和平指南", [103, 39, 221, 66]):
            return
        if not self.check("smartphone", 32, 67, threshold=0.96):
            return
        self.open_guide()

    def click_guide(self):
        """手机页面点「指南」进指南页：指南键不管用时的退路。"""
        if self._stopped():
            return
        found = self._match_box("指南", GUIDE_ICON_BOX)
        if found is None:
            return
        CUS_LOGGER.debug("手机页面点「指南」")
        self.click_box(found)
        self.update_state("relic_guide")

    def _log_once(self, tag, message, *args):
        """同类提示只在内容变化时打一条，避免每轮轮询刷同一条 debug。

        Args:
            tag: 这条提示的类别，同一类别共用一份上次内容。
            message: 带占位符的日志文本。
            *args: 占位符参数。
        """
        text = message % args if args else message
        if self.last_debug.get(tag) == text:
            return
        self.last_debug[tag] = text
        CUS_LOGGER.debug(text)

    def _match_box(self, text, box):
        """返回区域里第一条含指定文字的识别框。

        Args:
            text: 要匹配的文字。
            box: 识别区域 [左, 上, 右, 下]。

        Returns:
            [左, 上, 右, 下]；没有命中时返回 None。
        """
        for item in self.ts.find_with_box(box=box, redundancy=20):
            if text in clean_text(item["raw_text"]):
                return [int(value) for value in item["box"]]
        return None

    def _page_texts(self, box=None):
        """整页（或指定区域）识别到的文字与坐标，用于落点不对时定位。

        Args:
            box: 识别区域 [左, 上, 右, 下]；不传时取整个画面。

        Returns:
            [(文字, [左, 上, 右, 下]), ...]
        """
        items = self.ts.find_with_box(box=box or [0, 0, self.xx, self.yy], redundancy=0)
        return [(clean_text(item["raw_text"]), [int(value) for value in item["box"]])
                for item in items]

    def _text_visible(self, text, box):
        """区域里是否出现指定文字。

        Args:
            text: 要识别的文字。
            box: 识别区域 [左, 上, 右, 下]。

        Returns:
            True 表示该文字在当前画面里。
        """
        return any(text in clean_text(item["raw_text"])
                   for item in self.ts.find_with_box(box=box, redundancy=20))

    def _click_text_in(self, text, box):
        """在区域里认出文字才点它；认不到就什么都不做，绝不点区域中心。

        盲点区域中心会落到框里其它按钮或角色卡上（准备页的支援入口框就压在队伍卡位上方），
        一旦点错会把队伍里的角色下掉，所以这里只认字、不兜底。

        Args:
            text: 要识别的文字。
            box: 识别区域 [左, 上, 右, 下]。

        Returns:
            True 表示认到并点了一次。
        """
        found = self._match_box(text, box)
        if found is None:
            return False
        self.click_box(found)
        return True

    def run_static(self, *args, **kwargs):
        """每轮记录一次状态机结果，识别不到时明确提示是加载中或未知页面。"""
        name, result = super().run_static(*args, **kwargs)
        if name != self.last_action:
            self.last_action = name
            if name:
                CUS_LOGGER.debug("状态机执行「%s」，当前状态 %s", name, self.state)
            else:
                CUS_LOGGER.debug(
                    "状态机本轮没有命中任何已知界面（加载中或未知页面），不执行任何动作，当前状态 %s",
                    self.state,
                )
        return name, result


    def fast_forward(self):
        """画面已经走到更靠后的页面时，直接跳到那一页继续推进，绝不回退。

        典型场景：已经手动打开正确的副本准备页，而状态还停在找副本/选分类——
        这时按准备页继续走，不必从头再来。过渡帧里旧页面锚点还在、新页面还没画出来时
        本方法只会原地不动（目标状态次序不更靠后就不动），不会把状态倒回上一级。
        收尾链按固定线性流程执行，这里不参与。
        """
        if self._stopped() or self.state.startswith("reward_"):
            return
        best_state, best_stage = None, STAGE_ORDER.get(self.state, 0)
        for state, text, box in PAGE_ANCHORS:
            if STAGE_ORDER[state] <= best_stage:
                continue
            if self._text_visible(text, box):
                best_state, best_stage = state, STAGE_ORDER[state]
        # 外圈副本列表没有文字锚点，用画面上的副本图标认。
        if STAGE_ORDER["relic_list"] > best_stage and self.check("relic", 324, 828, threshold=0.99):
            best_state, best_stage = "relic_list", STAGE_ORDER["relic_list"]
        if best_state is None:
            return
        if best_state == "relic_skill" and STAGE_ORDER.get(self.state, 0) < STAGE_ORDER["relic_prepare"]:
            # 一开局人就已经站在副本里：不知道是哪个副本，但继续接敌比退回入口更合理。
            CUS_LOGGER.warning("未知内圈副本（当前状态 %s），按已进入副本直接开始接敌流程", self.state)
        CUS_LOGGER.debug("画面已到 %s，状态从 %s 直接推进过去", best_state, self.state)
        self.update_state(best_state)

    def select_category(self):
        """点击配置的副本分类；分类不在左侧菜单可见范围时滚动一屏。

        Raises:
            RuntimeError: 菜单滚到底仍看不到配置的分类。
        """
        if self._stopped():
            return
        # 不在生存索引页时不动：刷新列表途中停在实训页签的话，先点回生存索引页签。
        if not self._text_visible("生存索引", TAB_LINE_BOX):
            if self._text_visible("每日实训", TAB_LINE_BOX):
                self.click_position(TAB_INDEX)
            return
        target = MODULE_CATEGORY[self._module()]
        box = [240, 270, 700, 890]
        items = self.ts.find_with_box(box=box, redundancy=20)
        texts = [clean_text(item["raw_text"]) for item in items]
        hits = [(item, text) for item, text in zip(items, texts) if target in text]
        if hits:
            # 菜单项挨得很近，OCR 有时会把相邻两行并成一个高框：优先选最矮的（单行）。
            item, text = min(hits, key=lambda hit: hit[0]["box"][3] - hit[0]["box"][1])
            # 菜单滚动带惯性：滚动途中截到的框，下一帧已经偏移了整行，照它点就会点到
            # 滚上来占住这个位置的别的分类。两轮算出的落框一致才点，否则等下一轮。
            if self.category_box is None or max(
                    abs(now_value - old_value)
                    for now_value, old_value in zip(item["box"], self.category_box)) > 8:
                self.category_box = item["box"]
                self._log_once("category_box", "分类 %s 的落框还在变化，本轮不点击：%s", target, item["box"])
                return
            CUS_LOGGER.debug("点击分类 %s：识别内容 %s 识别框 %s", target, text, item["box"])
            self.category_box = None
            self.click_box(item["box"])
            # 点中分类后同一页面右侧就是副本列表，交给下一步定位目标副本；
            # 上一页的静止判断与方向全部作废，否则会拿旧列表的结论去滚新列表。
            self.list_direction = None
            self.list_settle = 0
            self.list_texts = {}
            self.list_misses = {}
            self.update_state("relic_list")
            return
        visible = [index for index, name in enumerate(MENU_ITEMS)
                   if any(name in text for text in texts)]
        if not visible:
            self._log_once("menu_miss", "左侧菜单没认出分类 %s，本帧识别到：%s", target, texts)
            return
        target_index = MENU_ITEMS.index(target)
        nearest = min(visible, key=lambda index: abs(index - target_index))
        # 正数向上滚动：目标在可见项下方时向下滚，一次四格。
        self._scroll_once(box, (470, 580), -4 if nearest < target_index else 4,
                          texts, f"左侧菜单滚到底仍找不到分类：{target}")

    def enter_dungeon(self):
        """点击配置副本同一行的「进入」，点中后把状态推进到副本准备页。

        Raises:
            RuntimeError: 列表滚到底仍未找到配置的副本。
        """
        if self._stopped():
            return
        module = self._module()
        name = str(self.config[module]).split("-", 1)[0]
        box = [660, 260, 1700, 990]
        items = self.ts.find_with_box(box=box, redundancy=20)
        texts = [clean_text(item["raw_text"]) for item in items]
        if not texts:
            # 刚切到这一页时列表还没渲染出来：先把这一帧等过去再判方向，
            # 否则会对着空列表滚一屏，把本来就在最上方的副本滚走。
            self._log_once("list_loading", "副本列表还没识别出文字（可能在加载），本轮不滚动")
            return
        named = [item for item, match in zip(items, texts) if self._name_matches(name, match)]
        if named and not any(name in match for match in texts):
            self._log_once("name_fuzzy", "副本名与配置有一字误差，按 %s 处理：%s", name, texts)
        if not named:
            self._log_once("list_miss", "副本列表没找到 %s，本帧识别到：%s", name, texts)
            # 滚动后列表位置会变，之前记下的落框作废。
            self.enter_box = None
            # 刚切到这一页时右侧列表还在换内容：先空看两帧，确认新列表已经渲染出来，
            # 免得对着上一页的列表先滚一屏，把本来就在最上方的副本滚走又滚回来。
            if self.list_settle < 2:
                self.list_settle += 1
                CUS_LOGGER.debug("刚切到副本列表，先观察一帧再决定是否滚动（%s/2）", self.list_settle)
                return
            # 每次滚 8 格，滚完下一轮再判断一次副本名，命中就停；
            # 方向按配置里录入的先后顺序判断（目标在可见副本下方就向下滚）。
            ticks = self._list_ticks(name, texts)
            self._scroll_once(box, (1358, 698), ticks, texts, f"副本列表滚到底仍找不到：{name}")
            return
        name_box = named[0]["box"]
        row_y = (name_box[1] + name_box[3]) / 2
        for item in items:
            enter_box = item["box"]
            if "进入" not in clean_text(item["raw_text"]) or enter_box[0] <= name_box[2]:
                continue
            # 「进入」必须与副本名同一行，允许 40 像素的纵向偏差。
            if abs((enter_box[1] + enter_box[3]) / 2 - row_y) > 40:
                continue
            # 列表可能还在滚动：两轮算出的落框一致才点，否则等下一轮，
            # 避免用滚动前的旧坐标点到别的行。
            if self.enter_box is None or max(
                    abs(now_value - old_value)
                    for now_value, old_value in zip(enter_box, self.enter_box)) > 8:
                self.enter_box = enter_box
                return
            self.enter_box = None
            self.click_box(enter_box)
            self.update_state("relic_prepare")
            return
        self._log_once("enter_miss", "已识别到副本 %s，但没找到同一行的「进入」，本轮不动作", name)

    def prepare_page(self):
        """准备页：确认是配置的副本，调好挑战次数，再按配置推进到支援或挑战。

        Raises:
            RuntimeError: 挑战次数连续多轮停在同一个值，点按没有生效。
        """
        if self._stopped():
            return
        module = self._module()
        # 内外圈准备页的开拓力、次数、减号位置各自不同；加号两边在同一个位置。
        stamina_box, count_box, minus_box = {
            "inner": ([1505, 51, 1597, 78], [1600, 857, 1711, 883], [1447, 882, 1497, 911]),
            "outer": ([1640, 53, 1739, 80], [1491, 850, 1601, 879], [1223, 876, 1276, 906]),
        }[module]
        loaded = self._dungeon_name_visible()
        if loaded is None:
            return
        if loaded is False:
            # 准备页不是配置的副本：ESC 退回生存索引，切到每日实训再切回分类刷新列表，
            # 不用一路退回大世界。连续刷新两次仍不符说明配置或界面有问题。
            self.refresh_count += 1
            if self.refresh_count > 2:
                raise RuntimeError("准备页副本与配置不符，刷新列表后仍不对，请检查配置的副本名")
            CUS_LOGGER.debug("准备页副本与配置不符，退回生存索引刷新列表（第 %s 次）", self.refresh_count)
            key_mouse_manager.press("esc")
            self.update_state("relic_refresh")
            return
        self.refresh_count = 0
        # 单次挑战最多设定 6 次；目标次数只算一次，不随每次点击重算。
        if self.count_target is None:
            planned = self._planned_runs(stamina_box)
            if planned <= 0:
                CUS_LOGGER.info("开拓力不足以再刷一次 %s，直接进入收尾", MODULE_CATEGORY[module])
                self.update_state("relic_done")
                return
            self.count_target = min(max(RUNS_CHOICES), planned)
        want = self.count_target
        current = self._read_number(count_box)
        if current is None:
            return
        if current != want:
            # 一次把差值点完，下一轮只核对一次结果；连续三轮仍不对再报错。
            self.count_clicks += 1
            if self.count_clicks > 3:
                raise RuntimeError(f"挑战次数连续 {self.count_clicks} 轮仍停在 {current}，无法调整到 {want}")
            for _ in range(abs(want - current)):
                self.click_box([1816, 873, 1876, 911] if want > current else minus_box)
            return
        self.count_clicks = 0
        if module == "outer":
            # 外圈先在准备页点「挑战」进队伍页，支援在队伍页处理。
            self.update_state("relic_outer_challenge")
            return
        if not self._support_on():
            self.update_state("relic_challenge")
            return
        # 内圈支援入口在准备页右下角；认不到入口就等下一轮，不盲点。
        self.support_phase = 0
        if not self._click_text_in("支援", [688, 739, 878, 912]):
            self._log_once("support_entry_miss", "准备页还没认出「支援」入口，等界面刷新")
            return
        self.update_state("relic_support_list")

    def pick_support_slot(self):
        """支援角色页：按界面顺序选替换位置和支援角色，内外圈各用自己的配置。

        内外圈是同一个页面（顶部页签内圈叫「支援列表」、外圈叫「支援角色」），
        但「替换几号位」的落框不同，见 SUPPORT_SLOTS。每轮只点一下：先按配置打开「仅好友支援」，
        再点替换几号位，最后点列表第 N 个角色；选完内圈回准备页点开始挑战，
        外圈还要点一次「确认」才回到队伍页。
        """
        if self._stopped():
            return
        module = self._module()
        if self.support_phase == 0:
            # 支援角色页的布局每轮都要核对：外圈的落框和配置都还在调，这一帧把整页
            # 识别结果记下来，落点不对时能直接从日志看出按钮和角色列表在哪。
            # 整页 OCR 很贵，只有真的打开 debug 时才做。
            if CUS_LOGGER.isEnabledFor(logging.DEBUG):
                CUS_LOGGER.debug("支援角色页本帧识别到：%s", self._page_texts())
            self.support_phase = 1
            if self.config[f"{module}_support_friend"]:
                # 「仅好友支援」开关在支援角色页左上角；ON 图认得到说明它已经开着，
                # 这时再点一下反而会把它关掉，所以先判图再决定要不要点。内外圈同一处。
                if self.check("ON", 76, 142, threshold=0.995):
                    CUS_LOGGER.debug("「仅好友支援」已经是开启状态，本轮不点（相似度 %s）", self.tm)
                else:
                    CUS_LOGGER.debug("「仅好友支援」没开，点开关打开（相似度 %s）", self.tm)
                    self.click_position([71, 145])
            return
        if self.support_phase == 1:
            # 先点配置的替换几号位，界面才会把角色列表切到该位置。
            slot = int(self.config[f"{module}_support_slot"])
            CUS_LOGGER.debug("支援角色页：点 %s 号位 %s", slot, SUPPORT_SLOTS[module][slot - 1])
            self.click_box(SUPPORT_SLOTS[module][slot - 1])
            self.support_phase = 2
            return
        # 支援角色页左侧可选角色位置，从上到下最多 6 个；选完回准备页点开始挑战。
        rows = ([72, 248], [71, 384], [70, 521], [71, 660], [70, 797], [70, 934])
        index = int(self.config[f"{module}_support_index"])
        CUS_LOGGER.debug("支援角色页：选第 %s 个支援角色", index)
        self.click_position(rows[index - 1])
        self.support_phase = 0
        if module == "outer":
            # 外圈支援页多一个「确认」，点完才回到队伍页。
            self.update_state("relic_support_outer")
            return
        self.update_state("relic_challenge")

    def team_page(self):
        """外圈队伍页：按配置先点「支援」进支援角色页，否则交给脚本点开始挑战。"""
        if self._stopped():
            return
        if not self._support_on():
            self.update_state("relic_team_start")
            return
        self.support_phase = 0
        self.click_box([1053, 969, 1104, 999])
        self.update_state("relic_support_list")

    def release_skill(self):
        """按配置的顺序放完秘技：切号位 → 等换人 → 放秘技 → 等下一轮。

        两个键都走 game_keys 里的逻辑键名，不写死物理键；两档延时来自配置，
        换人动画和秘技动画各留够时间，比靠轮询间隔凑节奏稳得多。
        """
        if self._stopped():
            return
        order = str(self.config["inner_skill_order"])
        if not order:
            self.update_state("relic_approach")
            return
        switch_delay = float(self.config["inner_skill_switch_delay"])
        delay = float(self.config["inner_skill_delay"])
        for index, slot in enumerate(order):
            if self._stopped():
                return
            key_mouse_manager.press(f"role_{slot}")
            key_mouse_manager.wait()
            key_mouse_manager.sleep(switch_delay)
            key_mouse_manager.wait()
            key_mouse_manager.press("technique")
            key_mouse_manager.wait()
            if index < len(order) - 1:
                key_mouse_manager.sleep(delay)
                key_mouse_manager.wait()
        self.update_state("relic_approach")

    def approach_enemy(self):
        """向小地图红点靠近并攻击：一次轮询只走一步或砍一刀。

        Raises:
            RuntimeError: 接敌超过 180 秒仍没进战斗（卡墙、队伍没进场等）。
        """
        if self._stopped():
            return
        if self.check("auto_2", 112, 83) or self.check("battle", 1842, 1056):
            # 已经进入战斗：自动战斗由「开启自动战斗」事件负责，这里停手即可。
            self.approach_time = None
            return
        if self.approach_time is None:
            self.approach_time = time.monotonic()
        elif time.monotonic() - self.approach_time > 180:
            raise RuntimeError("接敌超时：180 秒内没有进入战斗，请检查队伍与路线")
        distance = self._enemy_distance()
        if distance is not None and distance > 18:  # 距小地图中心 18 像素内即视为进入攻击范围
            key_mouse_manager.press("move_w", 0.3)
            return
        # 看不到红点（多半已经和敌人贴在一起）或已进入攻击范围：原地砍一刀。
        # 2 秒内只砍一次，避免每轮都点鼠标。
        now = time.monotonic()
        if self.attack_time is not None and now - self.attack_time < 2:
            return
        self.attack_time = now
        key_mouse_manager.click_point(self.xx // 2, self.yy // 2)

    def auto_battle(self):
        """按 V 打开自动战斗；与寰宇命途内核的处理一致。"""
        if self._stopped():
            return
        key_mouse_manager.press("V")

    def count_run(self):
        """退出关卡后结束本张挑战：清掉本次运行的临时状态，进入收尾。"""
        self.approach_time = None
        self.list_texts = {}
        self.list_misses = {}
        self.list_direction = None
        self.list_settle = 0
        self.count_target = None
        self.update_state("relic_done")






    def finish_relic(self):
        """遗器本轮数刷完：按配置去领每日奖励，或直接结束任务。"""
        self.list_texts = {}
        self.list_misses = {}
        self.claim_clicks = 0
        self.claimed_box = None
        self.claim_waits = 0
        self.commission_misses = 0
        self.progress_retries = 0
        self.snack_phase = 0
        self.snack_index = 0
        self.snack_last_name = None
        self.snack_same = 0
        if self.config["daily_reward"]:
            self.update_state("reward_phone")
            return
        self.finish_task()

    def open_commission_page(self):
        """手机页面点委托入口；还没到手机页面就先按一次 ESC 把它打开。

        收尾阶段 ESC 是开关式的：只有确认还停在大世界（smartphone 认得到）才补按，
        其余情况一律只等不按——这样哪怕提前进了本状态也不会卡死。
        """
        if self._stopped():
            return
        if self._match_box("指南", GUIDE_ICON_BOX) is not None:
            CUS_LOGGER.debug("收尾：手机页面点「委托」入口")
            self.click_position([1731, 408])
            key_mouse_manager.wait()
            self.update_state("reward_commission")
            return
        if self.check("smartphone", 32, 67, threshold=0.96):
            # 还停在大世界：ESC 打开手机页面，下一轮再来点委托。
            if self.press_esc():
                CUS_LOGGER.debug("收尾：大世界按 ESC 打开手机页面")
            return
        self._log_once("phone_page_wait", "等手机页面出现「指南」入口")

    def claim_commission(self):
        """委托页：等页面渲染出来再点「领取奖励」，确认真的没得领才退出。

        刚点进委托页的那几帧按钮还没画出来，单帧认不到不等于没有奖励；
        所以先连等几帧，并且要认到「委托」标题才允许判定委托页已无奖励。
        """
        if self._stopped():
            return
        # 委托页右侧整块区域按文字找「领取奖励」，多行委托都能覆盖到。
        claim_box = self._match_box("领取奖励", [700, 300, 1900, 1010])
        if claim_box is not None:
            CUS_LOGGER.debug("委托页：领取奖励 %s", claim_box)
            self.commission_misses = 0
            self.click_box(claim_box)
            key_mouse_manager.wait()
            self.update_state("reward_got_close")
            return
        self.commission_misses += 1
        if self.commission_misses < 3:
            CUS_LOGGER.debug("委托页还没认出「领取奖励」，再等一帧（%s/3）", self.commission_misses)
            return
        # 委托页左上角标题实测 委托 [101,50,157,85]，放宽一点再用。
        if not self._text_visible("委托", [90, 40, 200, 100]):
            self._log_once("commission_wait", "委托页还没出现，继续等")
            return
        self.commission_misses = 0
        self.update_state("reward_got_close")

    def close_commission_page(self):
        """领完委托后逐级退回手机页面：关提示一次、退委托页一次，直到认到「指南」。

        等不到就一直等（每次 ESC 之间仍受 5 秒限速），不跳过——跳过会把后面的领奖全带偏。
        """
        if self._stopped():
            return
        if self._text_visible("指南", GUIDE_ICON_BOX):
            self.update_state("reward_phone_guide")
            return
        if self.press_esc():
            # 一次 ESC 只关掉获得物品提示，要再按一次才退委托页，所以这里会连着按。
            self._log_once("commission_esc", "委托页按 ESC 退回上一级")

    def open_reward_guide(self):
        """手机页面点「指南」；认不到入口就等，不盲点也不跳过。"""
        if self._stopped():
            return
        guide_box = self._match_box("指南", GUIDE_ICON_BOX)
        if guide_box is None:
            self._log_once("reward_guide_miss", "手机页面还没出现「指南」入口，继续等")
            return
        self.click_box(guide_box)
        key_mouse_manager.wait()
        self.update_state("reward_guide")

    def goto_training(self):
        """指南页切到「每日实训」页签；页签已经是每日实训就不再点。"""
        if self._stopped():
            return
        if not self._text_visible("每日实训", TAB_LINE_BOX):
            self.click_position(TAB_DAILY)
            key_mouse_manager.wait()
        self.update_state("reward_training")

    def claim_training(self):
        """每日实训页：确认页签后逐个领奖，再按活跃度决定「合成奇巧零食」或收尾。

        页签不对就只点页签、别的什么都不点——盲点会把页面点走，和领奖流程抢起来。
        """
        if self._stopped():
            return
        # 页签行实测 每日实训 [104,66,203,94]。
        if not self._text_visible("每日实训", TAB_LINE_BOX):
            self._log_once("training_miss", "还没到每日实训页，点页签等它出来")
            self.click_position(TAB_DAILY)
            key_mouse_manager.wait()
            return
        # 整块实训页正文按文字找「领取」，不写死单个按钮的坐标。
        matched = self._match_box("领取", [150, 120, 1900, 1050])
        if self.claim_clicks < 20 and matched is not None:
            if self.claimed_box is not None and max(
                    abs(now_value - old_value)
                    for now_value, old_value in zip(matched, self.claimed_box)) <= 8:
                # 还是上一次点过的那个按钮：界面还没刷新，这一轮只等不点。
                self.claim_waits += 1
                if self.claim_waits <= 3:
                    CUS_LOGGER.debug("「领取」还在上次点过的位置，等界面刷新（%s/3）", self.claim_waits)
                    return
            self.claimed_box = matched
            self.claim_waits = 0
            self.claim_clicks += 1
            self.click_box(matched)
            # 点完等这一下真正执行完：点击是入队执行的，不等的话下一帧还是点之前的画面。
            key_mouse_manager.wait()
            return
        # 进度条上那一排刻度数字，用来判断是否已满 500、是否卡在 400。
        progress = self._read_number([316, 344, 368, 370])
        if progress is None:
            # 领奖的获得物品提示可能压住进度条：连读三帧都读不到再往下判。
            self.progress_retries += 1
            if self.progress_retries <= 3:
                CUS_LOGGER.debug("每日实训页没读到活跃度，先等一帧（%s/3）", self.progress_retries)
                return
        else:
            self.progress_retries = 0
        if progress == 500:
            # 活跃度满 500：点进度条末尾的礼物图标领掉里程碑奖励。
            self.click_box([1581, 298, 1643, 333])
            self.update_state("reward_done")
            return
        if progress == 400:
            # 活跃度卡在 400：合成奇巧零食补满，回到实训页后再判一次 500。
            self.snack_phase = 0
            self.snack_index = 0
            self.snack_last_name = None
            self.snack_same = 0
            self.update_state("reward_snack")
            return
        CUS_LOGGER.warning("每日实训活跃度读到 %s，没能确认已满 500，500 里程碑奖励可能没领；本次收尾继续",
                           progress)
        self.update_state("reward_done")

    def find_snack(self):
        """消耗品合成：先用筛选规则把列表缩小，再逐格点开按右侧名字找奇巧零食。"""
        if self._stopped():
            return
        if self.snack_phase == 0:
            self.snack_phase = 1
            CUS_LOGGER.debug("消耗品合成：打开筛选")
            filter_box = self._match_box("筛选", [140, 960, 240, 1010])
            if filter_box is not None:
                self.click_box(filter_box)
            return
        if self.snack_phase == 1:
            self.snack_phase = 2
            CUS_LOGGER.debug("消耗品合成：打开筛选规则")
            # 筛选面板里的「筛选规则」。
            self.click_box([398, 251, 530, 286])
            return
        if self.snack_phase == 2:
            self.snack_phase = 3
            CUS_LOGGER.debug("消耗品合成：选中筛选项")
            # 要勾选的那一类筛选项。
            self.click_position([918, 519])
            return
        if self.snack_phase == 3:
            self.snack_phase = 4
            CUS_LOGGER.debug("消耗品合成：确认筛选")
            # 应用筛选的「确认」。
            self.click_box([1159, 794, 1213, 825])
            return
        # 右侧详情里的物品名：格子本身只有图标和数量。
        name = (self.ts.ocr_one_row(self.screen, [960, 150, 1400, 215]) or "").strip()
        if "奇巧零食" in name:
            CUS_LOGGER.debug("找到奇巧零食，准备合成")
            self.update_state("reward_snack_ready")
            return
        same = self.snack_same + 1 if name and name == self.snack_last_name else 0
        self.snack_same = same
        self.snack_last_name = name
        if same >= 3:
            CUS_LOGGER.warning("消耗品列表点到底也没找到奇巧零食，跳过本次合成")
            self.update_state("reward_done")
            return
        total = len(SNACK_GRID_X) * len(SNACK_GRID_Y)
        if self.snack_index >= total:
            CUS_LOGGER.warning("消耗品列表点满 %s 格也没找到奇巧零食，跳过本次合成", total)
            self.update_state("reward_done")
            return
        x = SNACK_GRID_X[self.snack_index % len(SNACK_GRID_X)]
        y = SNACK_GRID_Y[self.snack_index // len(SNACK_GRID_X)]
        self.snack_index += 1
        CUS_LOGGER.debug("点开消耗品第 %s/%s 格 (%s, %s)", self.snack_index, total, x, y)
        key_mouse_manager.click_point(x, y)
        key_mouse_manager.wait()

    def finish_task(self):
        """结束本次任务：停止状态机，由运行入口释放截图与输入资源。"""
        CUS_LOGGER.info("日常任务完成")
        self.stop()

    def goto_index(self):
        """指南页切到「生存索引」页签；页签已经是生存索引就不再点。

        指南页会记住上次打开的页签：已经停在生存索引上时再点一下页签，
        等于在原页面上空点一次。
        """
        if self._stopped():
            return
        # 指南窗口左上角第二行是当前页签，实测 生存索引 [101,63,203,99]。
        if not self._text_visible("生存索引", TAB_LINE_BOX):
            self.click_position(TAB_INDEX)
        self.update_state("relic_index")



    def _name_matches(self, name, text):
        """识别到的文字里是否有配置的副本名，允许一个字以内的识别误差。

        OCR 会把生僻字认错（例如「蠹役饥肠」认成「蠢役饥肠」），这里逐窗口允许一次
        替换或插入，只用来确认目标副本名本身。

        Args:
            name: 配置的副本短名。
            text: 单条识别结果。

        Returns:
            True 表示这条识别结果就是配置的副本。
        """
        if name in text:
            return True
        padded = text + chr(32)
        return any(is_edit_distance_at_most_one(name, padded[index:index + len(name)],
                                           padded[index + len(name)])
                   for index in range(len(padded) - len(name)))

    def _list_ticks(self, name, texts):
        """按录入顺序判断目标副本在可见副本的上方还是下方。

        Args:
            name: 配置的副本短名。
            texts: 本帧列表区域识别到的文字。

        Returns:
            滚动格数：目标在下方为 -8（向下），在上方为 8（向上）；无法判断时向下。
        """
        if self.list_direction is not None:
            return self.list_direction
        module = self._module()
        order = [item.split("-", 1)[0] for item, _ in (INNER_TARGETS if module == "inner" else OUTER_TARGETS)]
        target = next((index for index, item in enumerate(order) if item.startswith(name)), None)
        visible = [index for index, item in enumerate(order)
                   if any(self._name_matches(item, text) for text in texts)]
        if target is None or not visible:
            return -8
        nearest = min(visible, key=lambda index: abs(index - target))
        self.list_direction = -8 if nearest < target else 8
        return self.list_direction

    def _dungeon_name_visible(self):
        """读取准备页中央的副本名，判断是否是配置的那个副本。

        只有认到完整的「副本名|难度」那一行且名字对不上时才判定走错副本；
        认到的是别的东西或还没渲染出来时返回 None，避免把正确的准备页踢掉。

        Returns:
            True 是配置的副本；False 明确是别的副本；None 无法判断。
        """
        box = {"inner": [500, 105, 1100, 150], "outer": [1209, 124, 1496, 155]}[self._module()]
        texts = [clean_text(item["raw_text"])
                 for item in self.ts.find_with_box(box=box, redundancy=20)]
        if not texts:
            return None
        name = str(self.config[self._module()]).split("-", 1)[0]
        if any(self._name_matches(name, text) for text in texts):
            return True
        if any("难度" in text for text in texts):
            return False
        return None

    def _module(self):
        """返回配置的运行模式。

        Returns:
            inner 表示饰品提取，outer 表示侵蚀隧洞。
        """
        return str(self.config["module"])

    def _support_on(self):
        """返回当前运行模式是否开启支援。

        Returns:
            True 表示需要替换支援角色。
        """
        return bool(self.config[f"{self._module()}_support"])

    def _planned_runs(self, stamina_box):
        """按配置的次数或当前开拓力算出本张挑战要刷的轮数。

        Args:
            stamina_box: 开拓力数字的识别区域 [左, 上, 右, 下]，仅自动推算时读取。

        Returns:
            本张挑战的轮数；开拓力不足一次挑战时返回 0。
        """
        module = self._module()
        if not self.config[f"{module}_auto"]:
            return int(self.config[f"{module}_runs"])
        # 开拓力写作「当前值/上限」；识别框已经避开旁边的备用开拓力，这里直接取斜杠前的当前值。
        raw = self.ts.ocr_one_row(self.screen, stamina_box) or ""
        match = re.search(r"(\d+)\s*/", raw)
        stamina = int(match.group(1)) if match else None
        # 每次挑战固定消耗 40 点开拓力，能刷的次数就是「当前值 // 40」。
        planned = 0 if stamina is None else stamina // 40
        CUS_LOGGER.debug("开拓力识别：%r → 当前 %s，本次计划刷 %s 次", raw, stamina, planned)
        return planned

    def _read_number(self, box, pattern=r"(\d+)"):
        """返回识别区域内的第一个数字。

        Args:
            box: 识别区域 [左, 上, 右, 下]。
            pattern: 取数字的正则；开拓力只取斜杠前的当前值。

        Returns:
            识别到的整数；没有数字时返回 None。
        """
        match = re.search(pattern, self.ts.ocr_one_row(self.screen, box) or "")
        return int(match.group(1)) if match else None

    def _settled(self, box, texts):
        """同一识别区域连续两轮识别到相同内容，说明列表已经停止滚动。

        Args:
            box: 识别区域 [左, 上, 右, 下]。
            texts: 本帧该区域识别到的文字。

        Returns:
            True 表示这一帧的坐标可以直接拿去点击。
        """
        key = tuple(box)
        signature = "".join(texts)
        previous = self.list_texts.get(key)
        self.list_texts[key] = signature
        return previous == signature

    def _scroll_once(self, box, point, ticks, texts, message):
        """列表静止时才滚一屏；连续多帧静止仍没命中说明已经滚到底。

        每次滚动后列表要过一会儿才落定，落定前那一帧的识别结果不可信——
        所以只在"这一帧和上一帧内容完全一致"时才滚，避免刚滚过就把还看得见的目标翻走。

        Args:
            box: 判断内容是否变化的识别区域 [左, 上, 右, 下]。
            point: 滚动时鼠标悬停位置 (x, y)，沿用旧版实测位置。
            ticks: 滚动格数，正数向上、负数向下。
            texts: 本帧该区域识别到的文字，按识别顺序拼接后作为页面标识。
            message: 已经滚到底仍不满足条件时抛出的说明。

        Raises:
            RuntimeError: 该区域连续多帧没有变化，滚动不再生效。
        """
        key = tuple(box)
        if not self._settled(box, texts):
            # 内容还在变化：刚滚过或仍在滚动，这一轮只观察不动作。
            self.list_misses[key] = 0
            return
        still = self.list_misses.get(key, 0) + 1
        self.list_misses[key] = still
        if still >= 3:
            raise RuntimeError(message)
        key_mouse_manager.scroll_point(*point, ticks)
        # 滚轮是入队执行的：等这一下真正滚完，下一轮截到的画面才是滚过之后的画面；
        # 否则会拿着滚动前的那一帧去算落点，点到的就是滚上来的别的行。
        key_mouse_manager.wait()

    def _enemy_distance(self):
        """返回小地图红点距小地图中心的最小像素距离。

        Returns:
            距离（像素）；小地图上没有红点时返回 None。
        """
        local = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
        # 红点颜色为 (47, 47, 232)，容差 5000 用于吸收渲染差异。
        mask = np.sum((local - np.array((47, 47, 232))) ** 2, axis=-1) <= 5000
        rows, cols = np.where(mask)
        if not len(rows):
            return None
        distances = np.sqrt((cols - MINIMAP_RADIUS) ** 2 + (rows - MINIMAP_RADIUS) ** 2)
        return float(distances.min())


def create_engine(*, script=False):
    """按注册表约定创建内核实例。

    Args:
        script: 由注册表传入的运行形态标记；本内核只按 JSON 脚本运行，不使用该标记。

    Returns:
        已加载模块配置的日常内核。
    """
    return DailyKernel()
