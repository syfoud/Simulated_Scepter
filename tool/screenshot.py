import ctypes
import time
from ctypes import Structure
from ctypes.wintypes import DWORD, LONG, WORD
from threading import Lock

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
    def __init__(self,w=1920,h=1080):
        self.gdi = ctypes.WinDLL("gdi32")
        self.srcdc  = ctypes.WinDLL("user32").GetWindowDC(0)
        self.memdc = self.gdi.CreateCompatibleDC(self.srcdc)
        self.width, self.height = w, h
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
        self.bmp = self.gdi.CreateCompatibleBitmap(self.srcdc, self.width, self.height)
        self.gdi.SelectObject(self.memdc, self.bmp)

    def grab(self, x, y):
        with lock:
            for attempt in range(10):
                try:
                    self.gdi.BitBlt(self.memdc, 0, 0, self.width, self.height, self.srcdc, x, y, 0x40CC0020)
                    bits = self.gdi.GetDIBits(self.memdc, self.bmp, 0, self.height, self.data, self.bmi, 0)
                    if bits != self.height:
                        CUS_LOGGER.warning(f'截图失败！第{attempt + 1}次尝试')
                        time.sleep(0.05)
                        continue
                    return np.frombuffer(bytearray(self.data), dtype=np.uint8).reshape((self.height,self.width,4))[:,:,:3]
                except Exception as e:
                    CUS_LOGGER.warning(f'截图过程中发生异常: {e}, 第{attempt + 1}次尝试')
                    time.sleep(0.05)
                    continue
        CUS_LOGGER.error('截图失败！已达到最大重试次数')
        return np.zeros((self.height,self.width,3), dtype=np.uint8)
