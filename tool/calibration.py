"""鼠标转角倍率（校准角度）的读写与校准流程。

不同电脑的鼠标移动速度、画面缩放比和分辨率不同，同一个“转身 60 度”指令
在不同机器上转过的角度并不一致，因此需要实测出一个倍率并缓存到用户设置里。
"""

import time

import numpy as np

from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER
from tool.settings import load_settings, update_settings



def get_multi():
    """读取已保存的校准倍率。

    未校准或数值超出合理范围时返回 1.0（相当于不做修正）。

    Returns:
        float: 校准倍率。
    """
    try:
        value = float(load_settings()["calibration_angle"])
    except (KeyError, TypeError, ValueError):
        CUS_LOGGER.warning("校准角度配置不是有效数字，按未校准处理")
        return 1.0
    # 校准倍率的合理范围：超出说明测量被打断或配置被手改过
    if 0.0 < value <= 5.0:
        return value
    CUS_LOGGER.warning(f"校准角度配置异常（{value}），按未校准处理")
    return 1.0


def create_kernel():
    """构造一个仅供校准使用的内核实例。

    校准只需要前台窗口截图和小地图朝向识别，与命途、地图、战斗等业务逻辑无关，
    因此直接实例化通用内核，不依赖任何具体内核是否可运行。

    Returns:
        ScriptKernel: 已连接游戏窗口、附带小地图朝向识别器的内核实例。
    """
    from core.common.runtime import ScriptKernel
    from tool.utils.mminimap import PositionPredict

    kernel = ScriptKernel()
    kernel.pos_predictor = PositionPredict()
    return kernel


def get_angle(su):
    """按一次前进键后，从当前小地图朝向反推出角色朝向角。"""
    key_mouse_manager.press("move_w")
    time.sleep(0.5)
    su.get_screen()
    r, d = su.pos_predictor.update_minimap_data(su.screen)
    return r


def main(ang=[1, 1, 3], su=None):
    """执行一次角度校准并保存结果。

    Args:
        ang: 依次进行的转身次数分组，默认先转 1 次、再 1 次、最后 3 次。
        su: 已就绪的内核实例；为空时自行创建通用内核并在结束后释放。

    Returns:
        bool: 校准成功返回 True，无法识别初始朝向返回 False。
    """
    key_mouse_manager.start()
    own_kernel = su is None
    try:
        if own_kernel:
            su = create_kernel()
        return _calibrate(ang, su)
    finally:
        if own_kernel:
            if su is not None:
                su.stop()
            else:
                key_mouse_manager.stop()


def _calibrate(ang, su):
    """按组转身并累积误差比，最终写入用户设置。"""
    CUS_LOGGER.info("开始校准")
    key_mouse_manager.multi = 1
    init_ang = get_angle(su)
    if init_ang is None:
        CUS_LOGGER.info("未成功修正")
        return False
    lst_ang = init_ang
    for i in ang:
        if lst_ang != init_ang and i == 1:
            continue
        ang_list = []
        for j in range(i):
            key_mouse_manager.turn(60, fine=3 // i)
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
    if abs(key_mouse_manager.multi) > 5.0 or key_mouse_manager.multi <= 0.0:
        CUS_LOGGER.warning(f"校准结果{key_mouse_manager.multi}超出合理范围，重置为默认值1")
        key_mouse_manager.multi = 1

    # 打印基本校准后的角度校准值
    CUS_LOGGER.info(f"基本角度校准值: {key_mouse_manager.multi}")

    CUS_LOGGER.info("所有校准完成")
    update_settings({"calibration_angle": float(key_mouse_manager.multi)})
    return True


if __name__ == "__main__":
    import pyuac

    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin()
    else:
        main()
