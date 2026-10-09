"""本地崩坏：星穹铁道安装路径发现。"""

import json
import os
import re
from pathlib import Path

REGISTRY_KEYS = (
    ("HKEY_CLASSES_ROOT", r"Local Settings\Software\Microsoft\Windows\Shell\MuiCache"),
    ("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage\AppSwitched"),
    ("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage\ShowJumpView"),
)


def find_star_rail_executable() -> str | None:
    """从 Windows 最近使用记录和 HoYoPlay 配置中寻找有效的 StarRail.exe。"""
    candidates = _hoyoplay_candidates() + _registry_candidates()
    for candidate in candidates:
        if candidate.is_file() and candidate.name.casefold() == "starrail.exe":
            return str(candidate.resolve())
    return None


def _registry_candidates() -> list[Path]:
    """提取注册表中记录的 StarRail.exe 完整路径。"""
    import winreg

    registry_roots = {
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    }
    candidates = []
    for root_name, subkey in REGISTRY_KEYS:
        try:
            with winreg.OpenKey(registry_roots[root_name], subkey, 0, winreg.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        value_name, value_data, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    for value in (value_name, value_data):
                        if isinstance(value, str):
                            position = value.casefold().find("starrail.exe")
                            if position >= 0:
                                candidates.append(Path(value[:position + len("starrail.exe")]))
        except OSError:
            continue
    return candidates


def _hoyoplay_candidates() -> list[Path]:
    """读取 HoYoPlay 的游戏数据文件，解析其安装目录记录。"""
    app_data = os.environ.get("APPDATA")
    if not app_data:
        return []

    hoyoplay_dir = Path(app_data) / "Cognosphere" / "HYP"
    if not hoyoplay_dir.is_dir():
        return []

    install_paths = []
    install_path_pattern = re.compile(
        r'"(?:installPath|persistentInstallPath)"\s*:\s*"([^\"]+)"',
        re.IGNORECASE,
    )
    for data_path in hoyoplay_dir.rglob("gamedata.dat"):
        try:
            data = data_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in install_path_pattern.finditer(data):
            try:
                install_paths.append(Path(json.loads(f'"{match.group(1)}"')))
            except (json.JSONDecodeError, OSError):
                continue

    candidates = []
    for install_path in install_paths:
        candidates.extend((install_path / "StarRail.exe", install_path / "Games" / "StarRail.exe"))
    return candidates
