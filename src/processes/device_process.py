"""外设控制子进程 — 舵机 + LED 控制器

职责:
- 接收主进程的外设控制命令（SERVO_COMMAND / LED_COMMAND / BOX_OPEN / BOX_CLOSE）
- 执行舵机角度控制和 LED 颜色/模式切换
- 响应 SHUTDOWN 信号

通信:
- Input:  from_main (接收 SERVO_COMMAND / LED_COMMAND / BOX_OPEN / BOX_CLOSE / SHUTDOWN)
- Output: to_main   (发送命令执行结果 / HEARTBEAT)
"""

import time
import threading
from typing import Union

try:
    from multiprocessing import Queue as MPQueue
except ImportError:
    MPQueue = None

import queue as th_queue

from src.config import config
from src.devices import (
    get_box_servo_left, get_box_servo_right,
    get_pan_servo, get_tilt_servo,
    get_led,
)
from src.message_bus import IPCMessage, MessageType
from src.utils.logger import setup_logger

logger = setup_logger("device_proc")

# 命令处理间隔（秒）
COMMAND_POLL_INTERVAL = 0.05  # 50ms 高频轮询以保证舵机响应及时


def device_process_main(
    to_main: Union[th_queue.Queue, MPQueue],
    from_main: Union[th_queue.Queue, MPQueue],
    shutdown_event: threading.Event,
):
    """
    外设控制子进程主函数

    在子进程内部自行创建设备实例。
    持续轮询 from_main 队列，执行收到的控制命令。

    Args:
        to_main: 发送执行结果到主进程的队列
        from_main: 接收主进程命令的队列
        shutdown_event: 关闭信号
    """
    logger.info("外设控制子进程启动中...")

    # ── 在子进程内部创建设备实例 ──
    try:
        box_left = get_box_servo_left()
        box_right = get_box_servo_right()
        pan = get_pan_servo()
        tilt = get_tilt_servo()
        led = get_led()
        logger.info("外设设备初始化完成")
    except Exception as e:
        logger.error(f"外设设备初始化失败: {e}")
        return

    # ── 配置参数 ──
    box_open_angle = config.get("servo.box_open_angle", 0)
    box_close_angle = config.get("servo.box_close_angle", 90)

    # 心跳
    heartbeat_interval = 1.0
    last_heartbeat = time.monotonic()

    logger.info(f"外设控制循环启动 (开盖={box_open_angle}°, 关盖={box_close_angle}°)")

    # ── 主循环 ──
    while not shutdown_event.is_set():
        try:
            # ── 轮询命令 ──
            try:
                cmd = from_main.get_nowait() if not from_main.empty() else None
            except (th_queue.Empty, Exception):
                cmd = None

            if cmd is None:
                # 心跳
                now = time.monotonic()
                if now - last_heartbeat > heartbeat_interval:
                    last_heartbeat = now
                    to_main.put(IPCMessage(
                        type=MessageType.HEARTBEAT,
                        source="device",
                        payload={"uptime": now},
                    ))
                time.sleep(COMMAND_POLL_INTERVAL)
                continue

            # ── 解析命令 ──
            if isinstance(cmd, dict):
                cmd = IPCMessage.from_dict(cmd)

            if not isinstance(cmd, IPCMessage):
                continue

            # ── 处理 SHUTDOWN ──
            if cmd.type == MessageType.SHUTDOWN:
                logger.info("收到 SHUTDOWN 信号，外设子进程退出")
                # 退出前恢复默认状态
                led.set_color("blue", "breath")
                break

            # ── 处理舵机命令 ──
            elif cmd.type == MessageType.SERVO_COMMAND:
                servo_name = cmd.payload.get("servo", "")
                angle = cmd.payload.get("angle", 90)
                servo_map = {
                    "box_left": box_left,
                    "box_right": box_right,
                    "pan": pan,
                    "tilt": tilt,
                }
                if servo_name in servo_map:
                    servo_map[servo_name].set_angle(angle)
                    logger.info(f"舵机控制: {servo_name} -> {angle}°")
                    to_main.put(IPCMessage(
                        type=MessageType.SYSTEM_EVENT,
                        source="device",
                        payload={"event": "servo_done", "servo": servo_name, "angle": angle},
                    ))

            # ── 处理盒盖命令 ──
            elif cmd.type == MessageType.BOX_OPEN:
                box_left.set_angle(box_open_angle)
                box_right.set_angle(box_open_angle)
                logger.info("执行: 打开盒盖")
                to_main.put(IPCMessage(
                    type=MessageType.SYSTEM_EVENT,
                    source="device",
                    payload={"event": "box_opened"},
                ))

            elif cmd.type == MessageType.BOX_CLOSE:
                box_left.set_angle(box_close_angle)
                box_right.set_angle(box_close_angle)
                logger.info("执行: 关闭盒盖")
                to_main.put(IPCMessage(
                    type=MessageType.SYSTEM_EVENT,
                    source="device",
                    payload={"event": "box_closed"},
                ))

            # ── 处理LED命令 ──
            elif cmd.type == MessageType.LED_COMMAND:
                color = cmd.payload.get("color", "off")
                pattern = cmd.payload.get("pattern", "solid")
                led.set_color(color, pattern)
                logger.info(f"LED控制: {color} / {pattern}")
                to_main.put(IPCMessage(
                    type=MessageType.SYSTEM_EVENT,
                    source="device",
                    payload={"event": "led_done", "color": color, "pattern": pattern},
                ))

        except Exception as e:
            logger.error(f"外设控制循环异常: {e}")
            time.sleep(0.5)

    # ── 清理 ──
    try:
        led.set_color("off")
        for dev in [box_left, box_right, pan, tilt, led]:
            if hasattr(dev, 'close'):
                dev.close()
    except Exception:
        pass
    logger.info("外设控制子进程已停止")
