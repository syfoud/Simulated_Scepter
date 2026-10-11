import ctypes
import sys
import time

import numpy as np
import cv2 as cv
import win32gui
from tool.utils.get_win_rect import get_window_rect
from tool.GLOBAL import key_mouse_manager
from tool.screenshot import Screen
from core.simulated.utils import set_forground
from tool.utils.image_tool import find_image_in_folder, load_all_images_from_directory
load_all_images_from_directory()
event_mask = (find_image_in_folder("gray_image/",'MASK_MAP_INTERACT_BLACK') > 70)[:497]
def get_screen():

    # 获取游戏窗口信息
    hwnd = win32gui.GetForegroundWindow()
    win32gui.GetClientRect(hwnd)
    x0, y0, x1, y1 = get_window_rect(hwnd)
    screen_capture = Screen()
    screen = screen_capture.grab(x0, y0)
    return screen
def get_text_position(image):
    scr = image[:497]
    mask = np.zeros((497, scr.shape[1]), dtype=np.uint8)
    mask_zero = np.zeros((497, scr.shape[1]), dtype=np.uint8)
    mask[((scr.max(axis=-1) - scr.min(axis=-1)) < 3) & (scr.max(axis=-1) > 247)] = 255
    mask_zero[((scr.max(axis=-1) - scr.min(axis=-1)) < 3) & (scr.max(axis=-1) < 21)] = 255
    kernel = np.ones((10, 30), np.uint8)
    mask_zero = cv.dilate(mask_zero, kernel, iterations=1)
    mask &= mask_zero
    mask[event_mask] = 0
    kernel = np.ones((8, 55), np.uint8)
    mask = cv.dilate(mask, kernel, iterations=1)
    kernel = np.ones((6, 40), np.uint8)
    mask = cv.erode(mask, kernel, iterations=2)
    # cv.imshow("mask", mask)
    # cv.waitKey(0)
    contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    print(contours)
    mx_area, mx_cnt = 0, None
    for cnt in contours:
        x, y, w, h = cv.boundingRect(cnt)
        # print(w,h)
        if h > 22:
            continue
        if mx_area < w * h:
            mx_area = w * h
            mx_cnt = cnt
    res = []
    if mx_area < 4:
        return res
    xx, yy, ww, hh = cv.boundingRect(mx_cnt)
    for cnt in contours:
        x, y, w, h = cv.boundingRect(cnt)
        if w * h >= 4 and abs(y - yy) < 20:
            res.append((x + w // 2, y + h // 2))
    res = sorted(res, key=lambda x: x[0])
    if len(res) == 2 and res[1][0] - res[0][0] < 150:
        res = [((res[0][0] + res[1][0]) // 2, res[0][1])]
    return res
def draw_text_positions(image, positions):
    """
    在图像上绘制文本位置的框选结果
    
    参数:
        image: 原始图像
        positions: get_text_position函数返回的坐标点列表 [(x, y), ...]
    
    返回:
        带有标注框的图像
    """
    # 创建图像副本以避免修改原图
    result_image = image.copy()
    
    # 为每个检测到的文本位置绘制框
    for i, (x, y) in enumerate(positions):
        # 绘制红色圆点标记中心位置
        cv.circle(result_image, (x, y), 5, (0, 0, 255), -1)
        
        # 在旁边添加序号标签
        cv.putText(result_image, str(i+1), (x+10, y-10), 
                  cv.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        # 绘制十字线辅助定位
        cv.line(result_image, (x-15, y), (x+15, y), (0, 255, 0), 2)
        cv.line(result_image, (x, y-15), (x, y+15), (0, 255, 0), 2)
    
    return result_image
def main(show):
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                __file__,
                None,
                show
            )
            return True
        except:
            return False


    if not is_admin():

        if run_as_admin():
            sys.exit(0)
        else:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("权限错误", "此程序需要管理员权限才能正常运行。请右键点击程序并选择'以管理员身份运行'。")
            root.destroy()
    else:
        set_forground()
        time.sleep(1)
        key_mouse_manager.start()
        for k in [60, 120, 60, 60, 30, 30, -60, -60, -60, -60, -60, -60]:
            pos = get_text_position(get_screen())
            print(pos)
            if pos:
                print(960 - pos[0][0])
                key_mouse_manager.mouse_move((pos[0][0]-960)/16.5)
                key_mouse_manager.wait()
                break
            key_mouse_manager.mouse_move(-k)
            key_mouse_manager.wait()
        key_mouse_manager.stop()
        input("请按任意键继续...")
if __name__ == '__main__':
    # 读取测试图像
    # image = cv.imread('test/20251029_214854.png')
    # # 获取文本位置
    # positions = get_text_position(image)
    # print(f"检测到的文本位置: {positions}")
    main(1)
    # 绘制标注结果
    # annotated_image = draw_text_positions(image, positions)
    # cv.imshow('Text Position Detection Result', annotated_image)
    # cv.waitKey(0)
    # cv.destroyAllWindows()
