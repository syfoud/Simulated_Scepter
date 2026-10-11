"""装载选定的 JSON 脚本，并交由内核自身的运行入口执行。"""

from tool.GLOBAL import get_global_stop_flag
from tool.public_ocr import load_actions


def run_script(engine, json_path):
    """替换内核的动作脚本后启动其主循环，结束或失败时释放运行资源。

    Args:
        engine: 已初始化的游戏内核，提供 start() 主循环及 stop() 清理接口。
        json_path: JSON 动作脚本的路径。
    """
    try:
        engine.default_json = load_actions(json_path)
        if not engine.default_json:
            raise ValueError("动作脚本为空，无法运行")
        engine.default_json_path = json_path
        if get_global_stop_flag():
            return
        engine._stop = False
        # 业务内核在主循环中推进寻路、战斗和状态；不能以 run_static 代替。
        engine.start()
    finally:
        if not engine._stop:
            engine.stop()
