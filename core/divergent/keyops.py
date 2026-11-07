import threading
import time

import pyautogui

from tool.key_mouse_manager import resolve_key


def keyDown(x):
    pyautogui.keyDown(resolve_key(x))


def keyUp(x):
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
