"""差分宇宙的 OCR 包装。

通用识别逻辑（文本查找、祝福/奇物分割）统一放在 core.common.ocr，这里只保留两处差异：
识别精度取自差分宇宙自己的 accuracy 配置；find_with_box 默认重新截图。
"""

from core.common.ocr import My_TS as CommonMyTS
from core.divergent.config import config


class My_TS(CommonMyTS):
    """差分宇宙识别器：使用配置里的检测精度，并保持调用方默认重截屏的习惯。"""

    def __init__(self, father=None):
        super().__init__(father=father, det_limit_side_len=config.accuracy)

    def find_with_box(self, box=None, redundancy=10, forward=0, mode=0, re_screen=True):
        return super().find_with_box(
            box=box, redundancy=redundancy, forward=forward, mode=mode, re_screen=re_screen
        )
