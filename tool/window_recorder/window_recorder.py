import ctypes
import datetime
import os
import threading
import time

# 导入必要的 Windows API 函数
from ctypes import windll

import cv2
import numpy as np
import win32gui
import win32ui
from PIL import ImageGrab

from route import PATHS
from tool.log import CUS_LOGGER
from tool.thread import ThreadWithException
from tool.utils.game_window import (
    CLOUD_WINDOW_KIND,
    LOCAL_GAME_TITLE,
    find_game_window,
    get_client_screen_rect,
    get_window_kind,
    is_usable_game_window,
)
from tool.window_recorder.recorder_writer import RecorderWriter
from tool.window_recorder.video_remux import convert_in_background


class WindowRecorder:
    def __init__(self, output_path=PATHS["video"], handle=None, fps=30.0, window_title=None, window_class_name=None, see_time=False, is_show=False, offsets=None, overlay_map=False, map_alpha=0.7, simul_instance=None, task_owner=None):
        self.output_path = output_path
        self.fps = fps
        self.window_title = window_title
        self.window_class_name = window_class_name
        self.recording = False
        self.recording_thread = None
        self.hwnd = handle
        self.out = None
        self.width = 0
        self.height = 0
        self.window_kind = None
        self.see_time = see_time
        self.is_show = is_show
        # 偏移参数，用于收缩录制范围 [left, top, right, bottom]
        if offsets is None:
            offsets = [0, 0, 0, 0]
        self.offsets = offsets
        self.left_offset = offsets[0]
        self.top_offset = offsets[1]
        self.right_offset = offsets[2]
        self.bottom_offset = offsets[3]
        # 是否叠加地图窗口
        self.overlay_map = overlay_map
        # 地图透明度 (0.0-1.0，1.0为完全不透明)
        self.map_alpha = map_alpha
        # SimulatedUniverse实例引用
        self.simul_instance = simul_instance
        # 停止信号，代表一个尚未被响应的停止请求，必须保留到下一次启动被拒绝
        self.stop_event = threading.Event()
        # 保护录制状态与停止请求的转移，避免停止到达时错误放行一次新的录制
        self.state_lock = threading.Lock()
        # 录制所服务的任务线程。录制线程每轮检查它是否还活着，任务一结束就停止录制，
        # 避免录制线程成为孤儿、任务早就停了录像却一直在长大。
        # 可以在构造时传入，也可以在创建内核后由 GUI 统一绑定（见 create_task_engine）。
        self.task_owner = task_owner

    def capture_window_background(self, hwnd):
        """使用 PrintWindow API 后台截图指定窗口"""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None

        # 获取窗口尺寸
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            if width <= 0 or height <= 0:
                return None

            # 创建设备上下文和位图
            hwnd_dc = None
            mfc_dc = None
            save_dc = None
            save_bit_map = None
            old_bitmap = None

            try:
                # 获取窗口DC
                hwnd_dc = win32gui.GetWindowDC(hwnd)
                if not hwnd_dc:
                    return None

                # 创建DC对象
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()

                # 创建位图
                save_bit_map = win32ui.CreateBitmap()
                save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
                old_bitmap = save_dc.SelectObject(save_bit_map)

                # 使用 PrintWindow API 后台截图
                result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)

                if result == 1:  # 成功
                    # 转换为 numpy 数组
                    bmp_info = save_bit_map.GetInfo()
                    bmp_str = save_bit_map.GetBitmapBits(True)
                    img = np.frombuffer(bmp_str, dtype=np.uint8)
                    img.shape = (bmp_info['bmHeight'], bmp_info['bmWidth'], 4)  # BGRA

                    # 转换为 BGR 格式
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    return img
                else:
                    return None

            finally:
                # 确保所有资源都被正确释放 - 关键修复点
                try:
                    if old_bitmap and save_dc:
                        save_dc.SelectObject(old_bitmap)
                except Exception as e:
                    CUS_LOGGER.warning(f"恢复位图选择失败: {e}")

                try:
                    if save_bit_map:
                        win32gui.DeleteObject(save_bit_map.GetHandle())
                except Exception as e:
                    CUS_LOGGER.warning(f"删除位图对象失败: {e}")

                try:
                    if save_dc:
                        save_dc.DeleteDC()
                except Exception as e:
                    CUS_LOGGER.warning(f"删除保存DC失败: {e}")

                try:
                    if mfc_dc:
                        mfc_dc.DeleteDC()
                except Exception as e:
                    CUS_LOGGER.warning(f"删除MFC DC失败: {e}")

                try:
                    if hwnd_dc:
                        win32gui.ReleaseDC(hwnd, hwnd_dc)
                except Exception as e:
                    CUS_LOGGER.warning(f"释放窗口DC失败: {e}")

        except Exception as e:
            CUS_LOGGER.warning(f"后台截图窗口失败: {e}")
            # 发生异常时也要确保资源清理
            import gc
            gc.collect()
            return None

    def start_recording(self,count=0):
        """开始录制指定窗口"""
        CUS_LOGGER.debug(f"启动录制第{count}次")
        with self.state_lock:
            if self.recording:
                CUS_LOGGER.info("Already recording")
                return
            if self.recording_thread and self.recording_thread.is_alive():
                # 上一次会话的线程还活着：它仍持有写入器，此时启动新会话会让旧线程
                # 退出时误释放新会话的写入器，因此拒绝。
                CUS_LOGGER.debug("上一次录制的线程尚未结束，跳过本次启动")
                return
            # 走到这里说明上一次会话已经结束。若仍有停止意图，那它只可能来自
            # 「停止该会话」的请求（restart_recording 正是"停止→再启动"的写法），
            # 属于那个已结束的会话，应当随本次启动一并清掉；否则配对的启动会被
            # 自己拒绝，此后本次运行再也不录制。
            self.stop_event.clear()
        timestamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = os.path.join(self.output_path, f"第{count}次轮回-{timestamp}.mp4")
        # 查找目标窗口
        if self.hwnd and not is_usable_game_window(self.hwnd):
            self.hwnd = None
        if not self.hwnd:
            self.hwnd = win32gui.FindWindow(self.window_class_name, self.window_title)
        # 本地客户端沿用 UnityWndClass；找不到时为云游戏选择真正的
        # Chrome_WidgetWin_1，避免精确标题命中 Explorer 的 TabProxyWindow。
        if (
            not is_usable_game_window(self.hwnd)
            and self.window_title == LOCAL_GAME_TITLE
        ):
            game_window = find_game_window(prefer_foreground=True)
            self.hwnd = game_window.hwnd if game_window else None
        CUS_LOGGER.info(f"找到窗口句柄: {self.hwnd or 0}")

        if not self.hwnd:
            if self.window_class_name:
                CUS_LOGGER.error(f"未找到类名为 '{self.window_class_name}' 且标题包含 '{self.window_title}' 的窗口")
                raise ValueError(f"未找到类名为 '{self.window_class_name}' 且标题包含 '{self.window_title}' 的窗口")
            else:
                CUS_LOGGER.error(f"未找到标题包含 '{self.window_title}' 的窗口")
                raise ValueError(f"未找到标题包含 '{self.window_title}' 的窗口")

        # 确保窗口可见且有效
        if not win32gui.IsWindowVisible(self.hwnd):
            CUS_LOGGER.warning("警告: 窗口不可见")

        if not win32gui.IsWindow(self.hwnd):
            CUS_LOGGER.error("窗口句柄无效")
            raise ValueError("窗口句柄无效")

        self.window_kind = get_window_kind(self.hwnd)
        if self.window_kind is None:
            CUS_LOGGER.error("找到的窗口不是受支持的游戏主窗口")
            raise ValueError("找到的窗口不是受支持的游戏主窗口")

        # 设置DPI感知
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 2 = Per-monitor v2 DPI awareness
        except Exception as e:
            CUS_LOGGER.warning(f"无法设置DPI感知级别: {e}")
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception as e:
                CUS_LOGGER.warning(f"无法设置DPI感知级别(备用方法): {e}")

        # 获取窗口位置和尺寸
        try:
            # 云游戏只录制 Edge 客户区；本地客户端保持原窗口矩形逻辑。
            if self.window_kind == CLOUD_WINDOW_KIND:
                rect = get_client_screen_rect(self.hwnd)
            else:
                rect = win32gui.GetWindowRect(self.hwnd)
            self.left, self.top, self.right, self.bottom = rect
            self.width = self.right - self.left
            self.height = self.bottom - self.top

            CUS_LOGGER.info(
                f"窗口类型: {self.window_kind}, 位置: "
                f"({self.left}, {self.top}, {self.right}, {self.bottom}), "
                f"尺寸: {self.width}x{self.height}"
            )
        except Exception as e:
            CUS_LOGGER.error(f"获取窗口位置失败: {e}")
            raise

        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 应用偏移后的实际录制尺寸
        self.capture_left = self.left + self.offsets[0]
        self.capture_top = self.top + self.offsets[1]
        self.capture_right = self.right - self.offsets[2]
        self.capture_bottom = self.bottom - self.offsets[3]
        actual_width = self.capture_right - self.capture_left
        actual_height = self.capture_bottom - self.capture_top
        # 常见编码器要求偶数宽高。云窗口可能是 1920x1079，裁剪后为奇数。
        if actual_width % 2:
            self.capture_right -= 1
            actual_width -= 1
        if actual_height % 2:
            self.capture_bottom -= 1
            actual_height -= 1
        if actual_width <= 0 or actual_height <= 0:
            raise ValueError(f"录像区域无效: {actual_width}x{actual_height}")

        # 设置视频写入器
        CUS_LOGGER.info(f"初始化视频写入器，尺寸: {actual_width}x{actual_height}")
        self.out = RecorderWriter(self.output_file, actual_width, actual_height, self.fps)

        # 初始化期间可能已经收到停止请求，此时不要启动录制线程，并丢弃刚创建的空文件
        with self.state_lock:
            self.recording = True
            if self.stop_event.is_set():
                CUS_LOGGER.debug("录制初始化期间收到停止请求，取消本次录制")
                self.recording = False
                self._abort_start()
                return

            # 启动录制线程
            self.recording_thread = ThreadWithException(target=self._record_window, daemon=True,name="视频录制")
            self.recording_thread.start()

    def _remove_output(self):
        """删除当前录制文件，无文件时按已删除处理。"""
        if not os.path.exists(self.output_file):
            return

        try:
            os.remove(self.output_file)
            CUS_LOGGER.debug(f"已删除视频文件：{self.output_file}")
        except OSError as e:
            CUS_LOGGER.warning(f"删除视频文件失败：{e}")

    def _abort_start(self):
        """释放因停止请求而取消的启动所创建的空视频文件。"""
        if self.out:
            self.out.stop()
            self.out = None

        self._remove_output()

    def _record_window(self):
        """实际的窗口录制线程"""
        frame_count = 0
        started_at = time.monotonic()
        try:
            while self.recording and not self.stop_event.is_set():
                owner = self.task_owner
                if owner is not None and not owner.is_alive():
                    # 所属任务已结束（正常退出或异常终止）：录制必须跟着结束。
                    # 否则录制线程会作为孤儿继续写盘，直到进程被强制结束为止，
                    # 表现为「任务早就停了，录像文件却一直在长大」。
                    CUS_LOGGER.warning(
                        f"录制的任务已结束，停止录制（已录 "
                        f"{time.monotonic() - started_at:.0f} 秒 / {frame_count} 帧）"
                    )
                    break
                try:
                    # 应用偏移值来收缩录制范围 [left, top, right, bottom]
                    # 使用ImageGrab直接捕获窗口区域
                    bbox = (
                        self.capture_left,
                        self.capture_top,
                        self.capture_right,
                        self.capture_bottom,
                    )
                    img = ImageGrab.grab(bbox=bbox)

                    # 转换为OpenCV格式
                    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

                    # 检查是否需要叠加地图窗口
                    if self.overlay_map:
                        # 尝试查找地图窗口（"Map"窗口）
                        map_hwnd = win32gui.FindWindow(None, "Map")
                        if map_hwnd:
                            try:
                                # 使用后台截图方式获取地图窗口图像
                                map_img_cv = self.capture_window_background(map_hwnd)

                                if map_img_cv is not None:
                                    # 进一步缩小地图图像尺寸
                                    map_scale = 0.3  # 缩放到原图的30%
                                    map_resized_width = int(img_cv.shape[1] * map_scale)  # 基于主窗口宽度计算
                                    map_resized_height = int(map_resized_width * (map_img_cv.shape[0] / map_img_cv.shape[1]))  # 保持比例
                                    map_img_resized = cv2.resize(map_img_cv, (map_resized_width, map_resized_height))
                                    # 动态读取SimulatedUniverse的state属性并绘制到地图图像上
                                    if self.simul_instance is not None and self.simul_instance.state is not None:
                                        state_text = "state:" + str(self.simul_instance.state)
                                        font = cv2.FONT_HERSHEY_SIMPLEX
                                        font_scale = 0.8
                                        font_thickness = 1
                                        text_color = (0, 255, 0)
                                        cv2.putText(map_img_resized,
                                                  state_text,
                                                  (5, 15),  # 固定位置，避免计算文本尺寸
                                                  font,
                                                  font_scale,
                                                  text_color,
                                                  font_thickness)
                                        if self.simul_instance.now_map is not None:
                                            state_text = "map:" + str(self.simul_instance.now_map)
                                            cv2.putText(map_img_resized,
                                                        state_text,
                                                        (5, 40),
                                                        font,
                                                        font_scale,
                                                        (0, 0, 255),
                                                        font_thickness)

                                    # 将调整后的地图图像叠加到主图像的左下角上方（带透明度）
                                    margin = 10
                                    # 计算时间戳区域的高度
                                    # 预先计算时间戳尺寸，以便地图放置在时间戳上方
                                    if self.see_time:
                                        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                                        current_time = datetime.datetime.now().strftime("%H:%M:%S")

                                        # 配置参数
                                        font_scale = 0.5
                                        font_thickness = 2
                                        font = cv2.FONT_HERSHEY_SIMPLEX
                                        line_spacing = 15
                                        h_padding = 6
                                        v_padding = 20

                                        # 获取文本尺寸
                                        (text_width1, text_height1), _ = cv2.getTextSize(current_date, font, font_scale, font_thickness)
                                        (text_width2, text_height2), _ = cv2.getTextSize(current_time, font, font_scale, font_thickness)

                                        # 计算最大宽度和总高度
                                        max_text_width = max(text_width1, text_height2)
                                        total_text_height = text_height1 + text_height2 + line_spacing

                                        # 优化背景框尺寸计算
                                        rect_width = max_text_width + h_padding * 2
                                        rect_height = total_text_height + v_padding * 2

                                        # 将地图放在时间戳上方
                                        timestamp_bottom_y = img_cv.shape[0] - 5
                                        timestamp_top_y = timestamp_bottom_y - rect_height
                                        map_bottom_y = timestamp_top_y - margin  # 地图在时间戳上方，留出间距
                                        map_top_y = map_bottom_y - map_resized_height

                                        # 确保地图在窗口范围内
                                        if map_top_y > margin:  # 如果地图放置在时间戳上方后仍在窗口内
                                            # 实现透明度叠加
                                            roi = img_cv[map_top_y:map_bottom_y, margin:margin+map_resized_width]
                                            # 将地图图像转换为相同数据类型
                                            map_img_resized = map_img_resized.astype(np.float32)
                                            roi = roi.astype(np.float32)
                                            # 使用加权叠加实现透明效果
                                            cv2.addWeighted(map_img_resized, self.map_alpha, roi, 1-self.map_alpha, 0, roi)
                                            # 转换回uint8并更新原图像
                                            img_cv[map_top_y:map_bottom_y, margin:margin+map_resized_width] = roi.astype(np.uint8)
                                        else:
                                            # 如果放不下，则不叠加地图
                                            pass
                                    else:
                                        # 如果不需要时间戳，将地图放在左下角（带透明度）
                                        roi = img_cv[img_cv.shape[0]-map_resized_height-margin:img_cv.shape[0]-margin,
                                                    margin:margin+map_resized_width]
                                        # 将地图图像转换为相同数据类型
                                        map_img_resized = map_img_resized.astype(np.float32)
                                        roi = roi.astype(np.float32)
                                        # 使用加权叠加实现透明效果
                                        cv2.addWeighted(map_img_resized, self.map_alpha, roi, 1-self.map_alpha, 0, roi)
                                        # 转换回uint8并更新原图像
                                        img_cv[img_cv.shape[0]-map_resized_height-margin:img_cv.shape[0]-margin,
                                              margin:margin+map_resized_width] = roi.astype(np.uint8)
                                else:
                                    CUS_LOGGER.warning("后台获取地图窗口失败，跳过叠加")
                            except Exception as e:
                                CUS_LOGGER.warning(f"叠加地图窗口失败: {e}")
                                # 如果叠加地图失败，继续录制主窗口
                                pass

                    # 添加时间戳（如果需要）
                    if self.see_time:
                        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                        current_time = datetime.datetime.now().strftime("%H:%M:%S")

                        # 配置参数
                        font_scale = 0.5
                        font_thickness = 2
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        line_spacing = 15
                        h_padding = 25
                        v_padding = 8

                        # 获取文本尺寸
                        (text_width1, text_height1), _ = cv2.getTextSize(current_date, font, font_scale, font_thickness)
                        (text_width2, text_height2), _ = cv2.getTextSize(current_time, font, font_scale, font_thickness)

                        # 计算最大宽度和总高度
                        max_text_width = max(text_width1, text_width2)
                        total_text_height = text_height1 + text_height2 + line_spacing

                        # 优化背景框尺寸计算
                        rect_width = max_text_width + h_padding * 2
                        rect_height = total_text_height + v_padding * 2

                        # 计算左下角位置（紧贴左下角）
                        bottom_y = img_cv.shape[0]
                        left_x = 0

                        # 绘制黑色背景矩形
                        cv2.rectangle(img_cv,
                                      (left_x, bottom_y - rect_height),
                                      (left_x + rect_width, bottom_y),
                                      (0, 0, 0),
                                      -1)

                        # 优化文字绘制位置
                        line1_y = bottom_y - rect_height + v_padding + text_height1
                        line2_y = line1_y + text_height2 + line_spacing

                        cv2.putText(img_cv, current_date,
                                    (left_x + h_padding, line1_y),
                                    font,
                                    font_scale,
                                    (255, 255, 255),
                                    font_thickness)

                        cv2.putText(img_cv, current_time,
                                    (left_x + h_padding, line2_y),
                                    font,
                                    font_scale,
                                    (255, 255, 255),
                                    font_thickness)

                    # 写入视频文件
                    self.out.write(img_cv)
                    frame_count += 1

                    if self.is_show:
                        # 实时显示当前帧
                        cv2.imshow('Window Recorder', img_cv)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            CUS_LOGGER.info("用户按 q 键，停止录制")
                            self.stop_recording()
                            break

                    # 控制帧率
                    time.sleep(1 / self.fps)

                except Exception as e:
                    CUS_LOGGER.warning(f"录制单帧时发生错误: {e}")
                    continue

        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            # 释放资源
            if self.out:
                self.out.stop()
                self.out = None
            self.recording = False
            CUS_LOGGER.info("视频写入器已释放")

            # 停止请求在首帧之前到达时不会写入任何画面，留下的空文件无法播放
            if frame_count == 0:
                self._abort_start()

    def stop_recording(self, delete_video=False, battle_count=None):
        """停止录制

        Args:
            delete_video (bool): 是否删除录制的视频文件，默认为 False
            battle_count (int, optional): 战斗次数；保留录制且不为 None 时，用于更新视频文件名
        """
        with self.state_lock:
            if not self.recording:
                # 没有正在运行的录制可停：只记录，不留停止意图。
                # 若在这里留下停止意图，随后配对的 start_recording 会把自己拒绝掉
                # （restart_recording 正是"停止→再启动"的写法），此后本次运行再也
                # 不会录制。停止意图只应属于真正被停止的那个会话。
                CUS_LOGGER.debug("录制尚未正式启动，无需停止")
                return

            self.stop_event.set()
            self.recording = False

        # 等待录制线程完全退出，避免编码器资源竞争。
        # 无论线程是否退出，下面都必须释放写入器：这是唯一能止住文件继续增长的动作。
        thread_stopped = self._stop_recording_thread()
        if not thread_stopped:
            # 线程卡在无法中断的截图或写盘调用里；它可能永远不再回到循环开头，
            # 此时若继续持有写入器，文件就会一直增长。释放后已写入的分片仍可播放，
            # 卡住的线程即使恢复也只会写入失败并退出。
            CUS_LOGGER.warning(
                f"录制线程未在规定时间内结束，先止住写入以避免文件持续增长：{self.output_file}"
            )

        # 分片 MP4 的 moov 写在文件开头，进程被强制结束时已写入的分片仍可播放，
        # 因此不再按索引判定有效性。也只有写入线程真的失败（文件里没有可用内容）
        # 才删除；线程未能结束不代表内容不可用，那种文件必须保留。
        write_failed = False
        if self.out:
            write_failed = self.out.failed
            if not self.out.stop():
                CUS_LOGGER.warning(f"写入器未正常收尾，保留已写入的分片：{self.output_file}")
            self.out = None

        if not thread_stopped:
            # 无法确认线程已退出，不能去动文件（不删除、不重命名、不转封装）
            CUS_LOGGER.debug(f"录制线程未退出，暂不处置录制文件：{self.output_file}")
            return

        if delete_video or write_failed:
            self._abort_start()
            return

        # 保留录制时，更新视频文件名，增加战斗次数信息
        if battle_count is not None:
            try:
                head, tail = self.output_file.rsplit("次轮回-", 1)
                new_path = f"{head}次轮回-{battle_count}战-{tail}"
                os.rename(self.output_file, new_path)
                self.output_file = new_path
            except Exception as e:
                CUS_LOGGER.warning(f"更新视频文件名失败：{e}")

        # 录制文件是分片 MP4：崩溃可播，但分片结构让部分播放器（如 Windows 自带）
        # 建不出进度索引。这里在后台转封装成标准 MP4 恢复可跳转，不阻塞主任务。
        # 走到这里说明写入器已正常收尾，文件结构完整、不含损坏帧，因此无需校验。
        convert_in_background(self.output_file, check_output=False)
        CUS_LOGGER.debug(f"停止录制{self.output_file}")

    def _stop_recording_thread(self):
        """等待录制线程退出，返回是否可以安全处置录制文件。

        录制线程可能阻塞在截图或写盘调用中，这类调用无法被停止标志或线程中断打断。
        此时不能强行终止线程，也不应继续等待卡住停止流程；本次录制按失败处理，
        调用方跳过清理与重命名，等线程自行退出后再由后续的停止流程处置。

        Returns:
            线程已退出（或本来就没有在录制）时为 True，否则为 False。
        """
        if not self.recording_thread or not self.recording_thread.is_alive():
            return True

        try:
            CUS_LOGGER.debug("等待录制线程结束...")
            self.recording_thread.join(timeout=3.0)
        except Exception as e:
            CUS_LOGGER.warning(f"等待录制线程结束时发生错误：{e}")
            return False

        if not self.recording_thread.is_alive():
            CUS_LOGGER.debug("录制线程已正常结束")
            return True

        CUS_LOGGER.error(
            "录制线程未在规定时间内结束，本次不处置录制文件（由停止流程先行止住写入）"
        )
        return False


if __name__ == "__main__":
    try:
        window_title = "崩坏：星穹铁道"
        output_file = PATHS["video"]
        fps = 10

        CUS_LOGGER.info("=== 窗口录制器测试 (带透明度地图叠加) ===")
        CUS_LOGGER.info("准备开始录制（5秒后自动停止）...")
        CUS_LOGGER.info(f"请在5秒内打开窗口：{window_title}")
        CUS_LOGGER.info("地图将以60%透明度叠加显示在左下角")
        time.sleep(2)

        # 创建带透明度的地图叠加录制器
        recorder = WindowRecorder(
            output_path=output_file,
            fps=fps,
            window_title=window_title,
            window_class_name="UnityWndClass",
            offsets=[10, 50, 10, 10],
            overlay_map=True,      # 启用地图叠加
            map_alpha=0.6,         # 60%透明度
            see_time=True          # 显示时间戳
        )

        recorder.start_recording()
        CUS_LOGGER.info(f"正在录制窗口：{window_title}")
        CUS_LOGGER.info("录制将持续5秒，请在目标窗口中进行一些操作")
        CUS_LOGGER.info("地图窗口会以半透明形式显示在录制画面左下角")

        time.sleep(5)

        recorder.stop_recording()
        CUS_LOGGER.info("录制已完成！")
        CUS_LOGGER.info(f"视频已保存为：{recorder.output_file}")
        CUS_LOGGER.info("请检查生成的视频文件，确认透明度叠加效果正常")

    except Exception as e:
        CUS_LOGGER.error(f"发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
