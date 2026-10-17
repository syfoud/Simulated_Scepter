import json

from tool.storage import config_path, save_json_values


class Config:
    def __init__(self):
        self.order_text = "1 2 3 4"
        self.angle = "1.0"
        self.difficult = "5"
        self.allow_difficult = [1, 2, 3, 4, 5]
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
        self.read()

    @property
    def multi(self) -> float:
        x = float(self.angle)
        if x > 5 or x <= 0:
            self.angle = '1.0'
            return 1.0
        return x

    @property
    def order(self) -> list[int]:
        return [int(i) for i in self.order_text.strip(" ").split(" ")]

    @property
    def diffi(self) -> int:
        return int(self.difficult) if int(self.difficult) in self.allow_difficult else 1

    def read(self):
        """读取用户配置；缺失字段已由存储层按默认配置补齐。"""
        with open(config_path(__file__), encoding="utf-8") as file:
            data = json.load(file)
        config = data["config"]
        self.order_text = " ".join(str(x) for x in config['order_text'])
        self.angle = str(config['angle'])
        self.difficult = config['difficulty']
        self.fate = config['fate']
        self.map_sha = config['map_sha']
        self.show_map_mode = config['show_map_mode']
        self.debug_mode = config['debug_mode']
        self.speed_mode = config['speed_mode']
        self.bonus = config['bonus']
        self.long_press_sprint = config['long_press_sprint']
        self.use_consumable = config['use_consumable']
        self.force_update = config['force_update']
        self.timezone = config['timezone']
        self.slow_mode = config['slow_mode']
        self.max_run = config['max_run']
        self.mapping = data['key_mapping']

    def save(self):
        """保存既有配置项，保留配置中的共享字段。"""
        with open(config_path(__file__), encoding="utf-8") as file:
            data = json.load(file)
        save_json_values(__file__, {
                "config": {
                    "order_text": list(map(lambda x: int(x), self.order_text.split(' '))),
                    "angle": float(self.angle),
                    "difficulty": self.diffi,
                    "fate": self.fate,
                    "secondary_fate": data["config"]["secondary_fate"],
                    "map_sha": self.map_sha,
                    "show_map_mode": self.show_map_mode,
                    "debug_mode": self.debug_mode,
                    "speed_mode": self.speed_mode,
                    "bonus": self.bonus,
                    "long_press_sprint": self.long_press_sprint,
                    "use_consumable": self.use_consumable,
                    "slow_mode": self.slow_mode,
                    "force_update": self.force_update,
                    "timezone": self.timezone,
                    "max_run": self.max_run
                },
                "prior": data["prior"],
                "key_mapping": self.mapping
            })


config = Config()
