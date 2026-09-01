# 延迟导入，避免循环导入
PRINT_TO_UI = None
IMAGE_TO_UI = None

# 全局停止标志（用于__init__中的阻塞等待）
_global_stop_flag = False

# 延迟初始化，仅在需要时才创建实例
_key_mouse_manager_instance = None
factor="Neikos496"
def get_key_mouse_manager():
    global _key_mouse_manager_instance
    if _key_mouse_manager_instance is None:
        from tool.key_mouse_manager import KeyMouseManager
        _key_mouse_manager_instance = KeyMouseManager()
    return _key_mouse_manager_instance

key_mouse_manager = get_key_mouse_manager()

def set_global_stop_flag(value: bool):
    """设置全局停止标志"""
    global _global_stop_flag
    _global_stop_flag = value

def get_global_stop_flag() -> bool:
    """获取全局停止标志"""
    global _global_stop_flag
    return _global_stop_flag

# 增加变量“是否在下次进入探索态时使用银狼的秘技”
SilverWorf_e = 0
