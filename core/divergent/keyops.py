import threading
import time

import pyautogui

from core.divergent.config import config
from tool.key_mouse_manager import resolve_key


def keyDown(x):
    pyautogui.keyDown(resolve_key(x))


def keyUp(x):
    # 长按加速：走 W 的时候把加速键一并松开，否则会一直处于加速状态
    if config.long_press_sprint and x == 'move_w':
        pyautogui.keyUp(resolve_key('sprint'))
    pyautogui.keyUp(resolve_key(x))


class KeyController:
    def __init__(self, father):
        self.events = []
        self.fff = 0
        self.father = father
        threading.Thread(target=self.loop).start()

    def loop(self):
        while not self.father._stop:
            if self.fff:
                keyDown('interact')
                time.sleep(0.02)
                keyUp('interact')
            else:
                time.sleep(0.1)
            for event in self.events:
                if event['type']=='down':
                    keyDown(event['key'])
                elif event['type']=='up':
                    keyUp(event['key'])
