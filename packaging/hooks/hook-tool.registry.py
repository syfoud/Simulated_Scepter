"""收集发现目录中的 Python；模块资源由构建脚本复制到外部 core 目录。"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("core")
