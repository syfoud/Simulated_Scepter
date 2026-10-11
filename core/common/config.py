"""多个内核共用的运行参数，保存于通用内核目录。"""

from tool.storage import load_module_settings, update_module_settings


def load_runtime_settings():
    return load_module_settings(__file__)


def save_runtime_settings(values):
    return update_module_settings(__file__, values)
