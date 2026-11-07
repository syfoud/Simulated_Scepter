"""货币战争内核入口：纯 UI + 战斗流程，不涉及大世界寻路。"""

from core.currency.automation import SimulatedCurrency
from tool.log import CUS_LOGGER
from tool.settings import load_settings


class CurrencyWar(SimulatedCurrency):

    def __init__(self):
        self.opt = load_settings()
        CUS_LOGGER.info("开始自动刷取未解锁投资策略")
        super().__init__(debug=self.opt.get("debug", True))


def create_engine(*, script=False):
    return CurrencyWar()
