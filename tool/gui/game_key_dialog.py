"""游戏内键位设置窗口：逐项捕获新按键，返回后由主窗口的「保存快捷键设置」统一落盘。"""

from pathlib import Path

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit

from route import PATHS
from tool.key_mouse_manager import is_valid_key_name, normalize_key_name

# 与游戏内「设置-按键说明」的页面顺序、文案逐项对应，逻辑名与 game_keys 字段同名。
# 第三项为该键的固定物理键（游戏内不可修改），此时不进入配置表。
GAME_KEY_ROWS = (
    ("呼出鼠标", None, "altleft"),
    ("角色菜单", "character", None),
    ("编队", "team_setup", None),
    ("导航", "map", None),
    ("背包", "inventory", None),
    ("任务", "mission", None),
    ("教学目录", "tutorial", None),
    ("活动", "travellog", None),
    ("无名勋礼", "nameless_honor", None),
    ("跃迁", "warp", None),
    ("星际和平指南", "interastral_peace_guide", None),
    ("商店", "shop", None),
    ("加速跑", "sprint", None),
    ("行走", "walk", None),
    ("新手提示", "tutorial_hints", None),
    ("交互", "interact", None),
    ("短信通知", "messages", None),
    ("追踪任务", "track_mission", None),
    ("聊天对话", "chat", None),
    ("秘技", "technique", None),
    ("迷宫玩法重置", "reset", None),
    ("任务道具", "quest_item", None),
    ("玩法交互", "gameplay_interaction", None),
    ("手机/退出", None, "esc"),
    ("切换角色1", "role_1", None),
    ("切换角色2", "role_2", None),
    ("切换角色3", "role_3", None),
    ("切换角色4", "role_4", None),
    ("角色移动-前", "move_w", None),
    ("角色移动-后", "move_s", None),
    ("角色移动-左", "move_a", None),
    ("角色移动-右", "move_d", None),
)

# 逻辑名→界面文案，保存失败时用于提示具体是哪一项不合法。
GAME_KEY_LABELS = {name: label for label, name, _fixed in GAME_KEY_ROWS if name}

# 物理键名→界面展示文案。裸修饰键在游戏里显示为 LeftShift/Ctrl 这类写法，
# 这里按游戏习惯展示左右，避免用户误以为是"任意 Ctrl"。
_DISPLAY_NAMES = {
    "space": "空格",
    "enter": "Enter",
    "esc": "Esc",
    "ctrlleft": "Ctrl",
    "ctrlright": "RightCtrl",
    "shiftleft": "LeftShift",
    "shiftright": "RightShift",
    "altleft": "LeftAlt",
    "altright": "RightAlt",
}

# Qt 的 nativeVirtualKey 分不出左右修饰键（Shift/Ctrl/Alt 的 VK 都是 0x10/0x11/0x12），
# 只有扫描码带左右信息，扩展键的 0x100 位由 Qt 折算进 nativeScanCode。
_MODIFIER_SCAN_CODES = {
    0x2A: "shiftleft",
    0x36: "shiftright",
    0x136: "shiftright",
    0x1D: "ctrlleft",
    0x11D: "ctrlright",
    0x38: "altleft",
    0x138: "altright",
}


def display_key_name(name):
    """把物理键名转成界面展示文案。"""
    name = normalize_key_name(name)
    return _DISPLAY_NAMES.get(name) or name.upper()


def _event_key_name(event):
    """从按键事件取出 pyautogui 键名；不在允许范围内时返回空串。"""
    virtual_key = event.nativeVirtualKey()
    if virtual_key in (0x10, 0x11, 0x12):
        return _MODIFIER_SCAN_CODES.get(event.nativeScanCode() & 0x1FF, "")
    if 0x41 <= virtual_key <= 0x5A:
        return chr(virtual_key).lower()
    if 0x30 <= virtual_key <= 0x39:
        return chr(virtual_key)
    if 0x70 <= virtual_key <= 0x87:
        return f"f{virtual_key - 0x6F}"
    if virtual_key == 0x20:
        return "space"
    if virtual_key == 0x0D:
        return "enter"
    return ""


class KeyCaptureEdit(QLineEdit):
    """只接受单键的输入框：按下什么就显示什么，不接受手输。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key_name = ""
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        # 输入法会把修饰键吞成 VK_PROCESSKEY，捕获时必须关掉
        self.setAttribute(Qt.WA_InputMethodEnabled, False)

    def set_key_name(self, name):
        self.key_name = normalize_key_name(name) if name else ""
        self.setText(display_key_name(self.key_name) if self.key_name else "")

    def keyPressEvent(self, event):
        # 长按产生的重复事件会让按键反复刷新，忽略掉
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key_Escape:
            # Esc 是游戏内固定的"手机/退出"，这里只当作取消本次输入，不关闭窗口
            event.accept()
            return
        name = _event_key_name(event)
        if name:
            self.set_key_name(name)
        event.accept()


class GameKeyDialog(QDialog):
    """
    自定义游戏内键位窗口

    窗口内只维护"待保存"的键位表，不写配置文件；返回后由主窗口在用户点击
    「保存快捷键设置」时与程序热键一起落盘，保证两处设置同时生效。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(str(Path(PATHS["ui"]) / "GameKeybinding.ui"), self)
        if parent is not None:
            # 主界面的 qss 挂在 MainFrame 上，顶层窗口不会自动继承，必须手动复制
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._edits = {}
        self._defaults = {}
        self._current = {}
        self._load_keys()
        self._build_rows()

        self.restore_default_btn.clicked.connect(self.restore_defaults)
        self.back_btn.clicked.connect(self.accept)
        available = self.screen().availableGeometry()
        self.resize(min(560, available.width() - 80), min(760, available.height() - 100))

    def _load_keys(self):
        from tool.settings import load_default_settings, load_settings

        try:
            self._defaults = (load_default_settings() or {}).get("game_keys") or {}
        except (OSError, ValueError) as error:
            self._defaults = {}
            print(f"读取默认键位配置失败：{error}")
        try:
            self._current = (load_settings() or {}).get("game_keys") or {}
        except (OSError, ValueError) as error:
            self._current = {}
            print(f"读取键位配置失败：{error}")

    def _build_rows(self):
        for label_text, key_name, fixed_key in GAME_KEY_ROWS:
            row = QHBoxLayout()
            label = QLabel(label_text, self)
            label.setMinimumWidth(140)
            edit = KeyCaptureEdit(self)
            edit.setMinimumWidth(180)
            if key_name is None:
                edit.set_key_name(fixed_key)
                edit.setEnabled(False)
                edit.setToolTip("游戏内固定按键，不可修改")
            else:
                value = self._current.get(key_name) or self._defaults.get(key_name) or ""
                if value and not is_valid_key_name(value):
                    value = self._defaults.get(key_name, "")
                edit.set_key_name(value)
                self._edits[key_name] = edit
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(edit)
            self.rows_layout.addLayout(row)

    def restore_defaults(self):
        """把可修改项恢复成默认键位；返回后仍需点击保存才会写入配置。"""
        for name, edit in self._edits.items():
            edit.set_key_name(self._defaults.get(name, ""))

    def game_keys(self):
        """返回窗口内待保存的完整键位表（逻辑名→物理键）。"""
        return {name: edit.key_name for name, edit in self._edits.items()}
