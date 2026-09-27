import math
import time
from statistics import median

import pyuac

from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER


def get_angle(su):
    if get_global_stop_flag():
        return None
    key_mouse_manager.press("w")
    key_mouse_manager.wait()
    time.sleep(0.5)
    if get_global_stop_flag():
        return None
    su.get_screen()
    r, d = su.pos_predictor.update_minimap_data(su.screen)
    return r if d is not None else None




# 不同电脑鼠标移动速度、放缩比、分辨率等不同，因此需要校准
# 基本逻辑：每次转60度，然后计算实际转了几度，计算出误差比
def main(ang=(1, 1, 3), su=None):
    """校准转向倍率，并在创建截图器的线程中释放临时资源。"""
    owns_universe = su is None
    owns_manager = not key_mouse_manager.running
    previous_multi = key_mouse_manager.multi
    completed = False
    config = None
    previous_angle = None
    try:
        if owns_universe:
            from tool.simul.utils import UniverseUtils
            su = UniverseUtils()
        if get_global_stop_flag():
            return False
        if 'Diver' in su.__class__.__name__:
            from tool.diver.config import config
        else:
            from tool.simul.config import config
        previous_angle = config.angle
        key_mouse_manager.start()
        CUS_LOGGER.info("开始校准")
        key_mouse_manager.multi = 1
        init_ang = get_angle(su)
        if init_ang is None or not math.isfinite(init_ang):
            CUS_LOGGER.warning("校准未获得可靠初始方向，保留原倍率")
            return False
        lst_ang = init_ang
        for i in ang:
            if lst_ang != init_ang and i == 1:
                continue
            ang_list = []
            for _ in range(i):
                if get_global_stop_flag():
                    return False
                key_mouse_manager.mouse_move(60, fine=3 // i)
                key_mouse_manager.wait()
                time.sleep(0.2)
                now_ang = get_angle(su)
                if now_ang is None or not math.isfinite(now_ang):
                    CUS_LOGGER.warning("校准中方向识别失效，停止转向并保留原倍率")
                    return False
                ang_list.append((now_ang - lst_ang) % 360)
                lst_ang = now_ang
            accepted = [value for value in ang_list if abs(value - median(ang_list)) <= 3]
            total_angle = sum(accepted)
            CUS_LOGGER.debug("校准采样：angles=%s accepted=%s multiplier=%.6f", ang_list, accepted, key_mouse_manager.multi)
            if total_angle <= 1e-6:
                CUS_LOGGER.warning("校准未检测到有效转角，保留原倍率")
                return False
            key_mouse_manager.multi *= 60 * len(accepted) / total_angle
        key_mouse_manager.multi += 1e-9
        if not math.isfinite(key_mouse_manager.multi) or not 0 < key_mouse_manager.multi <= 5:
            CUS_LOGGER.warning("校准倍率 %.6f 超出合理范围，保留原倍率", key_mouse_manager.multi)
            return False
        if get_global_stop_flag():
            return False
        config.angle = str(key_mouse_manager.multi)
        config.save()
        completed = True
        CUS_LOGGER.info("校准完成，转向倍率：%.6f", key_mouse_manager.multi)
        return True
    finally:
        if not completed:
            key_mouse_manager.multi = previous_multi
            if config is not None:
                config.angle = previous_angle
        try:
            if owns_manager:
                key_mouse_manager.stop()
        finally:
            # 初始化被停止时可能尚未创建截图器；借入的实例由其调用方释放。
            if owns_universe and su is not None and getattr(su, "sct", None) is not None:
                su.sct.close()


if __name__ == "__main__":
    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin()
    else:
        main()
