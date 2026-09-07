import json
import os
import shutil

from currency import SimulatedCurrency
from route import PATHS
from tool import EXTRA
from tool.log import CUS_LOGGER


class CurrencyWar (SimulatedCurrency):

    def __init__ (self):
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                self.opt = json.load(file)
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

