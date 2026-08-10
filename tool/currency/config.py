import sys

from route import PATHS


class Config:
    def __init__(self):
        self.abspath = PATHS["config"]+"//config"
        if getattr(sys, 'frozen', False):
            self.abspath = './config/config'
        self.order_text = "1 2 3 4"
        self.angle = "1.0"
        self.difficult = "5"
        self.allow_difficult = [1, 2, 3, 4, 5]
        self.text = "info_old.yml"
        self.fate = "巡猎"
        self.map_sha = ""
        self.fates = ["存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"]
        self.show_map_mode = 0
        self.debug_mode = 0
        self.speed_mode = 0
        self.long_press_sprint = 0
        self.use_consumable = 0
        self.slow_mode = 0
        self.force_update = 0
        self.unlock = 0
        self.bonus = 0
        self.timezones = ['America', 'Asia', 'Europe', 'Default']
        self.timezone = 'Default'
        self.origin_key = ['f','m','shift','v','e','w','a','s','d','1','2','3','4']
        self.mapping = self.origin_key
        self.max_run = 34

    @property
    def multi(self) -> float:
        x = float(self.angle)
        if x > 5:
            self.angle = '1.0'
            return 1.0
        elif x > 2:
            return x - 2
        else:
            return x

    @property
    def order(self) -> list[int]:
        return [int(i) for i in self.order_text.strip(" ").split(" ")]

    @property
    def diffi(self) -> int:
        return int(self.difficult) if int(self.difficult) in self.allow_difficult else 1

config = Config()
