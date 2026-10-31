"""状态驱动主循环：每帧只回答「现在是什么界面」，再看该交给谁处理。

与线性流程的区别：不记录「第几步」，也不预期「下一步应该是谁」。handler 处理完
进入冷却，冷却结束重新识别；界面乱序、重复出现、卡住不动都不会误动作，加新界面
只需往 handlers 里加一行。
"""

import time


class FlowDone(Exception):
    """handler 用它表示流程正常走完。"""


def run_flow(capture, identify, handlers, *, on_frame=None, idle=0.3, stable=2,
             cooldown=2.0, unknown_timeout=20.0, retry_limit=3, should_stop=None):
    """循环识别并分发。

    Args:
        capture: () -> image，取一帧画面。
        identify: image -> dict，至少包含 "state"；其余字段由 handler 自取自用。
        handlers: {state: handler(snapshot)}，handler 返回后进入冷却。
        on_frame: (snapshot, image) -> None，用于存证据，每帧调用。
        idle: 没有可动作状态时的轮询间隔（秒）。
        stable: 连续多少帧同一个状态才允许动作，防识别抖动导致连点。
        cooldown: 动作后多少秒内只识别不动作，等界面切换。
        unknown_timeout: 连续多少秒认不出已知状态就超时，避免无限等待。
        retry_limit: 同一界面连续处理几次仍无变化就报错，防「点了没反应」时无限重试。
        should_stop: () -> bool，外部停止条件（如 F8）。

    Raises:
        FlowDone: handlers 内主动结束（不再向上传播）。
        TimeoutError: 长时间停在未知界面。
        RuntimeError: 同一界面反复动作但界面没有变化。
        InterruptedError: should_stop 返回 True。
    """
    last_state, count = None, 0
    ready_at = 0.0
    unknown_since = None
    acted_state, same_state_actions = None, 0

    while True:
        if should_stop is not None and should_stop():
            raise InterruptedError("流程被外部停止")

        image = capture()
        snapshot = identify(image)
        state = snapshot["state"]
        if on_frame is not None:
            on_frame(snapshot, image)

        if state == last_state:
            count += 1
        else:
            last_state, count = state, 1

        handler = handlers.get(state)
        now = time.monotonic()
        if handler is None or count < stable or now < ready_at:
            if handler is None:
                unknown_since = unknown_since or now
                if now - unknown_since > unknown_timeout:
                    raise TimeoutError(f"长时间未识别到已知界面：{state}")
            else:
                unknown_since = None
            time.sleep(idle)
            continue

        unknown_since = None
        # 上一个动作后界面没变化：累计次数，超过上限说明点了没生效
        if state == acted_state:
            same_state_actions += 1
            if same_state_actions > retry_limit:
                raise RuntimeError(f"界面 {state} 连续处理 {same_state_actions} 次仍未变化，停止以免空转")
        else:
            acted_state, same_state_actions = state, 1

        try:
            handler(snapshot)
        except FlowDone:
            return
        ready_at = time.monotonic() + cooldown

