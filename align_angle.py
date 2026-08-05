import time

import numpy as np
import pyuac

from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER


def get_angle(su):
    key_mouse_manager.press("w")
    time.sleep(0.5)
    su.get_screen()
    r, d = su.pos_predictor.update_minimap_data(su.screen)
    return r




# 不同电脑鼠标移动速度、放缩比、分辨率等不同，因此需要校准
# 基本逻辑：每次转60度，然后计算实际转了几度，计算出误差比
def main(ang=[1,1,3], su=None):
    key_mouse_manager.start()
    if su is None:
        from tool.simul.utils import UniverseUtils
        su = UniverseUtils()
    if 'Diver' in su.__class__.__name__:
        from tool.diver.config import config
    else:
        from tool.simul.config import config
    CUS_LOGGER.info("开始校准")
    key_mouse_manager.multi = 1
    init_ang = get_angle(su)
    if init_ang is None:
        CUS_LOGGER.info("未成功修正")
        return False
    lst_ang = init_ang
    for i in ang:
        if lst_ang != init_ang and i==1:
            continue
        ang_list = []
        for j in range(i):
            key_mouse_manager.mouse_move(60, fine=3 // i)
            key_mouse_manager.wait()
            time.sleep(0.2)
            now_ang = get_angle(su)
            sub = now_ang - lst_ang
            while sub < 0:
                sub += 360
            ang_list.append(sub)
            lst_ang = now_ang
        ang_list = np.array(ang_list)
        # 十/3次转身的角度
        CUS_LOGGER.debug(f"基本角度变化: {ang_list}")
        ax = 0
        ay = 0
        for j in ang_list:
            if abs(j - np.median(ang_list)) <= 3:
                ax += 60
                ay += j
        CUS_LOGGER.debug(f"原始倍率：{key_mouse_manager.multi}倍率变化: {ax}/{ay}")
        key_mouse_manager.multi *= ax / ay
    key_mouse_manager.multi += 1e-9
    try:
        if abs(key_mouse_manager.multi) > 10 or key_mouse_manager.multi <= 0:
            CUS_LOGGER.warning(f"校准结果{key_mouse_manager.multi}超出合理范围，重置为默认值1")
            key_mouse_manager.multi = 1
    except:
        key_mouse_manager.multi = 1
    
    # 打印基本校准后的角度校准值
    CUS_LOGGER.info(f"基本角度校准值: {key_mouse_manager.multi}")

    
    CUS_LOGGER.info("所有校准完成")
    config.angle = str(key_mouse_manager.multi)
    config.save()
    return True


if __name__ == "__main__":
    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin()
    else:
        main()
