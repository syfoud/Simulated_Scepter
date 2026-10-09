def __init__(self):
    super().__init__()
    self.daily_config = load_module_settings(__file__)
    self._skills_released = False
    self._challenge_started = False
    self._scroll_attempts = 0
    self._done = False
    # 大地图只在流程开始时处理一次；进过副本后的过场画面也常常误匹配
    # big_world，用该 flag 屏蔽后续误判。
    self._home_world_handled = False