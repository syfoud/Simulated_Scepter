import json
import os
import shutil

from core.currency.automation import SimulatedCurrency
from route import PATHS
from tool.settings import load_settings
from core.common.config import load_runtime_settings
from tool.storage import load_module_settings
from tool import EXTRA
from tool.log import CUS_LOGGER


class CurrencyWar (SimulatedCurrency):

    def __init__ (self):
        self.opt = load_settings() | load_runtime_settings()
        CUS_LOGGER.info ("开始自动刷取未解锁投资策略")
        super().__init__(
            find=True,                # 是否寻路，货币战争可能不需要，但必须传
            debug=self.opt.get("debug", True),
            speed=False,             # 是否高速模式
            consumable=False,        # 是否使用消耗品
            slow=False,              # 是否慢速模式
            nums=self.opt.get("max_run_time", 0),
            bonus=False              # 是否领取沉浸奖励
        )



def create_engine(*, script=False):
    return CurrencyWar()
