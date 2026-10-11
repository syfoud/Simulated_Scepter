"""公共工具入口及外部内核包路径初始化。"""

import core
from route import PATHS

# 冻结程序也从发行目录发现模块，新装的模块可从外部 Python 文件加载。
if PATHS["core"] not in core.__path__:
    core.__path__.append(PATHS["core"])
