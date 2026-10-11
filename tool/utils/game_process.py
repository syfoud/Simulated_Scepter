"""本地崩坏：星穹铁道进程检测。"""

import ctypes
from ctypes import wintypes


class GameProcessEntry(ctypes.Structure):
    """Windows 进程快照中的进程条目。"""

    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    )


def is_star_rail_process_running() -> bool:
    """不依赖窗口是否可见，检查本机进程列表中是否有 StarRail.exe。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(GameProcessEntry))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(GameProcessEntry))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        process = GameProcessEntry()
        process.dwSize = ctypes.sizeof(process)
        has_process = kernel32.Process32FirstW(snapshot, ctypes.byref(process))
        while has_process:
            if process.szExeFile.casefold() == "starrail.exe":
                return True
            has_process = kernel32.Process32NextW(snapshot, ctypes.byref(process))
        return False
    finally:
        kernel32.CloseHandle(snapshot)
