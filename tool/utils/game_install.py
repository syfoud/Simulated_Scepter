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


def find_star_rail_executable() -> tuple[str, bool] | None:
    """按国服优先、国际服其次的顺序发现游戏，结果包含是否为国际服。"""
    candidates = (
        _mihoyo_launcher_candidates()
        + _hoyoplay_candidates()
        + _game_config_store_candidates()
        + _registry_candidates()
    )

    # 启动器来源能确定服务器时先按服务器顺序检查；历史记录只作为无法判断服务器的兜底。
    for is_global in (False, True, None):
        for candidate, region in candidates:
            if region is not is_global:
                continue
            if candidate.is_file() and candidate.name.casefold() == "starrail.exe":
                return str(candidate.resolve()), bool(is_global)
    return None


def is_global_star_rail_executable(game_path: str) -> bool:
    """根据游戏配置判断指定的 StarRail.exe 是否为国际服。"""
    return _path_region(Path(game_path)) is True


def _registry_candidates() -> list[tuple[Path, bool | None]]:
    """提取 Windows 最近使用记录中的 StarRail.exe 完整路径。"""
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
                                path = Path(value[:position + len("starrail.exe")])
                                candidates.append((path, _path_region(path)))
        except OSError:
            continue
    return candidates


def _game_config_store_candidates() -> list[tuple[Path, bool | None]]:
    """读取 Windows 游戏配置记录中的已匹配可执行文件路径。"""
    import winreg

    candidates = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"System\GameConfigStore\Children",
            0,
            winreg.KEY_READ,
        ) as root:
            child_names = [
                winreg.EnumKey(root, index)
                for index in range(winreg.QueryInfoKey(root)[0])
            ]
    except OSError:
        return candidates

    for child_name in child_names:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                rf"System\GameConfigStore\Children\{child_name}",
                0,
                winreg.KEY_READ,
            ) as child:
                matched_path = _registry_value(child, "MatchedExeFullPath")
        except OSError:
            continue
        if not matched_path:
            continue
        position = matched_path.casefold().find("starrail.exe")
        if position >= 0:
            game_path = Path(matched_path[:position + len("starrail.exe")])
            candidates.append((game_path, _path_region(game_path)))
    return candidates


def _hoyoplay_candidates() -> list[tuple[Path, bool | None]]:
    """读取 HoYoPlay 的游戏数据文件，解析安装目录和服务器标识。"""
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
        region = _game_region(data)
        for match in install_path_pattern.finditer(data):
            try:
                install_paths.append((Path(json.loads(f'"{match.group(1)}"')), region))
            except (json.JSONDecodeError, OSError):
                continue

    candidates = []
    for install_path, region in install_paths:
        candidates.extend((path, region) for path in (
            install_path / "StarRail.exe",
            install_path / "Games" / "StarRail.exe",
        ))
    return candidates


def _mihoyo_launcher_candidates() -> list[tuple[Path, bool | None]]:
    """从米哈游启动器卸载项和固定游戏目录中发现官方客户端。"""
    try:
        import winreg
    except ImportError:
        return []

    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    candidates = []
    installed_regions = set()
    for hive, root_path in uninstall_roots:
        try:
            with winreg.OpenKey(hive, root_path, 0, winreg.KEY_READ) as root:
                subkeys = [winreg.EnumKey(root, index) for index in range(winreg.QueryInfoKey(root)[0])]
        except OSError:
            continue

        for subkey_name in subkeys:
            if not subkey_name.casefold().startswith("hkrpg_"):
                continue
            is_global = "_global" in subkey_name.casefold()
            installed_regions.add(is_global)
            try:
                with winreg.OpenKey(hive, root_path + "\\" + subkey_name, 0, winreg.KEY_READ) as key:
                    install_path = _registry_value(key, "InstallLocation")
                    icon_path = _registry_value(key, "DisplayIcon")
                    uninstall = _registry_value(key, "UninstallString")
            except OSError:
                continue

            # 卸载项常把 InstallLocation 指向启动器本身；仅从它的固定游戏子目录尝试，
            # 不把启动器目录误当成游戏，也不递归扫描磁盘。
            launcher_root = Path(install_path) if install_path else None
            for root in (launcher_root,):
                if root is None:
                    continue
                for game_dir in (
                    root / "games" / "Star Rail Game",
                    root / "games" / "Star Rail Games",
                    root / "games" / "Star Rail" / "Game",
                ):
                    candidates.append((game_dir / "StarRail.exe", is_global))

            # 部分卸载记录直接指向游戏目录；路径必须明确包含对应服务器标记。
            for value in (install_path, icon_path, uninstall):
                if not value:
                    continue
                position = value.casefold().find("starrail.exe")
                if position >= 0:
                    candidates.append((Path(value[:position + len("starrail.exe")]), is_global))
    if len(installed_regions) == 1:
        installed_region = installed_regions.pop()
        candidates.extend(
            (path, installed_region)
            for path, region in _registry_candidates()
            if region is None
        )

    # 旧版启动器常见目录是“磁盘根目录\Star Rail\Game”；只检查固定位置，不遍历磁盘。
    import ctypes

    drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
    for drive_number in range(26):
        if drive_mask & (1 << drive_number):
            game_path = Path(f"{chr(ord('A') + drive_number)}:\\") / "Star Rail" / "Game" / "StarRail.exe"
            candidates.append((game_path, _path_region(game_path)))
    return candidates


def _registry_value(key, name: str) -> str:
    import winreg

    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return value if isinstance(value, str) else ""


def _game_region(data: str) -> bool | None:
    lowered = data.casefold()
    if "hkrpg_cn" in lowered:
        return False
    if "hkrpg_global" in lowered:
        return True
    return None


def _path_region(game_path: Path) -> bool | None:
    """从游戏配置或路径中的客户端标识识别服务器。"""
    lowered_path = str(game_path).casefold()
    if "hkrpg_cn" in lowered_path:
        return False
    if "hkrpg_global" in lowered_path:
        return True

    config_path = game_path.parent / "config.ini"
    try:
        return _game_region(config_path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None
