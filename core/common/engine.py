"""从模拟宇宙和货币战争提取的识别、状态转移及动作分发。"""

import time

import cv2 as cv
import numpy as np

from tool.GLOBAL import factor, key_mouse_manager
from tool.log import CUS_LOGGER, log_emitter
from tool.mask import MASK, crop_region, region_center_point
from tool.public_ocr import load_actions, merge_text
from tool.utils.image_tool import find_image_by_name


class StateKernel:
    def __init__(self):
        self.state = None
        self.last_state = None
        self.last_update_time = None
        self.action_history = []
        self.action_time = time.time()
        self.latched_events = set()
        # 最近一次图片匹配的落框 [x1, x2, y1, y2]，点击时写进日志便于核对落点
        self.tb = None

    def update_state(self, state):
        log_emitter.find_path_state_signal.emit(state if state is not None else "未识别")
        if self.state is None or self.state != state:
            self.last_state = self.state
            self.state = state
            self.last_update_time = time.time()
            CUS_LOGGER.debug("当前状态%s，更新时间%s", state, self.last_update_time)

    def wait_loading(self):
        started = time.time()
        while time.time() - started < 2:
            if np.mean(self.get_screen()) > 12:
                break
            if self.state != "black":
                CUS_LOGGER.info("无边的黑暗中，没有来由地，一道声音始终在耳边萦绕……")
                self.update_state("black")
        if np.mean(self.get_screen()) > 12 and self.state == "black":
            self.update_state(self.last_state)

    def run_static(self, json_path=None, json_file=None, action_list=None):
        self.wait_loading()
        return self.match_actions(json_path, json_file, action_list)

    def match_actions(self, json_path=None, json_file=None, action_list=None, skip_check=False):
        """按配置顺序识别首个界面，执行它的动作并保存最近十项历史。"""
        if json_file is None:
            json_file = self.default_json if json_path is None else load_actions(json_path)
        for group in action_list or json_file:
            for action in json_file[group]:
                trigger = action["trigger"]
                condition = trigger.get("condition")
                text_trigger = bool(trigger.get("text"))
                if text_trigger:
                    text = self.ts.find_with_box(trigger["box"], redundancy=trigger.get("redundancy", 30))
                    matched = skip_check or (
                        (condition is None or condition == self.state)
                        and text and trigger["text"] in merge_text(text)
                    )
                elif trigger.get("photo"):
                    if condition is not None and condition != self.state:
                        continue
                    mask_name = trigger.get("mask")
                    if mask_name:
                        matched = self.check(
                            trigger["photo"], mask=MASK[mask_name],
                            threshold=trigger.get("threshold"),
                            use_binary=trigger.get("binary", False),
                        )
                    elif "pos" in trigger:
                        matched = self.check(
                            trigger["photo"], trigger["pos"]["x"], trigger["pos"]["y"],
                            threshold=trigger.get("threshold"),
                            use_binary=trigger.get("binary", False),
                        )
                    else:
                        matched = self.click_target(
                            find_image_by_name(trigger["photo"]),
                            threshold=trigger.get("threshold", 0.9), flag=False, click=False,
                        )
                elif trigger.get("state_only"):
                    matched = condition is None or condition == self.state
                else:
                    continue
                if not matched:
                    self.latched_events.discard(action["name"])
                    continue
                name = action["name"]
                if trigger.get("once"):
                    if name in self.latched_events:
                        continue
                    self.latched_events.add(name)
                interval = trigger.get("interval")
                if interval and self.action_history and self.action_history[-1] == name:
                    if time.time() - self.action_time < interval:
                        return name, 1
                CUS_LOGGER.debug("%s触发并执行指令%s，条件：%s", factor, name,
                                 trigger.get("text") or trigger.get("photo") or "state_only")
                result = None
                for step in action["actions"]:
                    result = self.do_action(step)
                self.static_completed(name, result)
                self.action_history.append(name)
                self.action_history = self.action_history[-10:]
                self.action_time = time.time()
                return name, 1 if text_trigger else (0 if result is None else result)
        return "", 0

    def static_completed(self, name, result):
        """子内核在动作完成后执行自己的结算规则。"""

    def do_action(self, action):
        if isinstance(action, str):
            return getattr(self, action)()
        if "text" in action:
            text = self.ts.find_with_box(action.get("box", [0, 1920, 0, 1080]),
                                         redundancy=action.get("redundancy", 30))
            for item in text:
                if action["text"] in item["raw_text"]:
                    self.click_box(item["box"])
                    return 1
        if "photo" in action:
            self.click_target(find_image_by_name(action["photo"]), action.get("threshold", 0.9),
                              flag=False, click=True)
        elif "position" in action:
            self.click_position(action["position"])
        elif "sleep" in action:
            self.action_sleep(float(action["sleep"]))
        elif "real_sleep" in action:
            time.sleep(float(action["real_sleep"]))
        elif "press" in action:
            self.action_press(action["press"], action.get("time", 0))
        elif "drag" in action:
            key_mouse_manager.drag_point(*action["drag"])
        elif "scroll" in action:
            # 滚动落点固定在画面中心，脚本里只写滚动格数
            key_mouse_manager.scroll_point(960, 540, direct=action["scroll"])
        elif "set_state" in action:
            self.update_state(action["set_state"])
        else:
            return 0
        return 1

    def action_sleep(self, seconds):
        key_mouse_manager.sleep(seconds)

    def action_press(self, key, seconds):
        key_mouse_manager.press(key, seconds)

    def prepare_script(self):
        key_mouse_manager.start()

    def scan_screenshot(self, prepared):
        screenshot = self.get_screen()
        result = cv.matchTemplate(screenshot, prepared, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        return {
            "screenshot": screenshot,
            "min_val": min_val,
            "max_val": max_val,
            "min_loc": min_loc,
            "max_loc": max_loc,
        }

    def calculated(self, result, shape):
        mat_top, mat_left = result["max_loc"]
        prepared_height, prepared_width, prepared_channels = shape
        x = int((mat_top + mat_top + prepared_width) / 2)
        y = int((mat_left + mat_left + prepared_height) / 2)
        return x, y

    def click_target(self, target_path, threshold, flag=True, sub=True, click=False):
        target = target_path
        while not self._stop:
            result = self.scan_screenshot(target)
            if result["max_val"] > threshold:
                CUS_LOGGER.debug(f"全局图像匹配度{result['max_val']}")
                points = self.calculated(result, target.shape)
                if click:
                    # 全屏匹配的 max_loc 已是绝对坐标，配上模板尺寸就是匹配框
                    box = [int(result["max_loc"][0]),
                           int(result["max_loc"][0] + target.shape[1]),
                           int(result["max_loc"][1]),
                           int(result["max_loc"][1] + target.shape[0])]
                    key_mouse_manager.click_point(*points, box=box)
                return True
            if not flag:
                return False
            elif sub:  # 降低阈值直到匹配到为止
                threshold -= 0.01

    def get_local(self, x, y, size, large=True):
        """按 1920x1080 像素坐标截取 (x, y) 附近的画面，供模板匹配使用。"""
        sx, sy = size[0] + 60 * large, size[1] + 60 * large
        bx, by = int(x), int(y)
        return self.screen[
            max(0, by - sx // 2) : min(self.yy, by + sx // 2),
            max(0, bx - sy // 2) : min(self.xx, bx + sy // 2),
            :,
        ]

    def check(self, path, x=None, y=None, mask=None, threshold=None, use_binary=False,fresh=False):
        """
        判断截图中指定区域或匹配中心点附近是否存在匹配模板
        path：匹配模板的路径，
        x,y：匹配中心点，1920x1080 像素坐标（原点在客户区左上角），
        mask：识别区域 [x1, x2, y1, y2]（见 tool/mask.py），给出时忽略 x,y，
        threshold：匹配阈值
        """
        if fresh:
            self.get_screen()
        if threshold is None:
            threshold = self.threshold
        target = find_image_by_name(path)
        if target is None:
            # 模板名写错/文件缺失时直接判定为未匹配：否则 target.shape 会抛 AttributeError，
            # 中断整个任务线程，且现场已无法判断是哪个模板名写错了
            CUS_LOGGER.error(f"模板 {path} 不存在，本次匹配判定为未匹配")
            return False
        target = cv.resize(
            target,
            dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
        )
        if mask is None:
            center_x, center_y = x, y
            local_screen = self.get_local(x, y, target.shape)
        else:
            center_x, center_y = region_center_point(mask)
            local_screen = crop_region(self.screen, mask)
        if use_binary:
            # 将截图和模板图像转换为灰度图
            if len(local_screen.shape) == 3:
                gray_screen = cv.cvtColor(local_screen, cv.COLOR_BGR2GRAY)
            else:
                gray_screen = local_screen

            if len(target.shape) == 3:
                gray_target = cv.cvtColor(target, cv.COLOR_BGR2GRAY)
            else:
                gray_target = target

            # 对截图和模板进行二值化处理
            _, binary_screen = cv.threshold(gray_screen, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            _, binary_target = cv.threshold(gray_target, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)

            # 使用二值化图像进行匹配
            result = cv.matchTemplate(binary_screen, binary_target, cv.TM_CCORR_NORMED)
        else:
            try:
                result = cv.matchTemplate(local_screen, target, cv.TM_CCORR_NORMED)
            except Exception:
                CUS_LOGGER.error(f"{path}匹配失败，源图像{local_screen.shape}，目标图像{target.shape}")
                raise
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        # 匹配框中心相对局部截图中心的像素偏移，叠加到请求中心点上即为实际匹配中心
        offset_x = max_loc[0] - 0.5 * local_screen.shape[1] + 0.5 * target.shape[1]
        offset_y = max_loc[1] - 0.5 * local_screen.shape[0] + 0.5 * target.shape[0]
        self.tx = center_x + offset_x
        self.ty = center_y + offset_y
        self.tm = max_val
        # 匹配框由中心反推：日志里的框中心就和真正点击的点完全一致，
        # 模板在截图边缘被裁掉时也不会因为局部截图原点被夹紧而偏移
        half_width, half_height = target.shape[1] / 2, target.shape[0] / 2
        self.tb = [int(self.tx - half_width), int(self.tx + half_width),
                   int(self.ty - half_height), int(self.ty + half_height)]
        if max_val > threshold:
            if self.last_info != path:
                CUS_LOGGER.debug(f"匹配到图片记忆切片 {path} 相似度 {max_val} 阈值 {threshold}")
            self.last_info = path
        return max_val > threshold

    def get_screen(self):
        current_time = time.time()
        if hasattr(self, 'last_get_screen_time') and self.last_get_screen_time is not None:
            interval = current_time - self.last_get_screen_time
            self.fps_list.append(interval)
            if len(self.fps_list) > 30:
                self.fps_list.pop(0)
            avg_interval = sum(self.fps_list) / len(self.fps_list)
            # 使用信号发射方式更新FPS，避免多线程直接操作GUI
            log_emitter.fps_update_signal.emit(avg_interval)
            # log.info(f"平均FPS: {1 / avg_interval:.2f}")
        self.last_get_screen_time = current_time
        self.screen = self.sct.grab(self.x0, self.y0)
        return self.screen

    def click_box(self, box):
        """
        点击给定坐标框的中心位置

        Args:
            box: 坐标框，格式为[x1, x2, y1, y2]，其中x1,x2为横向坐标，y1,y2为纵向坐标，
                单位是 1920x1080 像素坐标（原点在客户区左上角）
        """
        x = (box[0] + box[1]) / 2
        y = (box[2] + box[3]) / 2
        key_mouse_manager.click_point(x, y, box=box)

    def click_position(self, position, box=None):
        """
        点击给定位置坐标

        Args:
            position: 位置坐标，格式为[x, y]，单位为 1920x1080 像素坐标（原点在客户区左上角）
            box: 这次点击来源的框 [x1, x2, y1, y2]，交不出来就不传，只用于写日志
        """
        if box is None:
            # 没有来源框（纯坐标点击）时按原样传参，日志与旧版完全一致
            key_mouse_manager.click_point(position[0], position[1])
        else:
            key_mouse_manager.click_point(position[0], position[1], box=box)
