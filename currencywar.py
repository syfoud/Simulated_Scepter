import json
import os
import shutil

from currency import SimulatedCurrency
from route import PATHS
from tool import EXTRA
from tool.log import CUS_LOGGER
from tool.public_ocr import load_actions, merge_text


class CurrencyWar (SimulatedCurrency):

    def __init__ (self):
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                self.opt = json.load(file)
        self.default_json_path = "actions/currencywar.json"
        self.default_json = load_actions (self.default_json_path)
        CUS_LOGGER.info ("开始自动刷取叽米")
        super().__init__(
            find=True,                # 是否寻路，货币战争可能不需要，但必须传
            debug=self.opt.get("debug", True),
            speed=False,             # 是否高速模式
            consumable=False,        # 是否使用消耗品
            slow=False,              # 是否慢速模式
            nums=self.opt.get("max_run_time", 0),
            bonus=False              # 是否领取沉浸奖励
        )

    def check_text_in_box(self, box, target_text):
        """
        在屏幕截图的指定区域进行 OCR，判断 target_text 是否出现
        box: [x1, x2, y1, y2] 像素坐标
        返回 True/False
        """
        if not hasattr(self, 'screen') or self.screen is None:
            return False
        # 裁剪区域
        x1, x2, y1, y2 = box
        roi = self.screen[y1:y2, x1:x2]
        if roi.size == 0:
            return False
        # 调用原项目的 OCR 函数（需要确认实际函数名和参数）
        # 假设存在 tool.public_ocr.ocr_image 返回字符串列表
        from tool.public_ocr import ocr_image
        result = ocr_image(roi)   # 返回格式可能是 list of (text, confidence)
        if result:
            # 如果 result 是字符串列表
            if isinstance(result[0], str):
                text_list = result
            else:
                text_list = [item[0] for item in result]
            merged = merge_text(text_list)
            return target_text in merged
        return False


