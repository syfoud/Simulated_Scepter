import threading
import time

import pyautogui

from tool.diver.config import config

_pressed_keys = set()
_key_lock = threading.Lock()


def get_mapping(x):
    if x in config.origin_key:
        x = config.mapping[config.origin_key.index(x)]
    return x

def keyDown(x):
    key = get_mapping(x)
    with _key_lock:
        _pressed_keys.add(key)
        pyautogui.keyDown(key)


def keyUp(x):
    with _key_lock:
        if config.long_press_sprint and x == 'w':
            shift = get_mapping('shift')
            pyautogui.keyUp(shift)
            _pressed_keys.discard(shift)
        key = get_mapping(x)
        pyautogui.keyUp(key)
        _pressed_keys.discard(key)


def release_pressed_keys():
    """停止直接键盘通道时释放全部已记录的按键。"""
    failures = {}
    with _key_lock:
        for key in tuple(_pressed_keys):
            try:
                pyautogui.keyUp(key)
            except Exception as exc:
                failures[key] = exc
            else:
                _pressed_keys.discard(key)
    return failures

class KeyController:
    def __init__(self, father):
        self.events = []
        self.fff = 0
        self.father = father
        self.thread = threading.Thread(target=self.loop, name="差分键盘控制", daemon=True)
        self.thread.start()

    def join(self):
        if self.thread is not threading.current_thread():
            self.thread.join()

    def loop(self):
        while not self.father._stop:
            if self.fff:
                keyDown('f')
                try:
                    time.sleep(0.02)
                finally:
                    keyUp('f')
            else:
                time.sleep(0.1)
            for event in tuple(self.events):
                if self.father._stop:
                    return
                if event['type']=='down':
                    keyDown(event['key'])
                elif event['type']=='up':
                    keyUp(event['key'])
