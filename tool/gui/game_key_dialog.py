"""游戏内键位设置窗口：逐项捕获新按键，返回后由主窗口的「保存快捷键设置」统一落盘。"""

from pathlib import Path

from PyQt5 import uic
from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QSizePolicy

from route import PATHS
from tool.key_mouse_manager import is_valid_key_name, normalize_key_name

# 与游戏内「设置-按键说明」逐项对应：(界面文案, 游戏键位逻辑名, 游戏内固定的物理键)。
# 逻辑名就是配置文件 game_keys 的字段名；第三项非 None 表示该键游戏内不可改，
# 只用于界面展示，不写进配置表。
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

GAME_KEY_LABELS = {name: label for label, name, _fixed in GAME_KEY_ROWS if name}

# 界面展示用的键名：左右修饰键分开写，避免用户以为设的是"任意 Ctrl"
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
    # 下面这些键游戏内不让绑，但程序热键可以录，展示时用各自的常用写法
    "tab": "Tab",
    "capslock": "CapsLock",
    "pause": "Pause",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "end": "End",
    "home": "Home",
    "insert": "Insert",
    "delete": "Delete",
    "printscreen": "PrintScreen",
    "numlock": "NumLock",
    "scrolllock": "ScrollLock",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}

# 修饰键只看扫描码：Qt 的 nativeVirtualKey 分不出左右（Shift/Ctrl/Alt 都是 0x10/0x11/0x12），
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

# 编辑键/扩展键的虚拟键码。游戏内键位不允许绑这些键，但程序热键可以，
# 所以录键逻辑认识它们，具体能不能用由各自的校验器决定。
_EXTENDED_KEY_NAMES = {
    0x09: "tab",
    0x13: "pause",
    0x14: "capslock",
    0x21: "pageup",
    0x22: "pagedown",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2C: "printscreen",
    0x2D: "insert",
    0x2E: "delete",
    0x90: "numlock",
    0x91: "scrolllock",
}

# 高亮只用背景色：边框属于盒模型，加边框会改变输入框的尺寸建议，
# 进入/退出录制时整行会跟着上下跳几像素。
_CAPTURE_STYLE = "QLineEdit { background-color: #d9e8ff; }"
_CAPTURE_PLACEHOLDER = "请按下新按键"
_INVALID_KEY_PLACEHOLDER = "该按键不可用，请重新按下"


def display_key_name(name):
    """把物理键名转成界面文案；F5、Q 这类单键显示为大写。"""
    normalized = normalize_key_name(str(name or ""))
    if not normalized:
        return ""
    return _DISPLAY_NAMES.get(normalized) or normalized.upper()


_QT_EXTENDED_KEYS = {
    Qt.Key_Pause: 0x13,
    Qt.Key_CapsLock: 0x14,
    Qt.Key_PageUp: 0x21,
    Qt.Key_PageDown: 0x22,
    Qt.Key_End: 0x23,
    Qt.Key_Home: 0x24,
    Qt.Key_Left: 0x25,
    Qt.Key_Up: 0x26,
    Qt.Key_Right: 0x27,
    Qt.Key_Down: 0x28,
    Qt.Key_Print: 0x2C,
    Qt.Key_Insert: 0x2D,
    Qt.Key_Delete: 0x2E,
    Qt.Key_NumLock: 0x90,
    Qt.Key_ScrollLock: 0x91,
}


def _qt_key_to_virtual_key(key):
    """把 Qt 键码换算成 Windows 虚拟键码；只覆盖可录制范围内的键，其余返回 0。

    真实输入有 nativeVirtualKey，用不到这个换算；Qt 自己构造的 QKeyEvent
    （自动化测试）没有原生键码，只能从 key() 反推。
    """
    if Qt.Key_A <= key <= Qt.Key_Z:
        return key
    if Qt.Key_0 <= key <= Qt.Key_9:
        return key
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return 0x70 + (key - Qt.Key_F1)
    if key == Qt.Key_Space:
        return 0x20
    if key == Qt.Key_Tab:
        # Tab 在实时输入里本来就有 nativeVirtualKey，这里只是让自动化测试构造的事件也能反推出 tab
        return 0x09
    if key in (Qt.Key_Return, Qt.Key_Enter):
        return 0x0D
    return _QT_EXTENDED_KEYS.get(key, 0)


def _event_key_name(event):
    """从按键事件里取出物理键名，取不到（不在可设范围内）时返回空串。"""
    virtual_key = event.nativeVirtualKey() or _qt_key_to_virtual_key(event.key())
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
    return _EXTENDED_KEY_NAMES.get(virtual_key, "")


class KeyCapture(QObject):
    """给一个只读 QLineEdit 装上"单键捕获"行为，键位窗口与主窗口共用同一套交互。

    交互约定：点击输入框即清空并进入等待状态，按下第一个可识别的键就录入并立即结束捕获；
    捕获期间点走焦点、窗口失活或按 Esc 都算取消，恢复进入捕获前的内容。

    用事件过滤器而不是继承 QLineEdit，是为了让主窗口里已有的程序热键输入框
    不必在 .ui 里换控件类型，两处行为也天然一致。
    """

    # 进入/退出捕获状态，主窗口据此暂停全局热键，否则录 F5 会直接触发"停止任务"
    capture_state_changed = pyqtSignal(bool)
    key_changed = pyqtSignal(str)

    def __init__(self, edit, allow_empty=False, validator=None, allow_tab=False):
        super().__init__(edit)
        self.edit = edit
        self.allow_empty = allow_empty
        # 校验器决定"能录哪些键"：游戏内键位只接受游戏支持的键，
        # 程序热键不传校验器（End、Pause 这些游戏不让设的键程序可以用）
        self.validator = validator
        # 只有程序热键允许录 Tab：游戏内没有 Tab 这一项，且 Tab 是焦点切换键，
        # 游戏键位框里让 Tab 继续切焦点比录进去更有用
        self.allow_tab = allow_tab
        self.key_name = ""
        self._capturing = False
        self._app_filter_installed = False
        # 录制态会临时改成左对齐，退出时按这里记下的原对齐恢复
        self._idle_alignment = edit.alignment()
        edit.installEventFilter(self)
        edit.setReadOnly(True)
        # 输入法会把修饰键吞成 VK_PROCESSKEY，抓键期间必须绕过输入法
        edit.setAttribute(Qt.WA_InputMethodEnabled, False)

    def set_key_name(self, name):
        self.key_name = normalize_key_name(str(name)) if name else ""
        self._refresh_text()
        if not self._capturing:
            # 程序热键允许留空表示不使用，空框要让用户看出是"未设置"而不是没填
            self.edit.setPlaceholderText("未设置" if self.allow_empty else "")

    def is_capturing(self):
        return self._capturing

    def begin_capture(self):
        if self._capturing or not self.edit.isEnabled():
            return
        self._capturing = True
        self.edit.clear()
        # Qt 5.15 在"有焦点 + 居中对齐"的空 QLineEdit 上不画占位提示（实测），
        # 而录制态必然有焦点，居中会让"请按下新按键/该按键不可用"整句看不见，
        # 所以录制期间改成左对齐，提示才画得出来
        self.edit.setAlignment(Qt.AlignLeft)
        self.edit.setPlaceholderText(_CAPTURE_PLACEHOLDER)
        self.edit.setStyleSheet(_CAPTURE_STYLE)
        self._install_app_filter()
        self.capture_state_changed.emit(True)

    def cancel_capture(self):
        """放弃本次捕获，恢复进入捕获前的值。"""
        if not self._capturing:
            return
        self._capturing = False
        self._restore_idle_style()
        self.capture_state_changed.emit(False)

    def _install_app_filter(self):
        """捕获期间挂到应用上监听点击，用来发现"点到了别处"。

        只有点进另一个可获焦控件才会收到 FocusOut；点标签、点窗口空白处都不会，
        不额外监听的话框会一直停在等待按键的状态，用户之后随手按一个键就被改掉了。
        """
        if self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._app_filter_installed = True

    def _remove_app_filter(self):
        if not self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._app_filter_installed = False

    def _restore_idle_style(self):
        self._remove_app_filter()
        self._refresh_text()
        self.edit.setAlignment(self._idle_alignment)
        self.edit.setPlaceholderText("未设置" if self.allow_empty else "")
        self.edit.setStyleSheet("")

    def _commit(self, name):
        self.key_name = normalize_key_name(name) if name else ""
        self._capturing = False
        self._restore_idle_style()
        self.capture_state_changed.emit(False)
        self.key_changed.emit(self.key_name)

    def _refresh_text(self):
        self.edit.setText(display_key_name(self.key_name) if self.key_name else "")

    def eventFilter(self, obj, event):
        if obj is not self.edit:
            # 应用级过滤器只用来发现捕获期间点到了别的地方，点自己由下面处理
            if (self._capturing and obj is not self.edit
                    and event.type() == QEvent.MouseButtonPress):
                self.cancel_capture()
            return False
        event_type = event.type()
        if event_type == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.edit.setFocus()
                self.begin_capture()
            # 吞掉点击：只读输入框不需要自己处理选中与光标
            return True
        if event_type == QEvent.FocusIn:
            self.begin_capture()
            return False
        if event_type == QEvent.FocusOut:
            self.cancel_capture()
            return False
        if event_type == QEvent.KeyPress:
            return self._handle_key(event)
        return False

    def _handle_key(self, event):
        """录键期间收到第一个可识别的键就结束捕获，之后按键不再改动这个框。"""
        if event.isAutoRepeat():
            return True
        if not self._capturing:
            # 没在录键时让 Tab 继续做焦点切换；其余键吞掉，避免 Enter 触发默认按钮、Esc 关窗口
            return event.key() != Qt.Key_Tab
        if event.key() == Qt.Key_Escape:
            self.cancel_capture()
            return True
        if event.key() == Qt.Key_Tab and not self.allow_tab:
            # Tab 是焦点切换键，游戏键位里也没有这一项：放行让焦点切到下一个控件
            self.cancel_capture()
            return False
        if self.allow_empty and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._commit("")
            return True
        name = _event_key_name(event)
        if not name or (self.validator is not None and not self.validator(name)):
            # 识别不出的键（符号键等）与游戏内不让绑的键都停在等待状态并说明原因，
            # 否则框里一直显示"请按下新按键"，用户会以为没录上
            self.edit.setPlaceholderText(_INVALID_KEY_PLACEHOLDER)
            return True
        self._commit(name)
        return True


class GameKeyDialog(QDialog):
    """游戏内键位设置窗口。

    这里只维护"待保存"的键位表，不写任何配置文件；用户点「返回」后由主窗口的
    「保存快捷键设置」把游戏内键位与程序热键一起落盘，避免只保存一半。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(str(Path(PATHS["ui"]) / "GameKeybinding.ui"), self)
        if parent is not None:
            # 主界面的 qss 挂在 MainFrame 上，顶层窗口不会自动继承
            self.setStyleSheet(parent.styleSheet())
            self.setFont(parent.font())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._captures = {}
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
            print(f"读取默认键位配置失败：{error}")
            self._defaults = {}
        try:
            self._current = (load_settings() or {}).get("game_keys") or {}
        except (OSError, ValueError) as error:
            print(f"读取键位配置失败：{error}")
            self._current = {}

    def _build_rows(self):
        for label_text, key_name, fixed_key in GAME_KEY_ROWS:
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setMinimumWidth(140)
            row.addWidget(label)

            edit = QLineEdit()
            edit.setMinimumWidth(180)
            edit.setAlignment(Qt.AlignCenter)
            # 录制提示最长的一句是"该按键不可用，请重新按下"，固定 180px 会被截成
            # "该按键不可用，请重…"，让输入框吃掉行内剩余宽度才放得下整句
            edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            if key_name is None:
                edit.setReadOnly(True)
                edit.setText(display_key_name(fixed_key))
                edit.setEnabled(False)
                edit.setToolTip("游戏内固定按键，不可修改")
                edit.setAttribute(Qt.WA_InputMethodEnabled, False)
            else:
                capture = KeyCapture(edit, validator=is_valid_key_name)
                value = self._current.get(key_name) or self._defaults.get(key_name) or ""
                if value and not is_valid_key_name(value):
                    value = self._defaults.get(key_name, "")
                capture.set_key_name(value)
                edit.setToolTip("点击后按下新按键即可修改")
                self._captures[key_name] = capture

            row.addWidget(edit)
            self.rows_layout.addLayout(row)

    def restore_defaults(self):
        """把可改项全部恢复成默认键；仍需点击主窗口的保存才写入配置。"""
        for key_name, capture in self._captures.items():
            capture.set_key_name(self._defaults.get(key_name, ""))

    def game_keys(self):
        """返回待保存的完整键位表（逻辑名 → 物理键）。"""
        return {name: capture.key_name for name, capture in self._captures.items()}

    def mousePressEvent(self, event):
        # 点在窗口空白/标签上不会转移焦点，这里主动结束捕获，效果等同"点了别处就恢复"
        for capture in self._captures.values():
            capture.cancel_capture()
        super().mousePressEvent(event)

    def changeEvent(self, event):
        # 切到其他窗口时 Qt 不会给焦点控件发 FocusOut，抓键框会一直停在等待状态
        if event.type() == QEvent.WindowDeactivate:
            for capture in self._captures.values():
                capture.cancel_capture()
        super().changeEvent(event)
