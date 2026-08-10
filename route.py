
import os
from pathlib import Path
from time import sleep


def get_root_path():
    my_path = Path(__file__).resolve()  # 该.py所在目录

    for i in range(5):
        if os.path.exists(str(my_path) + "\\LICENSE"):
            return str(my_path)
        else:
            my_path = my_path.parent  # 上一级
    print("呃呃,路径问题... 请终止")
    sleep(10000)


def build_paths(root):
    # 定义一个辅助函数来构建路径
    return {
        "root": root,
        "config": os.path.join(root, "config"),
        "logs": os.path.join(root, "logs"),
        "plugins": os.path.join(root, "plugins"),
        # 资源文件
        "font": os.path.join(root, "resource", "font"),
        "logo": os.path.join(root, "resource", "logo"),
        "model": os.path.join(root, "resource", "model"),
        "image": os.path.join(root, "resource", "imgs"),
        "theme": os.path.join(root, "resource", "theme"),
        "ui": os.path.join(root, "resource", "ui"),
        "db": os.path.join(root, "resource", "db")
    }


# 定义为全局变量 几乎完全是静态导入 可以直接import该变量
PATHS = build_paths(get_root_path())


def ensure_directory_exists(path):
    """检测路径是否存在"""

    # 检查路径是否存在
    if not os.path.exists(path):
        # 如果路径不存在，则创建它
        os.makedirs(path)
        try:
            print(f"路径不存在, 已创建: {path}")
        except UnicodeEncodeError:
            print(f"Path created: {path}")
    else:
        try:
            print(f"路径存在, 检测通过: {path}")
        except UnicodeEncodeError:
            print(f"Path exists: {path}")


def check_paths():
    """检测所有路径是否存在"""
    paths = [
        "\\logs",
    ]
    for path in paths:
        ensure_directory_exists(PATHS["root"] + path)


# 创建所有缺失的目录
check_paths()

if __name__ == '__main__':
    print(PATHS)
