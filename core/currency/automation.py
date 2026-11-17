import os
import re
import time

import cv2
import numpy as np
import pyautogui

from core.currency.affixes import AFFIX_NAMES
from core.currency.affix_stats import AffixSampler
from core.currency.envirs import ENVIR_NAMES
from core.currency.textmatch import best_match, similar
from core.currency.investment_selection import choose_fallback_investment
from core.currency.strategies import exit_plane_for, match_name
from core.currency.strategy_stats import StrategySampler
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
from core.currency.settings import (
    load_currency_settings,
    resolve_priority,
    save_currency_settings,
)
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
            # 切分点贴边会切出空数组，后面 OCR 一裁片就 cv2 断言崩掉
            if left < 6 or right > mask.shape[1] - 6:
                continue
            return patch[:, :left], patch[:, right:]
    return None


def read_count_number(recognizer, patch):
    """识别人数裁片一侧的数字；识别结果不是一个数字时返回 None。"""
    if patch is None or not getattr(patch, "size", 0):
        return None
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
    GOLDEN_ERA_NAMES = ("银•金•彩",)
    # 本工具自己的窗口里才会出现的文字：出现就说明画面被盖住了
    CONTAMINATION_MARKERS = ("运行输出", "中控台", "模拟权杖", "DeepSeek Harness")

    DIFFICULTY_MAX_STEPS = 120
    # 4.7 实测：这个框要比文字行宽一点，框太窄 OCR 会把「获得」认成「医得」
    DIFFICULTY_SELECTED_EFFECT_BOX = [660, 380, 1250, 450]
    DIFFICULTY_ENTER_BOX = [1550, 930, 1800, 1000]
    DIFFICULTY_DOWN_POSITION = (960, 844)
    DIFFICULTY_START_POSITION = (1692, 965)     # 难度页右下角的「开始对局」
    DIFFICULTY_START_ATTEMPTS = 3               # 点了没离开难度页时的重试次数
    DIFFICULTY_LEAVE_TIMEOUT = 1.2              # 每次点击后等界面切换的时间
    DIFFICULTY_LEAVE_STEP = 0.2
    DIFFICULTY_SETTLE_TIMEOUT = 0.8    # 点完向下后，轮询等难度描述变一次
    DIFFICULTY_SETTLE_STEP = 0.05
    ENVIRONMENT_TITLE_BOX = [897, 80, 1018, 114]
    ENVIRONMENT_CONFIRM_BOX = [1053, 967, 1108, 998]
    # 上阵人数裁片：避开左侧人物图标，右侧留出两位数上限的宽度。
    TEAM_COUNT_BOX = [884, 202, 1150, 280]
    BLESS_REFRESH_POSITIONS = ((384, 869), (868, 869), (1380, 869))
    # 右下角「进入标准博弈 / 进入超频博弈」按钮：两种博弈是同一个位置
    MODE_ENTER_POSITION = (1637, 960)
    # 该按钮的文字框（日志里带上落点来源，便于核对）
    # 右下角按钮：入口页是「开始「货币战争」」，模式页是「进入超频/标准博弈」
    BATTLE_MODE_BUTTON_BOX = [1400, 925, 1900, 1005]
    # 人数不足提示框的「确认」按钮：实测文字 [1160,656,1215,686]，取中心直接点
    BATTLE_FEWER_CONFIRM_POSITION = (1187, 671)
    # 游戏自己弹出的「前台区域无角色」提示：它在的时候格子被盖住，空位识别不可信
    FRONT_EMPTY_WARNING_BOX = [816, 512, 1104, 539]
    FRONT_EMPTY_DISMISS = (978, 671)
    # 选主角面板：顶部标题与底部红条。商店盖住标题时只剩红条 —— 这就是重叠 bug 的签名
    PROTAGONIST_TITLE_BOX = [700, 55, 1230, 120]
    PROTAGONIST_BANNER_BOX = [740, 775, 1180, 830]
    BROKEN_PANEL_ESC_GAP = 1.2
    # 「开拓商店」：标题在两张版式里都有；点击目标是那张「星穹列车，跃迁！」卡片
    PIONEER_TITLE_BOX = [890, 50, 1180, 105]
    PIONEER_CARD_POSITION = (1045, 275)     # 「星穹列车，跃迁！」卡片中心
    PIONEER_STEP_GAP = 0.9
    # 物品详情面板左上角的「消耗品」标签（实测约 [849,318,900,337]）
    ITEM_DETAIL_LABEL_BOX = [800, 300, 980, 355]
    # 左上角「超频博弈」标签页；标准博弈不需要切标签，直接点上面的按钮
    # 「从师」面板：卡片数量会变（3~4 张），卡片整体居中，所以固定坐标会飘。
    # 改成用卡名那一行当锚点：取最左边的名字，点它上方 90px（= 卡身）。
    MASTER_NAME_BAND = [560, 320, 1700, 385]
    MASTER_CARD_LIFT = 90
    MASTER_CARD_POSITION = (625, 240)   # 卡名都没认出来时的兜底
    MASTER_CONFIRM_BOX = [1400, 505, 1580, 570]

    # 4.7 的模式选择界面：左侧上下两张卡（标准 / 超频），右侧大标题显示当前选中的模式
    MODE_TITLE_BOX = [560, 125, 780, 185]
    MODE_CARD_POSITIONS = {"standard": (155, 226), "overclock": (155, 418)}
    # 只有低难度才会出现的「返回最高职级」；没它说明已经在 A8-20
    TOP_RANK_BUTTON_BOX = [1325, 952, 1457, 979]
    # 词缀界面：标题、左下词缀条、右下「下一步」
    AFFIX_TITLE_BOX = [485, 185, 679, 217]
    AFFIX_STRIP_BOX = [300, 938, 1160, 1020]
    AFFIX_NEXT_POSITION = (1397, 981)
    # 「点击空白处继续」：初始/首领/奇遇三处提示的 y 分别在 948~975 / 778~807 / 689~718，
    # 一条宽条带全罩住；点的时候点识别到的那块文字本身，不靠固定坐标猜
    BLANK_PROMPT_TEXT = "点击空白处继续"
    BLANK_PROMPT_BOX = [800, 640, 1140, 1010]
    # 界面刚切进来时常见「只渲染出一部分」：词缀条/环境卡片都要轮询等它出字，
    # 拿半帧结果去点下一步或点刷新会漏采、甚至会洗掉必选环境
    # A8-20 固定给四条词缀，而且是从左往右依次刷出来的：认到一条就跑会漏后面的
    AFFIX_EXPECTED = 4
    AFFIX_READ_ATTEMPTS = 10
    AFFIX_READ_INTERVAL = 0.3
    # 认不满四条时，最多再等这么多轮（每轮一次触发）才按现有结果继续
    AFFIX_PARTIAL_RETRY_ROUNDS = 3
    # 采集模式下，1-1 奖励屏会比奇遇界面先出来：就地轮询等它加载（12×0.5s ≈ 6 秒）。
    # 等不到就直接退出——奇遇那屏没有我们要的数据，真晚到了也会被「点击空白继续」接住
    CURIOSITY_WAIT_ATTEMPTS = 12
    CURIOSITY_WAIT_INTERVAL = 0.5
    ENVIR_WAIT_ATTEMPTS = 8
    ENVIR_WAIT_INTERVAL = 0.3
    ENVIR_MIN_FILLED = 3

    def __init__ (self, debug):
        super ().__init__ ()
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
        # 4.7 起策略不再按"每面固定一次"来数：记录每面实际出现过几次策略选择
        self.current_plane = None
        self.plane_strategy_count = {}
        # 退出失败重试计数（连续失败到上限就停手）
        self.exit_attempts = 0

        priority = load_currency_settings()["priority"]

        self.prior_envir = priority["prior_envir"][:]
        self.envir = [[] for _ in range(4)]
        # 采集模式用：这一轮下来已经刷到过的投资环境（跨局累计，用来判断目标是否收齐）
        self.envir_seen = set()
        # 本局是否已经选完投资环境（采集模式用它区分「词缀后的空白」和「奇遇的空白」）
        self.envir_selected = False
        # 本局词缀没认满四条的重试次数
        self.affix_incomplete_rounds = 0
        # 本局词缀是否已经记录过（词缀一局只出现一次）
        self.affixes_recorded = False

        for index in range(1, 5):
            self.envir[index - 1] = priority[f"envir_{index}"][:]

        self.ENVIR_BOXES = [[266, 375, 610, 413], [780, 375, 1134, 414], [1314, 373, 1645, 413]]
        self.BLESS_BOXES = [[298, 472, 608, 513], [783, 472, 1095, 513], [1298, 472, 1605, 513]]

        if debug != 2:
            # 似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False

        CUS_LOGGER.debug (f"开始运行,初始计数：{self.count}")

        # 首次运行时用默认配置补全游戏与脚本设置。
        load_settings()

        self.preparation = BattlePreparation()
        currency_settings = load_currency_settings()  # 模板去重可能已迁移角色优先级。
        self.front_priority, self.back_priority = resolve_priority(
            currency_settings["deployment"]
        )

        # 策略采样与「目标/负面策略」配置
        self.strategy_sampler = StrategySampler()
        self.strategy_targets = currency_settings["strategy_targets"]
        self.strategy_avoid = currency_settings["strategy_avoid"]
        self.auto_exit_plane = currency_settings["auto_exit_plane"]
        self.auto_clear_targets = currency_settings["auto_clear_targets"]
        # 配了目标策略就是在收集策略：这种跑法不该被"等词缀"卡住（低难度本来就没词缀）
        self.collecting_strategies = bool(self.strategy_targets)
        if self.strategy_targets:
            CUS_LOGGER.info("目标投资策略：%s", "、".join(self.strategy_targets))
        if self.strategy_avoid:
            CUS_LOGGER.info("负面投资策略（绝不选）：%s", "、".join(self.strategy_avoid))
        if self.auto_exit_plane:
            CUS_LOGGER.info("退出位面：按目标策略自动推算")
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

        # 新模式相关配置：对局类型（标准/超频）、难度选择方式、开局词缀收集
        self.gamemode = currency_settings["gamemode"]
        self.difficulty_mode = currency_settings["difficulty_mode"]
        self.gather_mode = currency_settings["gather_mode"]
        self.max_runs = currency_settings["max_runs"]
        self.affix_targets = currency_settings["affix_targets"]
        self.affix_sampler = AffixSampler()
        CUS_LOGGER.info(
            "对局类型: %s，难度选择: %s%s",
            "标准博弈" if self.gamemode == "standard" else "超频博弈",
            "最高职级(A8-20)" if self.difficulty_mode == "top" else "最低难度",
            "，已开启开局词缀收集模式" if self.gather_mode else "",
        )
        if self.affix_targets:
            CUS_LOGGER.info("目标词缀: %s", "、".join(self.affix_targets))

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

    @staticmethod
    def canonical_environments (texts):
        """把 OCR 结果对齐到已知的 72 条环境名。

        OCR 会把「银•金•彩」的间隔点吃掉、偶尔认错形近字；先用已知名字表纠回来，
        后面的优先级匹配、蓝海/银金彩判定都只看规范名。
        """
        return [best_match(text, ENVIR_NAMES) or text for text in texts]

    def wait_environments (self):
        """等三张投资环境卡片渲染出来再判断。

        刚切进界面时常见只出来第一张（日志里就是 `['二手市场', '', '']`），
        这时判"没刷到必选环境"会立刻点刷新，直接把必选环境洗掉。
        """
        texts = []
        for attempt in range(self.ENVIR_WAIT_ATTEMPTS):
            self.get_screen()
            texts = self.canonical_environments(self.recognize_options(self.ENVIR_BOXES))
            filled = sum(1 for text in texts if text.strip())
            if filled >= self.ENVIR_MIN_FILLED:
                if attempt:
                    CUS_LOGGER.debug("投资环境卡片已渲染（第 %d 次识别）", attempt + 1)
                return texts
            CUS_LOGGER.debug(
                "投资环境只认出 %d 张卡（第 %d/%d 次识别），等渲染",
                filled, attempt + 1, self.ENVIR_WAIT_ATTEMPTS,
            )
            time.sleep(self.ENVIR_WAIT_INTERVAL)
        CUS_LOGGER.warning(
            "投资环境只认出 %d 张卡，仍按当前结果继续",
            sum(1 for text in texts if text.strip()),
        )
        return texts

    def route (self):
        if self.background_mode:
            # 后台模式：不抢前台，直接进主循环（loop() 自身就是 while，窗口消失由 loop 内处理）
            CUS_LOGGER.info("后台模式：不抢前台，直接开始识别")
            self.loop()
            CUS_LOGGER.info("已停止任务")
            return

        set_forground ()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text ()
            warn_game = False
            cnt = 0
            focus_reclaim_wait = max(1, 2*load_settings().get("game_focus_reclaim_wait_seconds", 600))
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                if self._stop:
                    raise NormalEndError
                if not warn_game:
                    warn_game = True
                    CUS_LOGGER.warning (f"等待游戏窗口，当前窗口：{Text}")
                time.sleep(0.5)
                cnt += 1
                if cnt == focus_reclaim_wait:
                    set_forground () # 将游戏窗口设为前台
                hwnd,Text = get_hwnd_and_text ()
            if self._stop:
                break
            self.loop ()
        CUS_LOGGER.info ("已停止任务")

    def screen_contaminated (self):
        """这一帧是不是把本工具自己的窗口也截进来了。

        截图是抓屏幕像素的：只要控制台窗口盖在游戏画面上，抓到的就是控制台。
        识别到控制台里的文字时，任何点击都不可信，必须跳过。
        """
        try:
            texts = " ".join(item["raw_text"] for item in self.ts.res)
        except Exception:
            return False
        return any(marker in texts for marker in self.CONTAMINATION_MARKERS)

    def game_is_foreground (self):
        """游戏窗口是不是前台窗口。不是的话截到的是桌面/别的程序，识别全是乱的。"""
        try:
            import win32gui

            return bool(self.hwnd) and win32gui.GetForegroundWindow() == self.hwnd
        except Exception:
            return True   # 判断不了就别挡着跑

    def loop (self):
        CUS_LOGGER.info ("开始OCR识别，等待触发文字")
        silent_time = time.time ()
        shot_saved = False
        while not self._stop:
            # 游戏被切到后台时，截图抓到的是桌面或别的窗口，动作会点到乱七八糟的地方。
            # 后台模式是另一套链路（窗口捕获），这里不能抢前台
            if not getattr(self, "background_mode", False) and not self.game_is_foreground():
                CUS_LOGGER.warning("游戏窗口不在前台，先把切回来再继续（不执行任何动作）")
                set_forground()
                time.sleep(1)
                continue

            self.ts.forward (self.get_screen())
            if self.screen_contaminated():
                CUS_LOGGER.warning(
                    "画面里混进了控制台窗口的内容，多半是窗口盖住了游戏；这一帧不执行任何动作"
                )
                time.sleep(0.5)
                continue
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

    def wait_difficulty_settled (self, timeout=None, step=None):
        """点完向下箭头后，等难度描述文字发生变化（最多等 DIFFICULTY_SETTLE_TIMEOUT）。

        列表滚动是动画，点完立刻回头看会读到上一帧，容易多按几下。
        """
        timeout = self.DIFFICULTY_SETTLE_TIMEOUT if timeout is None else timeout
        step = self.DIFFICULTY_SETTLE_STEP if step is None else step
        self.get_screen()
        before = self.read_difficulty_text()
        deadline = time.monotonic() + timeout
        for _ in range(int(timeout / step) + 1):
            time.sleep(step)
            self.get_screen()
            current = self.read_difficulty_text()
            if current and current != before:
                return current
        return before

    def on_difficulty_screen (self):
        """现在还在不在难度界面：右下角应该能看到「开始对局」。"""
        return bool(self.click_text(
            text="开始对局", box=self.DIFFICULTY_ENTER_BOX, click=False, allow_fail=True))

    def read_difficulty_text (self):
        """读难度 1 的效果描述行（读不到返回空串）。"""
        try:
            return merge_text(self.ts.find_with_box(
                self.DIFFICULTY_SELECTED_EFFECT_BOX, forward=1))
        except Exception:
            return ""

    def is_one (self):
        try:
            text_list = self.ts.find_with_box(
                self.DIFFICULTY_SELECTED_EFFECT_BOX,
                forward=1,
            )
            merged = merge_text (text_list)
            CUS_LOGGER.debug(f"OCR 识别结果: {merged}")
            # 只认「开局时」：难度 1 的效果行开头就是它，OCR 后面的字容易错（获得→医得），
            # 掐头两个字足够判别，又不至于把「敌人难度+1」那行误判成难度 1
            return "开局时" in merged
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
            if not self.on_difficulty_screen():
                # 点完「开始对局」会先进黑屏，状态却还是 difficulty_select；
                # 这时候再连点只会往空处点，直接收手
                CUS_LOGGER.info("难度界面已消失（对局已开始或界面已切换），停止选择难度")
                return True
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
            # 难度列表滚动有动画：轮询等描述文字变一次再判断，别拿动画中间帧当结果
            self.wait_difficulty_settled()

        CUS_LOGGER.warning("达到向下选择上限，仍未识别到难度1；停止点击并等待下一轮识别")
        return False

    def read_mode_button (self):
        """读右下角按钮的文字（入口页「开始「货币战争」」/ 模式页「进入XX博弈」/ 难度页「开始对局」）。"""
        try:
            return merge_text(self.ts.find_with_box(
                self.BATTLE_MODE_BUTTON_BOX, redundancy=30))
        except Exception:
            return ""

    def enter_battle_mode (self):
        """进入对局：入口页 → 模式选择 → 难度界面，逐层判断。

        OCR 对这几个按钮很不稳（实测把「超频博弈」读成「超预博到」「超频博弃」），
        所以不整串匹配，只认关键单字：「货币战争」走入口、「开始」走难度、
        模式页则看有没有「超」/「标」来判断当前选中哪个模式。
        """
        want_overclock = self.gamemode != "standard"
        want_char = "超" if want_overclock else "标"
        card = self.MODE_CARD_POSITIONS["overclock" if want_overclock else "standard"]

        for attempt in range(3):
            text = self.read_mode_button()
            CUS_LOGGER.debug("右下角按钮：%r", text)

            if "货币战争" in text:
                CUS_LOGGER.info("已点击「进入货币战争」")
                key_mouse_manager.click_point(*self.MODE_ENTER_POSITION,
                                              box=self.BATTLE_MODE_BUTTON_BOX)
                key_mouse_manager.wait()
                return 1

            if "开始" in text:
                # 「开始对局」——已经在难度界面
                CUS_LOGGER.debug("已在难度界面，跳过模式切换")
                self.update_state("difficulty_select")
                return 1

            if "博" in text:
                # 只要出现「博」就说明在模式页（OCR 会把「博弈」读成「博到/博弃/博奔」），
                # 这时才敢点左侧模式卡；入口页和难度页都不会有这个字
                if want_char in text:
                    CUS_LOGGER.info("已选中「%s」", "超频博弈" if want_overclock else "标准博弈")
                    key_mouse_manager.click_point(*self.MODE_ENTER_POSITION,
                                                  box=self.BATTLE_MODE_BUTTON_BOX)
                    key_mouse_manager.wait()
                    self.update_state("difficulty_select")
                    return 1
                CUS_LOGGER.info("切换到「%s」（第 %d 次）",
                                "超频博弈" if want_overclock else "标准博弈", attempt + 1)
                key_mouse_manager.click_point(*card)
                key_mouse_manager.wait()
                continue

            # 按钮文字没读到或不是这几种：宁可什么都不点，也别把点打到攻略/图例上
            CUS_LOGGER.warning("认不出右下角按钮（%r），本轮不点击任何位置", text)
            return 0

        CUS_LOGGER.warning("三次都没切到目标模式，先不动，等下一轮")
        return 0

    def select_top_difficulty (self):
        """最高职级（A8-20）：有「返回最高职级」就点它切过去，没有说明已经是。"""
        box = self.TOP_RANK_BUTTON_BOX
        if self.click_text(text="返回最高职级", box=box, click=False, allow_fail=True):
            CUS_LOGGER.info("当前不是 A8-20，点击「返回最高职级」切换难度")
            key_mouse_manager.click_point(
                (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, box=box)
            key_mouse_manager.wait()
            self.get_screen()
        else:
            CUS_LOGGER.info("未出现「返回最高职级」，判定当前已是 A8-20")
        return self.complete_difficulty_selection()

    def handle_difficulty_selection(self):
        if self.state not in (None, "difficulty_select"):
            # 这个动作是靠「开始对局」触发的，能走到这儿说明人就在难度界面，
            # 状态没跟上（比如刚点完进入按钮）就直接纠正，别空转
            CUS_LOGGER.info("难度界面已出现，状态从 %s 纠正为 difficulty_select", self.state)

        self.update_state("difficulty_select")
        self.get_screen()

        if self.difficulty_mode == "top":
            return self.select_top_difficulty()

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
        # 点「开始对局」后确认真的离开了难度页：后台模式下点击偶尔会被丢掉，
        # 不确认的话就会每 2 秒原地重点一次，日志里只看到同一句"直接开始对局"。
        for attempt in range(1, self.DIFFICULTY_START_ATTEMPTS + 1):
            key_mouse_manager.click_point(*self.DIFFICULTY_START_POSITION, force=True)
            key_mouse_manager.wait()
            if not self.still_on_difficulty_screen():
                break
            if attempt < self.DIFFICULTY_START_ATTEMPTS:
                CUS_LOGGER.warning("第 %d 次点「开始对局」没反应，重试", attempt)
        else:
            # 后台消息整片失效时的最后手段：真实输入。会短暂把游戏切到前台，
            # 默认关闭（看网课时闪窗口太打扰），需要时在设置里打开。
            if getattr(self, "allow_foreground_fallback", False):
                CUS_LOGGER.warning(
                    "点了 %d 次「开始对局」都没离开难度页，改用前台兜底点击",
                    self.DIFFICULTY_START_ATTEMPTS)
                key_mouse_manager.click_point_foreground(*self.DIFFICULTY_START_POSITION)
                if self.still_on_difficulty_screen():
                    CUS_LOGGER.warning("前台兜底点击也没离开难度页，等下一轮")
            else:
                CUS_LOGGER.warning(
                    "点了 %d 次「开始对局」都没离开难度页，等下一轮"
                    "（如需自动切前台，请开启 background_allow_foreground_fallback）",
                    self.DIFFICULTY_START_ATTEMPTS)
            return True
        self.reset_run_state()
        CUS_LOGGER.info("货币战争对局计时开始")
        return True

    def still_on_difficulty_screen (self, timeout=None, step=None):
        """轮询确认还在不在难度页：按钮文字「开始对局」消失即视为已进入对局。"""
        timeout = self.DIFFICULTY_LEAVE_TIMEOUT if timeout is None else timeout
        step = self.DIFFICULTY_LEAVE_STEP if step is None else step
        deadline = time.monotonic() + timeout
        while True:
            self.get_screen()
            if not self.click_text(text="开始对局", box=self.DIFFICULTY_ENTER_BOX,
                                   click=False, allow_fail=True):
                return False
            if time.monotonic() >= deadline:
                return True
            time.sleep(step)

    def reset_run_state (self):
        """每局开局的复位。放在「投资环境选择完成」也调用一次：

        难度那一步有可能被跳过（比如「开始对局」文字没认出来就提前返回），
        那样 exit_requested 会带着上一局的 True 进来，prepare_battle 直接静默返回，
        整局都在空转。
        """
        self.exit_plane = self.set_exit_plane
        self.prior_environment_found = False
        self.exit_requested = False
        self.exit_started = False
        # 4.7 起策略不再按"每面固定一次"来数：记录每面实际出现过几次策略选择
        self.current_plane = None
        self.plane_strategy_count = {}
        # 退出失败重试计数（连续失败到上限就停手）
        self.exit_attempts = 0
        self.envir_selected = False
        self.affix_incomplete_rounds = 0
        self.affixes_recorded = False
        self.protagonist_picks = 0
        self.protagonist_drag_failures = 0
        self.battle_click_attempts = 0
        # 刷新额度按对局计：上一局无论刷没刷出必选，本局都要重新给一次。
        self.has_fresh = False
        self.run_history.start_run()

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
        texts = self.wait_environments ()
        CUS_LOGGER.info (f"OCR 识别结果: {texts}")
        self.envir_seen.update(text for text in texts if text)

        if sum(1 for text in texts if text.strip()) == 1:
            # 环境只会出现三种卡或一张卡（蓝海的额外环境），没有两张的情况：
            # 一张卡就按额外环境处理，不要拿半帧结果去点刷新
            CUS_LOGGER.info("投资环境只出现一张卡（蓝海的额外环境），直接选它")
            if self._select_blue_ocean_extra_environment():
                self.investment_tracker.reset()
                self.envir_selected = True
                self.update_state("1-1")
                CUS_LOGGER.info("投资环境选择完成")
                self.stop_if_gather_goal_reached()
                return 1
            CUS_LOGGER.warning("单卡投资环境处理失败，等下一轮")
            return 0
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
        self.envir_selected = True
        self.update_state("1-1")
        CUS_LOGGER.info ("投资环境选择完成")
        self.stop_if_gather_goal_reached()
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

        if any(best_match(text, self.GOLDEN_ERA_NAMES) for text in texts):
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
            texts = self.canonical_environments(self.recognize_options(self.ENVIR_BOXES))
            self.envir_seen.update(text for text in texts if text)
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

    def select_strategy (self):
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
            texts = self.canonical_strategies (self.recognize_options (boxes))
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

            pick, reason = self._pick_strategy(texts, icon_presence)
            if pick is not None and reason != "fallback":
                selected_idx = pick
                CUS_LOGGER.info(f"第{attempt}次命中「{reason}」，选中选项{pick+1}")
                break

            if attempt < self.max_refresh:
                CUS_LOGGER.info(f"第 {attempt+1} 次没命中目标/未解锁，点击刷新")
                self._refresh_investment_options(texts)
            else:
                selected_idx = (
                    pick if pick is not None
                    else choose_fallback_investment(texts, icon_presence)
                )
                CUS_LOGGER.warning(f"刷新后仍未命中，按兜底选选项{selected_idx+1}")

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

        # 4.7 起策略可能在同一面出现多次、也可能一次都不出现，
        # 所以这里只记账；退不退出交给备战界面的位面判定（_maybe_exit_by_stage）
        plane = self.current_plane if self.current_plane is not None else 0
        self.plane_strategy_count[plane] = self.plane_strategy_count.get(plane, 0) + 1
        CUS_LOGGER.info(
            "第 %s 面已选过 %d 次策略", plane, self.plane_strategy_count[plane])

        hits = self.strategy_sampler.record(
            plane, texts, selected_text, targets=self.strategy_targets)
        if hits:
            CUS_LOGGER.info("本屏命中目标策略：%s", "、".join(hits))
            self.auto_clear_target(selected_text)
        self._refresh_auto_exit_plane()

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
        if patch is None or not patch.size:
            CUS_LOGGER.debug("人数裁片为空（窗口尺寸可能不对），等下一轮")
            return None
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

    def read_affixes (self):
        """识别左下词缀条上的词缀名。

        词缀长度不一，四条的框在画面上宽度不同，所以整条一起 OCR、按识别结果收集，
        不按固定四格切。这里用底层识别器取「未合并」的结果：`forward()` 会把同行
        相距很近的文字并成一条（实测把前两枚词缀粘成「侵蚀·第一位面强化战个痛快」）。
        """
        box = self.AFFIX_STRIP_BOX
        patch = self.screen[box[1]:box[3], box[0]:box[2]]
        texts = []
        try:
            for _rect, (raw_text, score) in self.ts.ts.ocr(patch):
                text = re.sub(r"\s+", "", raw_text)
                if not text or score < 0.6 or text.isdigit():
                    continue
                if "敌人难度" in text or self.BLANK_PROMPT_TEXT in text:
                    continue
                # 对齐到 53 条已知词缀：OCR 常把首字吃掉或多认一笔（实测「山榜样激励」「首强化」），
                # 不纠回来的话采样统计会被这些碎片条目污染
                canonical = best_match(text, AFFIX_NAMES)
                if canonical is None:
                    CUS_LOGGER.debug("词缀条读到对不上的文字，丢弃：%s", text)
                    continue
                if canonical not in texts:
                    texts.append(canonical)
        except Exception:
            CUS_LOGGER.warning("词缀条 OCR 失败", exc_info=True)
        return texts

    def gather_goal_reached (self):
        """采集模式下，目标词缀与必选环境是否都刷到了。

        两边都没配置时不算达成（否则开局就停）。词缀看采样计数器，环境看跨局累计的
        `envir_seen`；都用形近字匹配，OCR 错一个字不至于漏判。
        """
        if not getattr(self, "gather_mode", False):
            return False
        if not self.affix_targets and not self.prior_envir:
            return False
        affixes_done = all(
            any(similar(target, seen) for seen in self.affix_sampler.counter)
            for target in self.affix_targets
        )
        envir_done = all(
            any(similar(prior, seen) for seen in self.envir_seen)
            for prior in self.prior_envir
        )
        return affixes_done and envir_done

    def stop_if_gather_goal_reached (self):
        """目标全部刷到就停下，别让它一直空转。返回是否已停止。"""
        if not self.gather_goal_reached():
            return False
        CUS_LOGGER.info(
            "采集目标已全部刷到（目标词缀 %d 条 / 必选环境 %d 条，共 %d 把），停止运行；"
            "游戏会停在当前界面，需要的话手动退出这一局",
            len(self.affix_targets), len(self.prior_envir), self.affix_sampler.run_index,
        )
        self._stop = True
        return True

    def wait_affixes (self):
        """轮询等词缀条刷满 AFFIX_EXPECTED 条。

        词缀是一条一条从左往右显出来的，认到一条就点下一步会漏采后面的；
        等满四条（或等够次数）再返回。
        """
        affixes = []
        for attempt in range(self.AFFIX_READ_ATTEMPTS):
            self.get_screen()
            affixes = self.read_affixes()
            if len(affixes) >= self.AFFIX_EXPECTED:
                return affixes
            CUS_LOGGER.debug(
                "词缀条现有 %d/%d 条（第 %d/%d 次识别）：%s",
                len(affixes), self.AFFIX_EXPECTED,
                attempt + 1, self.AFFIX_READ_ATTEMPTS,
                "、".join(affixes) if affixes else "（空）",
            )
            time.sleep(self.AFFIX_READ_INTERVAL)
        return affixes

    def read_affixes_and_continue (self):
        """词缀界面：读词缀 → 采样落盘 → 点右下角「下一步」。

        词缀一局只出现一次，点完下一步就没了；但切界面那一两帧文字可能还挂着，
        不挡住的话会对同一局重复识别（还会把下一屏的「点击空白处继续」当成词缀）。
        """
        if self.affixes_recorded:
            CUS_LOGGER.debug("本局词缀已记录，跳过重复识别")
            return 1

        # 只有开了词缀收集（或配了目标词缀）才值得花时间读词缀；否则直接点下一步，
        # 在低难度刷策略时这一步会白等十几秒
        if not getattr(self, "gather_mode", False):
            # 不置「已记录」：这一下没点掉时下一帧要能接着点，
            # 置了标记就会永远跳过，卡在这个界面
            CUS_LOGGER.debug("未开启词缀收集模式，跳过词缀识别直接点下一步")
            key_mouse_manager.click_point(*self.AFFIX_NEXT_POSITION)
            key_mouse_manager.wait()
            return 1

        affixes = self.wait_affixes()
        if not affixes:
            if getattr(self, "collecting_strategies", False):
                # 低难度局根本没有词缀，收集策略时不该在这儿卡住
                CUS_LOGGER.info("本局没有词缀（低难度/未开词缀），策略收集中，直接点下一步")
                self.affixes_recorded = True
                key_mouse_manager.click_point(*self.AFFIX_NEXT_POSITION)
                key_mouse_manager.wait()
                return 1
            CUS_LOGGER.warning(
                "等了 %d 帧仍没识别到词缀，先不点下一步，等下一轮重试",
                self.AFFIX_READ_ATTEMPTS,
            )
            return 1
        if len(affixes) < self.AFFIX_EXPECTED:
            self.affix_incomplete_rounds += 1
            give_up = (
                getattr(self, "collecting_strategies", False)
                or self.affix_incomplete_rounds >= self.AFFIX_PARTIAL_RETRY_ROUNDS
            )
            if not give_up:
                CUS_LOGGER.warning(
                    "词缀只识别到 %d/%d 条（%s），再等一轮（第 %d 次重试）",
                    len(affixes), self.AFFIX_EXPECTED, "、".join(affixes),
                    self.affix_incomplete_rounds,
                )
                return 1
            CUS_LOGGER.warning(
                "词缀只识别到 %d/%d 条（%s），按现有条数继续",
                len(affixes), self.AFFIX_EXPECTED, "、".join(affixes),
            )
        CUS_LOGGER.info("本局词缀：%s", "、".join(affixes))
        self.affixes_recorded = True
        hits = self.affix_sampler.record(affixes, self.affix_targets)
        if hits:
            CUS_LOGGER.info("命中目标词缀：%s", "、".join(hits))
        if self.max_runs and self.affix_sampler.run_index >= self.max_runs:
            CUS_LOGGER.info("已达到设定的最大把数(%s)，停止采集", self.max_runs)
            self._stop = True
            return 1
        if self.stop_if_gather_goal_reached():
            return 1
        key_mouse_manager.click_point(*self.AFFIX_NEXT_POSITION)
        key_mouse_manager.wait()
        return 1

    def find_blank_prompt (self):
        """在当前帧找「点击空白处继续」，返回它的框；没有就返回 None。"""
        self.ts.forward(self.get_screen())
        for item in self.ts.find_with_box(self.BLANK_PROMPT_BOX):
            if self.BLANK_PROMPT_TEXT in item["raw_text"]:
                return item["box"]
        return None

    def click_blank_prompt (self):
        """点「点击空白处继续」：按识别到的文字位置点，不假设它在哪一屏。

        采集模式下，只有在**投资环境已经选完**之后点这一下才算本局采样结束——
        词缀界面之后就有一个空白提示，那一步还不能退。
        """
        target = self.find_blank_prompt()
        if target is None:
            CUS_LOGGER.debug("这一帧没找到「点击空白处继续」，等下一帧")
            return 1

        CUS_LOGGER.debug("点击空白提示：%s", target)
        self.click_box(target)
        key_mouse_manager.wait()
        if getattr(self, "gather_mode", False) and self.envir_selected:
            CUS_LOGGER.info("开局词缀收集模式：本局采样结束，请求退出并重开")
            self.exit_requested = True
            self.update_state("exit")
        return 1

    def prepare_battle(self):
        """先补满阵容，再按优先级替换，截图确认完成后才允许出战。

        每次只执行一个拖拽并重新采集，避免备战栏压缩后使用过期的格子坐标。
        返回 1 表示已准备好，0 表示仍需准备；识别和落位失败均不放行。
        """
        CUS_LOGGER.debug(
            "出战前准备：state=%s stop=%s exit_requested=%s 退出位面=%s",
            self.state, self._stop, self.exit_requested,
            getattr(self, "exit_plane", None))
        # 游戏在说「前台区域无角色」时，格子被提示框盖着，空位/人数识别都不可信，
        # 这时候判"阵容就位"会直接再点一次出战，死循环。先关掉提示，等真正的备战画面再补位。
        if self.click_text(text="前台区域无角色", box=self.FRONT_EMPTY_WARNING_BOX,
                           click=False, allow_fail=True):
            CUS_LOGGER.info("游戏提示前台无角色，先关掉提示，等备战画面再补位")
            key_mouse_manager.click_point(*self.FRONT_EMPTY_DISMISS)
            key_mouse_manager.wait()
            return 0
        if self._stop:
            CUS_LOGGER.debug("出战前准备：已停止，跳过")
            return 0
        if self.exit_requested and self.state != "exit":
            # 状态机没在退出流程里，标志却是 True：一定是上一局漏清的，别拿它卡住整局
            CUS_LOGGER.warning("退出标志与状态不符（state=%s），复位后继续", self.state)
            self.reset_run_state()
        if self.exit_requested:
            CUS_LOGGER.debug("出战前准备：已请求退出，跳过")
            return 0
        # 备战界面是唯一能稳定读到「位面-节点」的地方，退出判定放这儿：
        # 连续出现两屏策略时，一定是第二屏点完、回到备战界面才按 ESC
        if self._maybe_exit_by_stage():
            CUS_LOGGER.debug("出战前准备：位面判定要求退出，本轮不准备")
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
            CUS_LOGGER.debug(
                "备战识别：人数=%s，前台空位=%s，后台空位=%s，备战角色=%d，补位动作=%d",
                counts, vacancies["front"], vacancies["back"],
                len(sources), len(moves),
            )
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

    def confirm_battle_short_handed (self):
        """「可出战角色人数未达上限，是否确认出战？」的提示框——直接点确认。

        不先识别再点：后台模式下捕获帧会滞后，读不到「确认」并不代表按钮不在，
        结果就是日志里一直「没点掉确认」、提示框关不掉。
        触发这一动作的本来就是提示框上的「本局不再提示」文字，位置已知，直接点即可。

        也不去勾「本局不再提示」：勾选框是否已勾读不出来，点一次就是切换一次。
        """
        key_mouse_manager.click_point(*self.BATTLE_FEWER_CONFIRM_POSITION)
        key_mouse_manager.wait()
        CUS_LOGGER.info("已确认按现有人数出战")
        return 1

    def start_battle(self):
        """仅在可出战状态点击出战，等待输入完成后进入战斗状态。"""
        # 连续点了好几次还没进战斗，说明有东西挡着：把整屏文字打出来，免得到现场猜
        self.battle_click_attempts = getattr(self, "battle_click_attempts", 0) + 1
        if self.battle_click_attempts == 3:
            try:
                self.ts.forward(self.get_screen())
                texts = [item["raw_text"].strip() for item in self.ts.res]
                CUS_LOGGER.warning(
                    "连点 3 次出战都没进战斗，当前屏幕文字：%s", " ".join(t for t in texts if t)
                )
            except Exception:
                CUS_LOGGER.warning("连点 3 次出战都没进战斗，且整屏识别失败", exc_info=True)

        key_mouse_manager.click_point(1818, 750)
        key_mouse_manager.wait()
        self.update_state("startbattle")
        return 1

    def handle_1_1_reward(self):
        """处理1-1投资环境选择后的奖励界面。"""

        if getattr(self, "gather_mode", False):
            # 采集只要词缀和环境名额，绝不进战斗。
            # 奇遇界面要加载几秒才出来，这段时间**必须就地等**：只返回 0 的话主循环会继续
            # 匹配别的动作，「出战前准备」靠屏幕上的「出战」文字触发（不带状态门槛），
            # 一下就绕过等待把仗打起来了。
            CUS_LOGGER.info(
                "开局词缀收集模式：等奇遇界面加载（最多 %.0f 秒）后再退出",
                self.CURIOSITY_WAIT_ATTEMPTS * self.CURIOSITY_WAIT_INTERVAL,
            )
            target = None
            for attempt in range(self.CURIOSITY_WAIT_ATTEMPTS):
                if self._stop:      # 用户按了停止就别再傻等
                    return 0
                target = self.find_blank_prompt()
                if target is not None:
                    CUS_LOGGER.debug("点击空白提示：%s", target)
                    self.click_box(target)
                    key_mouse_manager.wait()
                    break
                CUS_LOGGER.debug(
                    "奇遇界面还没出来（第 %d/%d 次等待）",
                    attempt + 1, self.CURIOSITY_WAIT_ATTEMPTS,
                )
                time.sleep(self.CURIOSITY_WAIT_INTERVAL)
            else:
                CUS_LOGGER.warning("等奇遇界面超时，直接退出重开")

            self.exit_requested = True
            self.update_state("exit")
            return 1

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
            self.exit_attempts = 0
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
            self.exit_attempts = 0
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
                self.exit_attempts = 0
                return 1
            return self._exit_failed("战斗内没能进入放弃并结算页面")

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

        return self._exit_failed("按 ESC 后没能进入放弃并结算页面")

    def reset_battle_click_attempts (self):
        self.battle_click_attempts = 0

    def handle_battle_finished(self):
        self.battle_click_attempts = 0
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
        if self.sct is not None:
            self.sct.close()
            self.sct = None
        self.map_thread = None
    PROTAGONIST_BUTTON_BOX = [1755, 732, 1877, 768]
    # 贴着文字边界裁会读空，左右上下都留出余量
    PROTAGONIST_TITLE_BOX = [760, 58, 1160, 122]
    # 一局会过两次主角面板：第二次那个角色身上已经有光环，所以拖第二个角色
    PROTAGONIST_DRAG = ((805, 612), (960, 445))
    PROTAGONIST_SECOND_DRAG = ((910, 609), (964, 441))
    # 前台 2 号位可能是空的（角色都被分到后台），连试两次不成改从后台第一个拖
    PROTAGONIST_FALLBACK_DRAG = ((709, 750), (964, 441))
    PROTAGONIST_AURA_POSITION = (1501, 502)
    PROTAGONIST_CONFIRM_BOX = [941, 938, 995, 968]
    PROTAGONIST_WAIT_ATTEMPTS = 25
    PROTAGONIST_WAIT_INTERVAL = 0.4
    # 第二次选主角时该角色已有光环，点光环会弹「是否替换该角色原有光环？」（实测 OCR 框）
    # 框贴太紧 OCR 会整行读空（实测过），左右上下都留余量
    PROTAGONIST_REPLACE_TITLE_BOX = [760, 468, 1180, 548]
    PROTAGONIST_REPLACE_CONFIRM_POSITION = (1189, 671)

    def dismiss_item_detail (self):
        """关掉误触打开的物品详情面板（界面上只有「消耗品」说明框）。"""
        self.get_screen()
        CUS_LOGGER.info("检测到物品详情面板，按 ESC 退出")
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        return 1

    def close_pioneer_shop (self):
        """关掉「开拓商店」面板：先点「星穹列车，跃迁！」那张卡，再按 ESC 回备战。

        必须点卡片本体（不能只按 ESC，实测直接 ESC 关不掉）；
        也不能按文字中心点——文字在卡片下边缘，会点到空隙里。
        """
        self.get_screen()
        CUS_LOGGER.info("发现「开拓商店」面板，先点卡片再按 ESC")
        key_mouse_manager.click_point(*self.PIONEER_CARD_POSITION)
        key_mouse_manager.wait()
        time.sleep(self.PIONEER_STEP_GAP)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        CUS_LOGGER.info("已关闭「开拓商店」")
        return 1

    def recover_broken_protagonist_panel (self):
        """游戏偶发 bug：商店与「选择主角」界面叠在一起时，先 ESC 关商店再 ESC 重开。

        判定用「底部红条在、顶部标题不在」这组签名：正常的选主角面板两者都在，
        商店把标题盖住时只剩底下的「尚未选择主角角色和光环」。
        """
        self.get_screen()
        banner = self.click_text(text="尚未选择主角角色和光环",
                                 box=self.PROTAGONIST_BANNER_BOX,
                                 click=False, allow_fail=True)
        title = self.click_text(text="选择一个角色获得主角光环",
                                box=self.PROTAGONIST_TITLE_BOX,
                                click=False, allow_fail=True)
        if not banner or title:
            return 0

        CUS_LOGGER.warning(
            "检测到商店与选择主角界面重叠（游戏偶发 bug）：先按 ESC 关商店，再按 ESC 重开")
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        time.sleep(self.BROKEN_PANEL_ESC_GAP)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.exit_requested = True
        return 1

    def select_protagonist (self):
        """4.7 新 UI「选择主角」：点按钮 → 等面板 → 拖第一个角色 → 选右侧光环 → 确认。

        面板出现在第一位面和第二位面首领之前的备战界面，按钮就压在「出战」的位置上，
        不处理的话主循环等不到「出战」文字会一直空转。
        """
        # 主循环每帧都刷过截图，这里直接用当前帧（自己抓会依赖 _stop 等运行时状态）
        if self.click_text(text="选择一个角色获得主角光环",
                           box=self.PROTAGONIST_TITLE_BOX, click=False, allow_fail=True):
            # 刚选完的这几秒里不要再点开面板：面板标题那条动作会立刻把它重新打开，
            # 结果就是每次都白等一轮（日志里连着 25 次「面板还没出现」）
            if time.monotonic() - getattr(self, "protagonist_done_at", 0.0) < 3.0:
                CUS_LOGGER.debug("主角刚选完，跳过这次面板处理")
                return 1
            # 面板已经开着：可能是上一轮点的按钮生效了，也可能是上一轮拖拽没成功。
            # 累计失败次数，用来决定要不要换起点。
            self.protagonist_drag_failures = getattr(self, "protagonist_drag_failures", 0) + 1
            CUS_LOGGER.info(
                "选择主角面板已打开（连续第 %d 次处理），直接选角色",
                self.protagonist_drag_failures)
        else:
            box = self.PROTAGONIST_BUTTON_BOX
            key_mouse_manager.click_point(
                (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, box=box)
            key_mouse_manager.wait()

        for attempt in range(self.PROTAGONIST_WAIT_ATTEMPTS):
            if self.click_text(
                text="选择一个角色获得主角光环",
                box=self.PROTAGONIST_TITLE_BOX,
                click=False,
                allow_fail=True,
            ):
                break
            CUS_LOGGER.debug(
                "选择主角面板还没出现（第 %d/%d 次等待）",
                attempt + 1, self.PROTAGONIST_WAIT_ATTEMPTS,
            )
            time.sleep(self.PROTAGONIST_WAIT_INTERVAL)
        else:
            CUS_LOGGER.warning("选择主角面板没等到，交给下一轮重试")
            return 0

        # 起点选择：默认第一个角色；第二次改拖第二个；连试两次都没成说明那些位置是空的，
        # 改从后台第一个角色拖（前台 2 号位可能压根没站人）。
        failures = getattr(self, "protagonist_drag_failures", 0)
        if failures >= 2:
            start, end = self.PROTAGONIST_FALLBACK_DRAG
            CUS_LOGGER.info("选择主角：前两次没拖动，改从后台第一个角色拖（第 %d 次尝试）", failures + 1)
        elif getattr(self, "protagonist_picks", 0) >= 1:
            start, end = self.PROTAGONIST_SECOND_DRAG
            CUS_LOGGER.info("选择主角：拖第 2 个角色")
        else:
            start, end = self.PROTAGONIST_DRAG
            CUS_LOGGER.info("选择主角：拖第 1 个角色")
        key_mouse_manager.drag_point(start[0], start[1], end[0], end[1])
        key_mouse_manager.wait()

        # 选右侧的主角光环（不刷新，省金币）
        key_mouse_manager.click_point(*self.PROTAGONIST_AURA_POSITION)
        key_mouse_manager.wait()

        # 一局要过两次主角面板：第二次那个角色身上已经有光环，
        # 再点光环会弹「是否替换该角色原有光环？」——直接确认替换
        if self.click_text(
            text="是否替换该角色原有光环",
            box=self.PROTAGONIST_REPLACE_TITLE_BOX,
            click=False,
            allow_fail=True,
        ):
            CUS_LOGGER.info("该角色已有光环，确认替换")
            key_mouse_manager.click_point(*self.PROTAGONIST_REPLACE_CONFIRM_POSITION)
            key_mouse_manager.wait()

        box = self.PROTAGONIST_CONFIRM_BOX
        key_mouse_manager.click_point(
            (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, box=box)
        key_mouse_manager.wait()
        self.protagonist_picks = getattr(self, "protagonist_picks", 0) + 1
        self.protagonist_drag_failures = 0
        self.protagonist_done_at = time.monotonic()
        CUS_LOGGER.info("主角已选择（本局第 %d 次）", self.protagonist_picks)
        return 1

    TEA_ENTRY_BOX = [1753, 732, 1879, 768]
    TEA_ENTRY_POSITION = (1816, 752)
    TEA_CHAT_BOX = [345, 815, 430, 860]        # 「聊一聊」
    TEA_CHAT_POSITION = (387, 837)
    TEA_BLANK_BOX = [1400, 895, 1585, 945]     # 对话里的「点击空白处继续」（右侧，和别处不同位）
    TEA_BLANK_POSITION = (1491, 920)
    TEA_BACK_BOX = [1140, 705, 1215, 750]      # 选项列表里的「返回」（用来判定"这是选项界面"）
    # 选项区域：上边界让开标题、下边界让开「返回」。
    # 取「最靠下的那一项」（也就是「返回」正上方）而不是最上面那个：
    # 台词气泡永远在选项上方，取最上面的会被气泡骗到；选项下面的效果说明点下去
    # 同样落在该选项区块里，不影响结果。
    TEA_OPTIONS_BOX = [1050, 380, 1750, 800]
    # 选项右侧的「确认」：纵向位置跟着被选中那一行走（实测 y 460~703 都可能出现），
    # 所以不锁高度，只锁右侧这条竖带；左下角是真按钮（点它的识别框中心）
    TEA_CONFIRM_BOX = [1600, 400, 1900, 820]
    TEA_CONFIRM_TIMEOUT = 1.2      # 等「确认」按钮渲染出来的上限
    TEA_CONFIRM_STEP = 0.15
    TEA_REWARD_BOX = [860, 175, 1060, 220]     # 「领取茶歇奖励」
    TEA_OPEN_POSITION = (961, 983)             # 「开启」

    def option_confirmed (self):
        """选项被点中后，右侧会出现「确认」按钮；用它判断这一下有没有点中。"""
        try:
            return bool(self.click_text(
                text="确认", box=self.TEA_CONFIRM_BOX, click=False, allow_fail=True))
        except Exception:
            return False

    def choose_tea_break_option (self):
        """茶歇对话的选项：轮流点候选，选中后由「茶歇-确认奖励」去点确认。

        两个坑决定了不能用"点完立刻验证"的写法：

        1. 选项区同时混着台词气泡和效果说明，前者点了没反应、后者只有标题行能点；
        2. 后台模式下窗口捕获的画面会滞后一点，点完当帧读到的还是旧画面，
           于是"确认按钮没出现"并不代表没点中。

        所以这里只负责轮流点不同候选（避免死盯同一条无效文本），
        真正的推进交给「茶歇-确认奖励」：它在后续帧看到「确认」就会去点。
        """
        self.ts.forward(self.get_screen())
        # 选项已经选中时右侧会出现「确认」：这一步必须让给「茶歇-确认奖励」去点。
        # 否则「返回」一直在这条动作就会一直触发，把确认那一步饿死（实机卡在茶歇就是这样）。
        if self.option_confirmed():
            CUS_LOGGER.debug("茶歇选项已选中，等「确认」处理")
            return 0
        options = [
            item for item in self.ts.find_with_box(self.TEA_OPTIONS_BOX, redundancy=30)
            if item["raw_text"].strip()
            and "返回" not in item["raw_text"]
            and len(item["raw_text"].strip()) <= 15
        ]
        if not options:
            CUS_LOGGER.warning("茶歇选项没识别到，等下一轮")
            return 0

        options.sort(key=lambda item: item["box"][1])
        attempt = getattr(self, "tea_option_attempt", 0)
        item = options[attempt % len(options)]
        self.tea_option_attempt = attempt + 1
        if self.tea_option_attempt >= len(options) * 2:
            self.tea_option_attempt = 0
        CUS_LOGGER.info("尝试茶歇选项（第 %d 次）：%s", attempt + 1, item["raw_text"])
        self.click_box(item["box"])
        key_mouse_manager.wait()
        return 1

    EXIT_MAX_ATTEMPTS = 3
    EXIT_ACTION_NAME = "开始退出"
    def _exit_failed(self, reason):
        """退出没成功：解开「开始退出」的 once 锁存，让下一帧还能再试。

        引擎里命中即锁存，不主动解锁的话这条动作本轮再也不会被调用——
        日志写着"下一轮重试"却永远不重试，玩家看到的就是卡死。
        连续失败到上限后停手，避免在错误界面上反复连按 ESC。
        """
        self.exit_attempts += 1
        if self.exit_attempts < self.EXIT_MAX_ATTEMPTS:
            self.latched_events.discard(self.EXIT_ACTION_NAME)
            CUS_LOGGER.warning(
                "%s，第 %d/%d 次退出未完成，下一帧重试",
                reason, self.exit_attempts, self.EXIT_MAX_ATTEMPTS,
            )
        else:
            CUS_LOGGER.warning(
                "%s，已连续 %d 次退出失败，本轮停止重试（游戏可能停在非预期界面）",
                reason, self.exit_attempts,
            )
        return 0

    STAGE_BOXES = ([430, 48, 515, 100], [250, 85, 330, 135])
    STAGE_UPSCALE = 3           # 原尺寸 OCR 会漏字，放大三倍才稳
    # 各面终局节点：1 面到 1-6，2/3 面到 x-5（幕后茶歇会顶掉一个奖励节点，1-5 不算终局）
    PLANE_LAST_NODE = {1: 6, 2: 5, 3: 5}
    def auto_clear_target (self, chosen):
        """刷到并选中目标策略后取消它的勾选。

        只取消"这次真的选了"的那条：本屏出现过但没选的不算，下一屏还得靠它压优先级。
        """
        if not getattr(self, "auto_clear_targets", False):
            return False
        if not chosen or chosen not in self.strategy_targets:
            return False
        self.strategy_targets = [name for name in self.strategy_targets if name != chosen]
        CUS_LOGGER.info("已自动取消勾选：%s（剩余目标 %d 条）", chosen, len(self.strategy_targets))
        self.persist_strategy_targets()
        return True

    def persist_strategy_targets (self):
        """把取消后的目标列表写回配置文件——否则重开/下一把又会全勾回来。"""
        try:
            save_currency_settings({"strategy_targets": list(self.strategy_targets)})
        except Exception:
            CUS_LOGGER.warning("保存目标策略列表失败", exc_info=True)

    @staticmethod
    def canonical_strategies (texts):
        """把 OCR 出来的卡名对齐到 298 条已知策略名，对不上的保留原文（便于发现新策略）。"""
        aligned = []
        for text in texts:
            name = match_name(text) if text else None
            aligned.append(name or text)
        return aligned

    def _pick_strategy (self, texts, icon_presence):
        """选卡优先级：目标策略 > 未解锁图标 > 兜底；负面策略一律不选。

        返回 (下标, 理由)；理由为 fallback 表示"这屏没有值得优先选的"，调用方可以刷新再试。
        """
        avoid = set(self.strategy_avoid)
        allowed = [
            idx for idx, name in enumerate(texts)
            if name and name not in avoid
        ]
        if not allowed:
            CUS_LOGGER.warning("这一屏三张都是负面策略，只能跳过优先逻辑")
            allowed = [idx for idx, name in enumerate(texts) if name]
        if not allowed:
            return None, "empty"

        for target in self.strategy_targets:
            for idx in allowed:
                if texts[idx] == target:
                    return idx, f"目标策略「{target}」"

        for idx in allowed:
            if icon_presence[idx]:
                return idx, "未解锁图标"

        fallback = choose_fallback_investment(texts, icon_presence)
        if fallback not in allowed:
            fallback = allowed[0]
        return fallback, "fallback"

    def _refresh_auto_exit_plane (self):
        """按「还没收集到的目标策略」实时推算退出位面。"""
        if not self.auto_exit_plane:
            return
        if not self.strategy_targets:
            self.exit_plane = self.set_exit_plane
            return
        plane = exit_plane_for(self.strategy_targets, self.strategy_sampler.collected)
        if plane != self.exit_plane:
            CUS_LOGGER.info(
                "退出位面自动调整：第 %s 面（目标策略还剩 %d 条未收集）",
                plane, len(self.strategy_sampler.missing(self.strategy_targets)),
            )
        self.exit_plane = plane

    def read_stage (self):
        """读顶栏的「位面-节点」标记，返回 (位面, 节点)；认不出来返回 None。

        原来的写法不读位面（只按"选了几次策略"数），4.7 里策略数量和位面不再一一对应，
        必须真读一次。原尺寸 OCR 会漏字，放大三倍才稳。
        """
        self.get_screen()
        for box in self.STAGE_BOXES:
            patch = self.screen[box[1]:box[3], box[0]:box[2]]
            if patch is None or patch.size == 0:
                continue
            upscaled = cv2.resize(
                patch, None, fx=self.STAGE_UPSCALE, fy=self.STAGE_UPSCALE,
                interpolation=cv2.INTER_CUBIC)
            text = self.ts.ocr_one_row(upscaled)
            match = re.search(r"(\d)\s*[-—~]\s*(\d+)", text or "")
            if match:
                return int(match.group(1)), int(match.group(2))
        return None

    def _maybe_exit_by_stage (self):
        """在备战界面判断能不能退。

        条件：到达设定退出位面、且这一面已经选过策略。
        另外两种情况直接退：已经走过设定面数；或者设定面的终局节点到了却一次策略都没出现
        （周天鸽会把某一面的策略提前，那个面的选择就没了）。
        """
        if self.exit_plane is None:
            return False

        stage = self.read_stage()
        if stage is None:
            CUS_LOGGER.debug("没读到位面标记，本轮不判断退出")
            return False

        plane, node = stage
        self.current_plane = plane
        selected = self.plane_strategy_count.get(plane, 0)
        last_node = self.PLANE_LAST_NODE.get(plane, 5)

        if plane > self.exit_plane:
            CUS_LOGGER.info(
                "已越过退出位面（当前 %d-%d，设定第 %d 面），直接退出", plane, node, self.exit_plane)
            reason = "越过退出位面"
        elif plane == self.exit_plane and selected:
            CUS_LOGGER.info(
                "第 %d 面已选过 %d 次策略（当前 %d-%d），退出", plane, selected, plane, node)
            reason = "到达退出位面且已选过策略"
        elif plane == self.exit_plane and node >= last_node and not selected:
            CUS_LOGGER.info(
                "第 %d 面已到终局节点 %d-%d 却没出现策略（被提前到前面了），直接退出",
                plane, plane, node)
            reason = "设定面无策略"
        else:
            return False

        CUS_LOGGER.info("退出条件满足：%s", reason)
        self.exit_requested = True
        self.update_state("exit")
        return True

    HACK_OPTIONS_BOX = [480, 150, 1400, 430]   # 两张效果卡的文字区
    HACK_FALLBACK_POSITION = (1288, 284)       # 认不出选项时兜底点右侧那张卡
    HACK_CONFIRM_BOX = [1430, 575, 1560, 620]  # 「确认选择」

    def choose_hack_effect (self):
        """银狼的「骇入效果」面板：选右侧那张卡，再点确认选择。

        选项名字会变（数据拷贝仪 / 病毒防火墙…），所以不写死文字：OCR 卡片区，
        取最右边那张点掉；认不出来就按固定位置兜底，最后点「确认选择」。
        """
        self.ts.forward(self.get_screen())
        options = [
            item for item in self.ts.find_with_box(self.HACK_OPTIONS_BOX)
            if item["raw_text"].strip()
        ]
        if options:
            options.sort(key=lambda item: item["box"][0])
            target = options[-1]["box"]
            CUS_LOGGER.info("骇入效果选右侧：%s", options[-1]["raw_text"])
            self.click_box(target)
        else:
            CUS_LOGGER.warning("骇入面板没认出选项文字，按固定位置点右侧")
            key_mouse_manager.click_point(*self.HACK_FALLBACK_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=self.HACK_CONFIRM_BOX, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("骇入面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("骇入效果已选择")
        return 1

    CLARA_DETAIL_BOX = [540, 395, 1560, 455]      # 一整行「详情」按钮
    CLARA_CARD_OFFSET = 60                        # 详情上方 60px 就是卡片本体
    CLARA_FALLBACK_POSITION = (610, 350)          # 一个「详情」都没认出时兜底点第一张卡
    CLARA_CONFIRM_BOX = [1430, 560, 1560, 610]    # 「确认选择」

    def choose_clara_enhance (self):
        """克拉拉的「机心巧匠」面板：任选一个强化效果，再点「确认选择」。

        选项数量会变（3 张或 4 张），位置也不固定，所以拿每张卡下面的「详情」按钮当锚点：
        取最左边那个「详情」，点它正上方 60px（就是那张卡），再点确认。
        """
        self.ts.forward(self.get_screen())
        details = [
            item for item in self.ts.find_with_box(self.CLARA_DETAIL_BOX)
            if "详情" in item["raw_text"]
        ]
        if details:
            details.sort(key=lambda item: item["box"][0])
            box = details[0]["box"]
            position = ((box[0] + box[2]) // 2, max(0, box[1] - self.CLARA_CARD_OFFSET))
            CUS_LOGGER.info("强化面板按「详情」锚点选卡：%s", position)
            key_mouse_manager.click_point(*position)
        else:
            CUS_LOGGER.warning("强化面板没认出「详情」，按固定位置点第一张卡")
            key_mouse_manager.click_point(*self.CLARA_FALLBACK_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=self.CLARA_CONFIRM_BOX, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("强化面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("强化效果已选择")
        return 1

    DRAGON_DETAIL_BOX = [620, 380, 1520, 425]
    DRAGON_CARD_OFFSET = 60
    DRAGON_FALLBACK_POSITION = (697, 332)
    DRAGON_CONFIRM_BOX = [1430, 575, 1560, 620]

    def choose_dragon_enhance (self):
        """龙丹的「双龙吟」面板：任选一个羁绊，再点「确认选择」。

        四张卡位置固定，但仍拿「详情」按钮当锚点（点它正上方 60px），
        这样即使以后卡片重排也不会点空。
        """
        self.ts.forward(self.get_screen())
        details = [
            item for item in self.ts.find_with_box(self.DRAGON_DETAIL_BOX)
            if "详情" in item["raw_text"]
        ]
        if details:
            details.sort(key=lambda item: item["box"][0])
            box = details[0]["box"]
            position = ((box[0] + box[2]) // 2, max(0, box[1] - self.DRAGON_CARD_OFFSET))
            CUS_LOGGER.info("双龙吟面板按「详情」锚点选卡：%s", position)
            key_mouse_manager.click_point(*position)
        else:
            CUS_LOGGER.warning("双龙吟面板没认出「详情」，按固定位置点第一张卡")
            key_mouse_manager.click_point(*self.DRAGON_FALLBACK_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=self.DRAGON_CONFIRM_BOX, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("双龙吟面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("羁绊效果已选择")
        return 1

    BLACK_MARKET_TITLE_BOX = [940, 50, 1120, 100]

    def close_black_market (self):
        """翡翠的「黑市主理人」面板：不买任何东西，按 ESC 关掉并确认真的关了。"""
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()

        if self.click_text(
            text="黑市主理人", box=self.BLACK_MARKET_TITLE_BOX, click=False, allow_fail=True
        ):
            CUS_LOGGER.warning("「黑市主理人」按了 ESC 还在，等下一轮再按")
            return 0
        CUS_LOGGER.info("「黑市主理人」面板已关闭")
        return 1

    RANGER_DETAIL_BOX = [620, 380, 1520, 430]
    RANGER_CARD_OFFSET = 60
    RANGER_FALLBACK_POSITION = (700, 334)
    RANGER_CONFIRM_BOX = [1430, 575, 1560, 620]

    def choose_ranger_hero (self):
        """「巡海游侠」任命面板：任选一名角色，再点「确认选择」。

        四张卡位置固定，但仍拿「详情」按钮当锚点（点它正上方 60px），卡片重排也不会点空。
        """
        self.ts.forward(self.get_screen())
        details = [
            item for item in self.ts.find_with_box(self.RANGER_DETAIL_BOX)
            if "详情" in item["raw_text"]
        ]
        if details:
            details.sort(key=lambda item: item["box"][0])
            box = details[0]["box"]
            position = ((box[0] + box[2]) // 2, max(0, box[1] - self.RANGER_CARD_OFFSET))
            CUS_LOGGER.info("巡海游侠面板按「详情」锚点选角色：%s", position)
            key_mouse_manager.click_point(*position)
        else:
            CUS_LOGGER.warning("巡海游侠面板没认出「详情」，按固定位置点第一张卡")
            key_mouse_manager.click_point(*self.RANGER_FALLBACK_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=self.RANGER_CONFIRM_BOX, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("巡海游侠面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("巡海游侠任命完成")
        return 1

    BEAST_DETAIL_BOX = [680, 425, 1660, 480]
    BEAST_CARD_OFFSET = 60
    BEAST_FALLBACK_POSITION = (761, 377)
    BEAST_CONFIRM_BOX = [1430, 575, 1560, 620]

    def choose_beast_chimera (self):
        """「奇兽花园」面板：任选一只奇美拉，再点「确认选择」。

        三张宽卡位置固定，但仍拿「详情」按钮当锚点（点它正上方 60px），卡片重排也不会点空。
        """
        self.ts.forward(self.get_screen())
        details = [
            item for item in self.ts.find_with_box(self.BEAST_DETAIL_BOX)
            if "详情" in item["raw_text"]
        ]
        if details:
            details.sort(key=lambda item: item["box"][0])
            box = details[0]["box"]
            position = ((box[0] + box[2]) // 2, max(0, box[1] - self.BEAST_CARD_OFFSET))
            CUS_LOGGER.info("奇兽花园面板按「详情」锚点选卡：%s", position)
            key_mouse_manager.click_point(*position)
        else:
            CUS_LOGGER.warning("奇兽花园面板没认出「详情」，按固定位置点第一张卡")
            key_mouse_manager.click_point(*self.BEAST_FALLBACK_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=self.BEAST_CONFIRM_BOX, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("奇兽花园面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("奇美拉已选择")
        return 1

    DREAM_DETAIL_BOX = [880, 390, 1250, 435]
    DREAM_FALLBACK_POSITION = (938, 339)
    DREAM_CONFIRM_BOX = [1430, 552, 1560, 600]
    CARD_DETAIL_OFFSET = 60      # 「详情」上方这么多像素就是卡片本体

    def choose_master (self):
        """「从师」面板：任选一名角色作为师父，再点「确认选择」。

        这个面板的卡片没有「详情」按钮行，直接点卡片本体。
        注意红字提示和「巡海游侠」面板一样是「请选择一名角色」，靠副标题区分。
        """
        names = [
            item for item in self.ts.find_with_box(self.MASTER_NAME_BAND, forward=1)
            if item["raw_text"].strip()
        ]
        if names:
            names.sort(key=lambda item: item["box"][0])
            box = names[0]["box"]
            position = ((box[0] + box[2]) // 2, max(0, box[1] - self.MASTER_CARD_LIFT))
            CUS_LOGGER.info("从师面板按卡名「%s」选卡：%s", names[0]["raw_text"], position)
            key_mouse_manager.click_point(*position)
        else:
            CUS_LOGGER.warning("从师面板没认出卡名，按固定位置点第一张卡")
            key_mouse_manager.click_point(*self.MASTER_CARD_POSITION)
        key_mouse_manager.wait()

        if not self.click_text(text="确认选择", box=self.MASTER_CONFIRM_BOX,
                               click=True, allow_fail=True):
            CUS_LOGGER.warning("从师面板没点掉「确认选择」，等下一轮")
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("已选择师父")
        return 1

    def pick_card_above_detail (self, detail_box, confirm_box, fallback,
                                count=1, offset=None, label="面板"):
        """通用弹窗处理：一排「详情」按钮 → 点最左边 count 个正上方（= 那几张卡）→ 点「确认选择」。

        大多数弹窗是"任选一个"（默认 count=1）；「梦境交织」要选两个角色共舞，传 count=2。
        卡片数量/位置会变，所以用「详情」当锚点、从左往右取，不写死卡片坐标。
        """
        offset = self.CARD_DETAIL_OFFSET if offset is None else offset
        self.ts.forward(self.get_screen())
        details = [
            item for item in self.ts.find_with_box(detail_box)
            if "详情" in item["raw_text"]
        ]
        details.sort(key=lambda item: item["box"][0])

        if details:
            if len(details) < count:
                CUS_LOGGER.warning(
                    "%s只认出 %d 张卡，需要选 %d 张", label, len(details), count)
            for index, item in enumerate(details[:count], start=1):
                box = item["box"]
                position = ((box[0] + box[2]) // 2, max(0, box[1] - offset))
                CUS_LOGGER.info("%s按「详情」锚点选第 %d 张卡：%s", label, index, position)
                key_mouse_manager.click_point(*position)
                key_mouse_manager.wait()
        else:
            CUS_LOGGER.warning("%s没认出「详情」，按固定位置点卡", label)
            key_mouse_manager.click_point(*fallback)
            key_mouse_manager.wait()

        if not self.click_text(
            text="确认选择", box=confirm_box, click=True, allow_fail=True
        ):
            CUS_LOGGER.warning("%s没点掉「确认选择」，等下一轮", label)
            return 0
        key_mouse_manager.wait()
        CUS_LOGGER.info("%s选择完成", label)
        return 1

    def choose_dream_weave (self):
        """「梦境交织」面板：**要选两个**角色共舞（跟只选一个的面板不同），再点「确认选择」。"""
        return self.pick_card_above_detail(
            self.DREAM_DETAIL_BOX, self.DREAM_CONFIRM_BOX,
            self.DREAM_FALLBACK_POSITION, count=2, label="梦境交织")

