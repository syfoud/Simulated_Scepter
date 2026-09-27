import ctypes
import time
from ctypes import Structure
from ctypes.wintypes import DWORD, LONG, WORD
from threading import Lock

import cv2
import numpy as np

from tool.log import CUS_LOGGER


class BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]
class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 3)]

lock = Lock()


class Screen:
    def __init__(self,w=1920,h=1080,out_w=None,out_h=None):
        self._lock = lock
        self._closed = False
        self.width, self.height = w, h
        # 输出尺寸：高分辨率窗口（如4K全屏）截取物理像素后缩回识别基准分辨率
        # 注意必须用 cv2.INTER_AREA 缩放：GDI StretchBlt 的滤波会破坏小字号数字的边缘，导致模板匹配失败
        self.out_width = out_w or w
        self.out_height = out_h or h
        self.scaled = (self.out_width, self.out_height) != (self.width, self.height)
        self.bmi = BITMAPINFO()
        self.bmi.bmiHeader.biSize = 40
        self.bmi.bmiHeader.biPlanes = 1
        self.bmi.bmiHeader.biBitCount = 32
        self.bmi.bmiHeader.biCompression = 0
        self.bmi.bmiHeader.biClrUsed = 0
        self.bmi.bmiHeader.biClrImportant = 0
        self.bmi.bmiHeader.biWidth = self.width
        self.bmi.bmiHeader.biHeight = -self.height
        self.data = ctypes.create_string_buffer(self.width * self.height * 4)
        self.gdi = ctypes.WinDLL("gdi32")
        self.user32 = ctypes.WinDLL("user32")
        self.user32.GetWindowDC.argtypes = [ctypes.c_void_p]
        self.user32.GetWindowDC.restype = ctypes.c_void_p
        self.user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        self.gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        self.gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
        self.gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi.SelectObject.restype = ctypes.c_void_p
        self.gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        self.gdi.DeleteObject.restype = ctypes.c_int
        self.gdi.DeleteDC.argtypes = [ctypes.c_void_p]
        self.gdi.DeleteDC.restype = ctypes.c_int
        self.gdi.BitBlt.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, DWORD,
        ]
        self.gdi.BitBlt.restype = ctypes.c_int
        self.gdi.GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, DWORD, DWORD, ctypes.c_void_p,
            ctypes.POINTER(BITMAPINFO), DWORD,
        ]
        self.gdi.GetDIBits.restype = ctypes.c_int

        self.srcdc = None
        self.memdc = None
        self.bmp = None
        self.oldbmp = None
        try:
            self.srcdc = self.user32.GetWindowDC(None)
            if not self.srcdc:
                raise RuntimeError("无法获取屏幕 DC")
            self.memdc = self.gdi.CreateCompatibleDC(self.srcdc)
            if not self.memdc:
                raise RuntimeError("无法创建截图 DC")
            self.bmp = self.gdi.CreateCompatibleBitmap(self.srcdc, self.width, self.height)
            if not self.bmp:
                raise RuntimeError("无法创建截图位图")
            self.oldbmp = self.gdi.SelectObject(self.memdc, self.bmp)
            if not self.oldbmp or self.oldbmp == ctypes.c_void_p(-1).value:
                self.oldbmp = None
                raise RuntimeError("无法选择截图位图")
        except Exception:
            self.close()
            raise

    def grab(self, x, y):
        with self._lock:
            if self._closed or self.srcdc is None:
                raise RuntimeError("截图器已关闭")
            for attempt in range(10):
                bits = 0
                if not self.gdi.BitBlt(self.memdc, 0, 0, self.width, self.height, self.srcdc, x, y, 0x40CC0020):
                    reason = "BitBlt 返回 0"
                else:
                    # GetDIBits 要求位图未选入 DC；读取后恢复，以供下一帧 BitBlt。
                    if self.gdi.SelectObject(self.memdc, self.oldbmp) != self.bmp:
                        self._closed = True
                        raise RuntimeError("无法从截图 DC 取消选择位图")
                    try:
                        bits = self.gdi.GetDIBits(self.memdc, self.bmp, 0, self.height, self.data, ctypes.byref(self.bmi), 0)
                    finally:
                        if self.gdi.SelectObject(self.memdc, self.bmp) != self.oldbmp:
                            self._closed = True
                            raise RuntimeError("无法恢复截图 DC 的位图")
                    reason = f"GetDIBits 返回 {bits} 行，期望 {self.height} 行"
                if bits == self.height:
                    # 输出图像必须独立于下一次 GDI 写入；先缩放 BGRA 再转换可少复制一张 4K 图。
                    frame = np.frombuffer(self.data, dtype=np.uint8).reshape((self.height, self.width, 4))
                    if self.scaled:
                        frame = cv2.resize(frame, (self.out_width, self.out_height), interpolation=cv2.INTER_AREA)
                    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                CUS_LOGGER.debug("截图重试 reason=%s attempt=%s region=%s", reason, attempt + 1, (x, y, self.width, self.height))
                if attempt < 9:
                    time.sleep(0.05)
            raise RuntimeError(f"截图失败，已重试 10 次：{reason}，区域={(x, y, self.width, self.height)}")

    def close(self):
        """释放截图 DC 和位图；重复调用会重试之前未释放的资源。"""
        with self._lock:
            self._closed = True
            failures = []
            restored = True
            if self.memdc and self.oldbmp:
                previous = self.gdi.SelectObject(self.memdc, self.oldbmp)
                # grab 恢复失败时原位图可能已在 DC 中；成功返回它仍可安全释放截图位图。
                if not previous or previous == ctypes.c_void_p(-1).value:
                    failures.append("恢复原位图")
                    restored = False
                else:
                    self.oldbmp = None
            if self.bmp and restored:
                if not self.gdi.DeleteObject(self.bmp):
                    failures.append("删除截图位图")
                else:
                    self.bmp = None
            if self.memdc and restored:
                if not self.gdi.DeleteDC(self.memdc):
                    failures.append("删除截图 DC")
                else:
                    self.memdc = None
            if self.srcdc:
                if not self.user32.ReleaseDC(None, self.srcdc):
                    failures.append("释放屏幕 DC")
                else:
                    self.srcdc = None
            if failures:
                CUS_LOGGER.error(
                    "截图资源清理失败：%s srcdc=%s memdc=%s bitmap=%s",
                    '、'.join(failures), self.srcdc, self.memdc, self.bmp,
                )

    def __del__(self):
        if any(getattr(self, name, None) for name in ("srcdc", "memdc", "bmp")):
            self.close()
