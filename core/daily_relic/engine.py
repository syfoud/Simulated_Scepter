"""日常遗器本自动化内核：纯状态机驱动，继承 AnyFate 复用寻路与战斗检测。

每轮循环识别当前界面，并执行对应转移；从任意已知状态都能推进到目标状态。
进入战斗后自动战斗、等待结束，最后退出关卡并领取每日实训委托奖励。
"""

import re
import time

from core.any_fate.engine import AnyFateUniverse
from core.simulated.utils import set_forground
from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import clean_text
from tool.storage import load_module_settings


# 各界面锚点：(特征文字, [左上x, 右下x, 左上y, 右下y])。
PHONE_ANCHOR = ("指南", [1319, 1364, 784, 809])
GUIDE_ANCHOR = ("每日实训", [103, 203, 65, 93])
GUIDE_CLICK_BOX = [440, 533, 198, 227]
TRAINING_ANCHOR = ("生存索引", [101, 201, 63, 96])
DIFF_UNIVERSE_ANCHOR = ("差分宇宙", [56, 148, 14, 42])

# 大地图特征：与 core/simulated/utils.py 的 is_run 使用同一检测位置和阈值。
HOME_WORLD_POS = (0.0245, 0.5185)

# 误触 ESC 弹出的「是否离开当前区域」确认框；点「取消」恢复副本界面。
LEAVE_CONFIRM_TEXT = "是否离开当前区域"
LEAVE_CONFIRM_BOX = [840, 1080, 530, 575]
LEAVE_CANCEL_BOX = [570, 930, 650, 710]

# 每日实训页面入口。
EXTRACTION_BOX = [300, 427, 436, 472]
EROSION_BOX = [303, 429, 649, 686]

# 副本列表内容区与滚动参数。
LIST_AREA = [660, 1700, 260, 990]
SCROLL_HOVER = (1407, 698)
SCROLL_TICKS = -4
SCROLL_SETTLE_SECONDS = 0.8
SCROLL_ATTEMPT_LIMIT = 15
ENTER_ROW_TOLERANCE = 40.0

# 内圈挑战设置。
INNER_COUNT_BOX = [1600, 1711, 857, 883]
INNER_PLUS_BOX = [1831, 1860, 888, 904]
INNER_MINUS_BOX = [1438, 1505, 884, 907]
INNER_START_BOX = [1656, 1759, 968, 1000]
INNER_STAMINA_BOX = [1495, 1599, 50, 81]

# 外圈挑战设置：挑战次数的显示与增减，底部先出现「挑战」，点击后弹确认框显示「开始挑战」。
OUTER_COUNT_BOX = [1489, 1600, 849, 878]
OUTER_PLUS_BOX = [1827, 1857, 876, 898]
OUTER_MINUS_BOX = [1235, 1264, 878, 900]
OUTER_CHALLENGE_BOX = [1619, 1673, 966, 1001]
OUTER_START_BOX = [1624, 1728, 968, 1000]
OUTER_STAMINA_BOX = [1640, 1737, 51, 78]

# 挑战设置页底部按钮的联合检测区，涵盖内外圈的「挑战」与「开始挑战」。
# y >= 950 是为了避开上方的「挑战次数 N」文本，防止误判。
CHALLENGE_BUTTON_AREA = [1560, 1800, 950, 1010]

# 退出关卡按钮；内外圈位置基本一致，取两者并集。
EXIT_BOX = [662, 767, 954, 990]
# 退出外圈副本后应回到侵蚀隧洞选本列表，左上角显示该分类名。
EROSION_ANCHOR_BOX = [102, 204, 48, 84]

# 每日委托奖励领取相关位置。
COMMISSION_BOX = [1708, 1753, 396, 420]           # 手机页面上的「委托」入口。
CLAIM_REWARD_BOX = [1449, 1578, 906, 945]         # 委托界面的「领取奖励」按钮。
DAILY_CLAIM_BOX = [411, 464, 811, 841]            # 每日实训栏的「领取」按钮。
DAILY_TRAINING_ENTRY_BOX = [303, 409, 196, 234]   # 进入「每日实训」菜单。
FINAL_CLOSE_BOX = [1589, 1637, 294, 327]          # 领取完成后的收尾按钮。

# 挑战次数上限与单次开拓力消耗。
MAX_RUNS = 6
STAMINA_PER_RUN = 40

# 循环领取的上限次数，避免异常时无限点击。
CLAIM_ATTEMPT_LIMIT = 20


class SkipExecution(RuntimeError):
    """本次执行应当跳过（例如开拓力不足），由 route 捕获后直接结束。"""


class DailyRelicKernel(AnyFateUniverse):
    """日常遗器本自动化内核。

    状态含义：
        home_world      大地图；按 ESC 打开手机页面。仅处理一次。
        leave_confirm   误触 ESC 弹出的离开确认框；点取消恢复。
        phone           手机页面；点击「指南」。
        guide           指南页面；点击中央每日实训卡片。
        training        每日实训页面；进入内圈或外圈副本列表。
        relic_list      副本列表；定位目标副本并点击右侧「进入」。
        challenge_setup 挑战设置页；设置次数后点开始挑战。
        diff_universe   差分宇宙准备页（仅内圈）；释放秘技并寻路到怪。
        battle          战斗中；确保自动战斗开启。
        exit_available  战斗结束；退出关卡并领取每日实训委托奖励后结束。
    """

    def __init__(self):
        super().__init__()
        self.daily_config = load_module_settings(__file__)
        self._skills_released = False
        self._challenge_started = False
        self._extraction_clicked = False
        self._scroll_attempts = 0
        self._done = False
        # 大地图只在流程开始时处理一次；进过副本后的过场画面也常常误匹配
        # big_world，用该 flag 屏蔽后续误判。离开确认弹窗出现时也会置位。
        self._home_world_locked = False
        # 外圈「挑战」按钮点击后弹确认框，用该 flag 区分是"首屏设置"还是"确认框"。
        self._outer_challenge_clicked = False

    @property
    def stopping(self):
        """当前是否收到停止请求（GUI 按钮、热键或任务线程结束）。"""
        return self._stop or get_global_stop_flag()

    # ---------- 主循环 ----------

    def route(self):
        """状态机循环：识别当前界面并执行对应转移。"""
        set_forground()
        # 初始化寻路状态（big_map_init / now_loc / mini_state 等），
        # 与 SimulatedUniverse.route 保持一致；navigate_battle 依赖这些字段。
        self.init_map()
        try:
            while not self.stopping and not self._done:
                state = self.detect_state()
                self.update_state(state)
                CUS_LOGGER.debug("当前状态：%s", state)
                self.handle_state(state)
        except SkipExecution as error:
            CUS_LOGGER.info("本次执行已跳过：%s", error)
            return
        if not self.stopping and self._done:
            CUS_LOGGER.info("日常遗器本流程完成")

    def detect_state(self):
        """识别当前界面。

        Returns:
            状态名；未匹配到已知界面时返回 ``"unknown"``。

        判定顺序：先处理弹窗与战斗（会挡住其他界面），再处理深层副本
        界面，最后处理浅层入口界面。``home_world`` 仅在流程最开始生效
        一次，避免副本加载过场被误判。
        """
        self.get_screen()
        # 战斗判定：左上角 auto_2 与右下角 battle 任一命中即认为进入战斗。
        # 两个图放在一起能覆盖不同版本、不同战斗模式下的图标差异。
        if (self.check("auto_2", 0.0583, 0.0769)
                or self.check("battle", 0.9594, 0.9778)):
            return "battle"
        self.ts.forward(self.screen)
        if self._text_in_res(LEAVE_CONFIRM_TEXT, LEAVE_CONFIRM_BOX):
            return "leave_confirm"
        if not self._home_world_locked and self.check(
                "big_world", *HOME_WORLD_POS, threshold=0.995):
            return "home_world"
        if self._text_in_res("退出关卡", EXIT_BOX):
            return "exit_available"
        if self._text_in_res("差分宇宙", DIFF_UNIVERSE_ANCHOR[1]):
            return "diff_universe"
        if self._text_in_res("指南", PHONE_ANCHOR[1]):
            return "phone"
        # challenge_setup 与 relic_list 早于 training：两者都在「生存索引」
        # 菜单下，左上角标题相同，靠右下角的按钮文字区分。
        if self._text_in_res("挑战", CHALLENGE_BUTTON_AREA):
            return "challenge_setup"
        if self._extraction_clicked and self._text_in_res("进入", LIST_AREA):
            return "relic_list"
        if self._text_in_res("每日实训", GUIDE_ANCHOR[1]):
            return "guide"
        if self._text_in_res("生存索引", TRAINING_ANCHOR[1]):
            return "training"
        return "unknown"

    def handle_state(self, state):
        """按识别到的状态执行对应转移。"""
        if state == "home_world":
            self._handle_home_world()
        elif state == "leave_confirm":
            self._handle_leave_confirm()
        elif state == "phone":
            self._handle_phone()
        elif state == "guide":
            self._handle_guide()
        elif state == "training":
            self._handle_training()
        elif state == "relic_list":
            self._handle_relic_list()
        elif state == "challenge_setup":
            self._handle_challenge_setup()
        elif state == "diff_universe":
            self._handle_diff_universe()
        elif state == "battle":
            self._handle_battle()
        elif state == "exit_available":
            self._handle_exit_available()
        else:
            CUS_LOGGER.debug("未识别到已知界面，等待下一次识别")
            self.pause(0.5)

    # ---------- 状态处理 ----------

    def _handle_home_world(self):
        """大地图：按 ESC 打开手机页面。只执行一次。"""
        self._home_world_locked = True
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.pause(1.0)

    def _handle_leave_confirm(self):
        """误触 ESC 弹出的离开确认：点「取消」恢复到副本界面。"""
        CUS_LOGGER.info("检测到「是否离开当前区域」弹窗，点击取消恢复")
        self.click_box_center(LEAVE_CANCEL_BOX)
        key_mouse_manager.wait()
        self.pause(0.8)
        # 无论是否真误触，一旦见到该弹窗就锁定 home_world。
        self._home_world_locked = True

    def _handle_phone(self):
        """手机页面：点击「指南」入口。"""
        self.click_box_center(PHONE_ANCHOR[1])
        key_mouse_manager.wait()
        self.pause(1.0)

    def _handle_guide(self):
        """指南页面：点击中央每日实训卡片。"""
        self.click_box_center(GUIDE_CLICK_BOX)
        key_mouse_manager.wait()
        self.pause(1.0)

    def _handle_training(self):
        """每日实训页面：进入内圈或外圈的副本列表。

        「生存索引」菜单只在首次进入时需要点击分类；后续回合若因识别延迟
        再次落到该状态，通过 ``_extraction_clicked`` 跳过重复点击。
        """
        if self._extraction_clicked:
            self.pause(0.5)
            return
        module = self.daily_config.get("daily_relic_module", "inner")
        if module == "inner":
            self.click_box_center(EXTRACTION_BOX)
            key_mouse_manager.wait()
        else:
            # 「侵蚀隧洞」分类若已可见就直接点，否则滚动左侧分类列表后再找。
            if not self._text_in_box_fresh("侵蚀隧洞", EROSION_BOX):
                cx = (EXTRACTION_BOX[0] + EXTRACTION_BOX[1]) // 2
                cy = (EXTRACTION_BOX[2] + EXTRACTION_BOX[3]) // 2
                key_mouse_manager.scroll(SCROLL_TICKS, cx, cy)
                key_mouse_manager.wait()
                self.pause(1.0)
                if self.stopping:
                    return
                if not self._text_in_box_fresh("侵蚀隧洞", EROSION_BOX):
                    CUS_LOGGER.warning("未识别到「侵蚀隧洞」，稍后重试")
                    return
            self.click_box_center(EROSION_BOX)
            key_mouse_manager.wait()
        self._extraction_clicked = True
        self.pause(1.5)

    def _handle_relic_list(self):
        """副本列表：定位目标副本并点击其右侧「进入」。"""
        target = self._target_name()
        if not target:
            raise RuntimeError("未配置目标副本名")
        self.ts.forward(self.get_screen())
        enter = self._find_enter_right(target)
        if enter is not None:
            key_mouse_manager.click(*enter)
            key_mouse_manager.wait()
            self.pause(1.5)
            return
        self._scroll_attempts += 1
        if self._scroll_attempts > SCROLL_ATTEMPT_LIMIT:
            raise RuntimeError(
                f"滚动 {self._scroll_attempts} 次后仍未找到目标副本「{target}」")
        key_mouse_manager.scroll(SCROLL_TICKS, *SCROLL_HOVER)
        key_mouse_manager.wait()
        self.pause(SCROLL_SETTLE_SECONDS)

    def _handle_challenge_setup(self):
        """挑战设置页：设置次数并点击开始挑战。

        内圈页面底部是「开始挑战」，点击后直接进入战斗。
        外圈页面底部是「挑战」，点击后弹出确认框显示「开始挑战」，
        需要再点一次。两步共用该 handler，通过 ``_outer_challenge_clicked``
        区分当前处于哪一步。
        """
        module = self.daily_config.get("daily_relic_module", "inner")

        # 已点过最终的开始挑战，等待界面切换。
        if self._challenge_started:
            self.pause(0.5)
            return

        # 外圈：已点过第一屏的「挑战」，等确认框出现后再点「开始挑战」。
        if module == "outer" and self._outer_challenge_clicked:
            if not self._text_in_box_fresh("开始挑战", OUTER_START_BOX):
                self.pause(0.5)
                return
            self.click_box_center(OUTER_START_BOX)
            key_mouse_manager.wait()
            self.pause(1.5)
            self._challenge_started = True
            return

        # 首次进入设置页：按配置调整次数并点击按钮。
        if module == "inner":
            runs = self._resolve_runs("inner", INNER_STAMINA_BOX)
            self._adjust_challenge_count(
                runs, INNER_COUNT_BOX, INNER_PLUS_BOX, INNER_MINUS_BOX)
            if self.stopping:
                return
            self.click_box_center(INNER_START_BOX)
            key_mouse_manager.wait()
            self.pause(1.5)
            self._challenge_started = True
        else:
            runs = self._resolve_runs("outer", OUTER_STAMINA_BOX)
            self._adjust_challenge_count(
                runs, OUTER_COUNT_BOX, OUTER_PLUS_BOX, OUTER_MINUS_BOX)
            if self.stopping:
                return
            self.click_box_center(OUTER_CHALLENGE_BOX)
            key_mouse_manager.wait()
            self.pause(0.8)
            self._outer_challenge_clicked = True

    def _handle_diff_universe(self):
        """差分宇宙准备页（内圈）：释放秘技后寻路到怪。"""
        if self._skills_released:
            # 已释放过，等待界面切换；不再重复施放。
            self.pause(0.5)
            return
        order = self._parse_skill_order()
        if order:
            # 给游戏留出进入稳定准备状态的时间，避免施放被吞。
            self.pause(0.4)
            for index, slot in enumerate(order):
                if self.stopping:
                    return
                key_mouse_manager.press(slot)
                key_mouse_manager.wait()
                self.pause(0.2)
                key_mouse_manager.press("e")
                key_mouse_manager.wait()
                if index < len(order) - 1:
                    self.pause(0.6)
        self._skills_released = True
        if self.stopping:
            return
        # 复用父类的寻路：没录过图时走 get_path_only_minimap（小地图寻路），
        # 已录过图时走 get_path_with_big_map。都会在到达怪附近或检测到
        # 遇敌红环后返回。
        self.navigate_battle()

    def _handle_battle(self):
        """战斗中：确保自动战斗开启。

        与 core/any_fate/actions/insect.json 中「自动战斗检测」一致：
        看到 c 图标即按 v 切换到自动战斗；c 图标消失后不再重复按。
        """
        self.get_screen()
        if self.check("c", 0.9891, 0.1491, threshold=0.9):
            key_mouse_manager.press("v")
            key_mouse_manager.wait()
            self.pause(0.8)
        else:
            self.pause(0.5)

    def _handle_exit_available(self):
        """战斗结束：退出关卡、回到大地图、领取每日委托奖励后结束流程。"""
        self.click_box_center(EXIT_BOX)
        key_mouse_manager.wait()
        self.pause(1.0)
        if self.daily_config.get("daily_relic_module", "inner") == "outer":
            # 外圈：等待回到侵蚀隧洞选本列表，再按一次 ESC。
            if not self._wait_for_anchor("侵蚀隧洞", EROSION_ANCHOR_BOX, timeout=15.0):
                if not self.stopping:
                    CUS_LOGGER.warning("未确认回到侵蚀隧洞列表，仍尝试结束流程")
            key_mouse_manager.press("esc")
            key_mouse_manager.wait()
            self.pause(0.5)
        self._claim_daily_training_rewards()
        self._done = True

    # ---------- 每日委托奖励领取 ----------

    def _claim_daily_training_rewards(self):
        """领取每日实训委托奖励。

        串行执行，不参与主状态机循环，避免干扰刷本流程。步骤：
        等待大地图 → ESC → 委托 → 领取奖励 → ESC → 指南
        →（若位于生存索引则进入每日实训）→ 循环领取 → 收尾按钮 → ESC ×2。
        """
        if not self._wait_home_world(timeout=15.0):
            if not self.stopping:
                CUS_LOGGER.warning("未确认回到大地图，跳过每日委托奖励领取")
            return

        # 打开手机页面，进入委托界面并领取奖励。
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.pause(1.0)
        if not self._wait_and_click("委托", COMMISSION_BOX, timeout=5.0):
            if not self.stopping:
                CUS_LOGGER.warning("未识别到「委托」入口，跳过每日委托奖励领取")
            return
        self.pause(1.0)
        if not self._wait_and_click("领取奖励", CLAIM_REWARD_BOX, timeout=5.0):
            if not self.stopping:
                CUS_LOGGER.warning("未识别到「领取奖励」按钮，跳过每日委托奖励领取")
            return
        self.pause(0.5)

        # 回到手机页面，进入指南。
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.pause(0.8)
        if not self._wait_and_click("指南", PHONE_ANCHOR[1], timeout=5.0):
            if not self.stopping:
                CUS_LOGGER.warning("未识别到「指南」入口，结束每日委托奖励领取")
            return
        self.pause(1.0)

        # 若仍位于「生存索引」菜单（每日实训尚未展开），点击进入每日实训。
        if self._text_in_box_fresh("生存索引", TRAINING_ANCHOR[1]):
            self.click_box_center(DAILY_TRAINING_ENTRY_BOX)
            key_mouse_manager.wait()
            self.pause(1.0)

        # 循环领取直到没有可领取的奖励。
        for _ in range(CLAIM_ATTEMPT_LIMIT):
            if self.stopping:
                return
            if not self._text_in_box_fresh("领取", DAILY_CLAIM_BOX):
                break
            self.click_box_center(DAILY_CLAIM_BOX)
            key_mouse_manager.wait()
            self.pause(0.3)

        # 收尾：点击收尾按钮并两次 ESC 退出。
        self.click_box_center(FINAL_CLOSE_BOX)
        key_mouse_manager.wait()
        self.pause(0.3)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.pause(0.3)
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.pause(0.3)

    # ---------- 辅助 ----------

    def _target_name(self):
        """返回当前模块配置的目标副本展示名。"""
        module = self.daily_config.get("daily_relic_module", "inner")
        return self.daily_config.get(f"daily_relic_{module}", "")

    def _text_in_res(self, anchor, box):
        """用已刷新的 OCR 结果判断文字是否出现在区域内。

        Args:
            anchor: 期望出现的文字。
            box: 识别区域 [左上x, 右下x, 左上y, 右下y]。
        """
        items = self.ts.find_with_box(box=box, redundancy=20)
        return any(anchor in clean_text(item["raw_text"]) for item in items)

    def _text_in_box_fresh(self, anchor, box):
        """重新截图后判断文字是否出现在区域内。"""
        self.ts.forward(self.get_screen())
        return self._text_in_res(anchor, box)

    def _find_enter_right(self, target_name):
        """在列表区域找到目标副本及其右侧「进入」，返回按钮中心像素坐标。

        Args:
            target_name: 配置中记录的展示名，例如「霜风之径-收容舱段」；
                游戏内只显示第一个「-」之前的部分，匹配时自动截断。

        Returns:
            (x, y) 像素坐标；未找到时返回 None。
        """
        match_name = target_name.split("-", 1)[0]
        named = [item for item in self.ts.find_with_box(box=LIST_AREA, redundancy=20)
                 if match_name in clean_text(item["raw_text"])]
        if not named:
            return None
        name_box = named[0]["box"]
        name_y = (name_box[2] + name_box[3]) / 2
        name_x2 = name_box[1]
        best = None
        best_dy = ENTER_ROW_TOLERANCE + 1.0
        for item in self.ts.res:
            box = item["box"]
            if "进入" not in clean_text(item["raw_text"]):
                continue
            if box[0] <= name_x2:
                continue
            dy = abs((box[2] + box[3]) / 2 - name_y)
            if dy < best_dy:
                best_dy = dy
                best = ((box[0] + box[1]) // 2, (box[2] + box[3]) // 2)
        return best

    def _resolve_runs(self, module, stamina_box):
        """按配置决定本次挑战次数。

        Args:
            module: ``"inner"`` 或 ``"outer"``。
            stamina_box: 该模块显示开拓力的区域。

        Returns:
            1~6 之间的整数。

        Raises:
            SkipExecution: 勾选自动判断且剩余开拓力不足 40。
        """
        auto = bool(self.daily_config.get(f"daily_relic_{module}_auto", False))
        if not auto:
            return int(self.daily_config.get(f"daily_relic_{module}_runs", 1))
        stamina = self._read_stamina(stamina_box)
        if stamina is None:
            raise RuntimeError(f"无法读取{module}模块的开拓力")
        if stamina < STAMINA_PER_RUN:
            raise SkipExecution(
                f"{module} 模块开拓力不足 {STAMINA_PER_RUN}（当前 {stamina}）")
        return min(MAX_RUNS, stamina // STAMINA_PER_RUN)

    def _adjust_challenge_count(self, target, count_box, plus_box, minus_box):
        """通过点击 +/- 按钮将挑战次数调整到目标值。

        Args:
            target: 期望的挑战次数（1~6）。
            count_box: 当前「挑战次数 N」的显示区域。
            plus_box: 增加次数的按钮区域。
            minus_box: 减少次数的按钮区域。
        """
        for _ in range(MAX_RUNS + 1):
            if self.stopping:
                return
            current = self._read_int_in_box(count_box)
            if current is None:
                CUS_LOGGER.warning("无法读取当前挑战次数，跳过调整")
                return
            if current == target:
                return
            box = plus_box if current < target else minus_box
            self.click_box_center(box)
            key_mouse_manager.wait()
            self.pause(0.3)
        CUS_LOGGER.warning("挑战次数调整超过上限，当前仍非目标值")

    def _parse_skill_order(self):
        """从配置解析秘技顺序。

        只接受 1/2/3/4 且不重复；留空或非法时返回空列表。

        Returns:
            槽位数字字符列表，例如 ``["1", "3", "4", "2"]``。
        """
        raw = str(self.daily_config.get(
            "daily_relic_inner_skill_order", "")).strip()
        if not raw:
            return []
        if not all(c in "1234" for c in raw):
            CUS_LOGGER.warning("秘技顺序只能包含 1/2/3/4，已跳过释放")
            return []
        if len(set(raw)) != len(raw):
            CUS_LOGGER.warning("秘技顺序不能有重复数字，已跳过释放")
            return []
        return list(raw)

    def click_box_center(self, box):
        """点击由 [左上x, 右下x, 左上y, 右下y] 描述的区域中心。"""
        key_mouse_manager.click(
            (box[0] + box[1]) // 2,
            (box[2] + box[3]) // 2,
        )

    def pause(self, seconds):
        """在键鼠队列中等待，允许停止请求即时打断。

        Args:
            seconds: 期望等待的时长，单位为秒。
        """
        key_mouse_manager.sleep(seconds)
        key_mouse_manager.wait()

    def _read_int_in_box(self, box):
        """识别区域内的第一个整数。"""
        text = self.ts.ocr_one_row(self.get_screen(), box)
        if not text:
            return None
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None

    def _read_stamina(self, box):
        """识别开拓力显示区域，返回分子（剩余开拓力）。"""
        text = self.ts.ocr_one_row(self.get_screen(), box)
        if not text:
            return None
        match = re.search(r"(\d+)\s*/\s*\d+", text)
        return int(match.group(1)) if match else None

    def _wait_for_anchor(self, anchor, box, timeout=10.0):
        """等待指定文字出现在指定区域。

        Args:
            anchor: 期望出现的文字。
            box: 识别区域 [左上x, 右下x, 左上y, 右下y]。
            timeout: 等待超时（秒）。

        Returns:
            True 表示识别成功；False 表示超时或收到停止请求。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stopping:
                return False
            if self._text_in_box_fresh(anchor, box):
                return True
            self.pause(0.3)
        return False

    def _wait_and_click(self, anchor, box, timeout=5.0):
        """等待文字出现在指定区域，识别到后点击该区域中心。

        Args:
            anchor: 期望出现的文字。
            box: 识别区域 [左上x, 右下x, 左上y, 右下y]。
            timeout: 等待超时（秒）。

        Returns:
            True 表示识别并点击成功；False 表示超时或停止。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stopping:
                return False
            if self._text_in_box_fresh(anchor, box):
                self.click_box_center(box)
                key_mouse_manager.wait()
                return True
            self.pause(0.3)
        return False

    def _wait_home_world(self, timeout=15.0):
        """等待回到大地图。

        Args:
            timeout: 等待超时（秒）。

        Returns:
            True 表示识别成功；False 表示超时或停止。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stopping:
                return False
            if self.check("big_world", *HOME_WORLD_POS,
                          threshold=0.995, fresh=True):
                return True
            self.pause(0.5)
        return False


def create_engine(*, script=False):
    return DailyRelicKernel()