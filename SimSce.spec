# -*- mode: python ; coding: utf-8 -*-
import ast
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('numpy')

def collect_dynamic_imports(path, variable):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if variable not in names or not isinstance(node.value, ast.Dict):
            continue
        return [v.value for v in node.value.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    raise SystemExit(f'{path} 中找不到 {variable}，打包脚本需要同步更新')

hiddenimports += collect_dynamic_imports('tool/gui/engine_settings.py', 'SETTINGS_MODULES')

a = Analysis(
    ['new_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SimSce',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resource\\logo\\圆角-FetDeathWing-256x-AllSize.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SimSce',
)
