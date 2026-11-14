"""日常内核入口：继承通用内核，具体流程待补充。"""

from core.common.runtime import ScriptKernel
from tool.GLOBAL import key_mouse_manager


class DailyKernel(ScriptKernel):
    """日常任务内核。

    继承通用内核的窗口识别、截图、OCR 与 JSON 动作分发；日常流程待补充。
    """

    def esc_end(self):
        key_mouse_manager.press("esc")
        key_mouse_manager.wait()
        self.stop()


def create_engine(*, script=False):
    return DailyKernel()
