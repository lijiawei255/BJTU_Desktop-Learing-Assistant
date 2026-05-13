"""视觉子进程 — 摄像头人脸跟踪 + 走神检测

职责:
- PID人脸跟踪 + 自动扫描（当人脸丢失时）
- MediaPipe 走神检测（闭眼、视线偏离）
- 检测到人脸/走神事件时发送 IPC 消息到主进程
- 响应主进程的 START_TRACKING / STOP_TRACKING / SHUTDOWN 命令

通信:
- Input:  from_main (接收 START_TRACKING / STOP_TRACKING / SHUTDOWN)
- Output: to_main   (发送 FACE_DETECTED / FACE_LOST / FACE_TRACKING / DISTRACTION / HEARTBEAT)
"""

import time
import threading
from typing import Optional, Union

try:
    from multiprocessing import Queue as MPQueue
except ImportError:
    MPQueue = None

import queue as th_queue

from src.config import config
from src.devices import get_pan_servo, get_tilt_servo, get_camera
from src.message_bus import IPCMessage, MessageType
from src.utils.logger import setup_logger

logger = setup_logger("vision_proc")


def vision_process_main(
    to_main: Union[th_queue.Queue, MPQueue],
    from_main: Union[th_queue.Queue, MPQueue],
    shutdown_event: threading.Event,
):
    """
    视觉子进程主函数

    可在独立线程或独立进程中运行。
    在子进程内部自行创建设备实例。

    Args:
        to_main: 发送消息到主进程的队列
        from_main: 接收主进程命令的队列
        shutdown_event: 关闭信号
    """
    logger.info("视觉子进程启动中...")

    # ── 在子进程内部创建设备实例 ──
    try:
        pan_servo = get_pan_servo()
        tilt_servo = get_tilt_servo()
        camera = get_camera(pan_servo, tilt_servo)
        logger.info("摄像头设备初始化完成")
    except Exception as e:
        logger.error(f"摄像头设备初始化失败: {e}")
        return

    # ── 内部状态 ──
    tracking_active: bool = False
    face_present: bool = False
    prev_face_present: bool = False
    distraction_cooldown: float = 0.0  # 走神提醒冷却

    # ── 配置参数 ──
    detect_interval = config.get("vision.face_detection_interval", 3)
    distract_interval = config.get("vision.distraction_interval_frames", 5)
    fps = config.get("vision.fps", 15)
    distraction_cooldown_sec = 5.0  # 走神提醒最小间隔

    # 心跳
    heartbeat_interval = 1.0
    last_heartbeat = time.monotonic()

    frame_count = 0
    last_face_rect = None

    # ── 设置回调（将检测事件转为 IPC 消息） ──
    def on_distraction_handler(reason: str):
        """走神检测回调 → IPC消息"""
        nonlocal distraction_cooldown
        now = time.monotonic()
        if now - distraction_cooldown < distraction_cooldown_sec:
            return  # 冷却中，不重复发
        distraction_cooldown = now
        to_main.put(IPCMessage(
            type=MessageType.DISTRACTION,
            source="vision",
            payload={"reason": reason, "timestamp": now},
        ))
        logger.info(f"走神事件: {reason}")

    def on_face_found_handler():
        """重新捕捉人脸回调 → IPC消息"""
        to_main.put(IPCMessage(
            type=MessageType.FACE_DETECTED,
            source="vision",
            payload={"timestamp": time.monotonic()},
        ))

    camera.on_distracted = on_distraction_handler
    camera.on_face_found = on_face_found_handler

    # ── 启动摄像头 ──
    try:
        camera.start()
        logger.info("摄像头已启动")
    except Exception as e:
        logger.error(f"摄像头启动失败: {e}")
        return

    logger.info(f"视觉循环启动 (检测间隔={detect_interval}帧, 走神间隔={distract_interval}帧, FPS={fps})")

    # ── 主循环 ──
    while not shutdown_event.is_set():
        try:
            # ── 检查主进程命令（非阻塞） ──
            try:
                cmd = from_main.get_nowait() if not from_main.empty() else None
            except (th_queue.Empty, Exception):
                cmd = None

            if cmd is not None:
                if isinstance(cmd, dict):
                    cmd = IPCMessage.from_dict(cmd)

                if isinstance(cmd, IPCMessage):
                    if cmd.type == MessageType.SHUTDOWN:
                        logger.info("收到 SHUTDOWN 信号，视觉子进程退出")
                        break
                    elif cmd.type == MessageType.SYSTEM_EVENT:
                        event = cmd.payload.get("event", "")
                        if event == "start_tracking":
                            tracking_active = True
                            camera.start_tracking()
                            logger.info("开始人脸跟踪")
                        elif event == "stop_tracking":
                            tracking_active = False
                            camera.stop_tracking()
                            logger.info("停止人脸跟踪")

            # ── 只在跟踪激活时执行检测 ──
            if not tracking_active:
                time.sleep(0.1)
                continue

            # ── 捕获帧 ──
            frame = camera.capture_frame()

            frame_count += 1

            # ── 跳帧人脸检测 ──
            if frame_count % detect_interval == 0:
                faces = camera.detect_faces(frame)
                last_face_rect = faces[0] if faces else None

            face_rect = last_face_rect
            prev_face_present = face_present
            face_present = face_rect is not None

            # ── 人脸状态变化通知 ──
            if face_present and not prev_face_present:
                to_main.put(IPCMessage(
                    type=MessageType.FACE_DETECTED,
                    source="vision",
                    payload={"timestamp": time.monotonic()},
                ))
            elif not face_present and prev_face_present:
                to_main.put(IPCMessage(
                    type=MessageType.FACE_LOST,
                    source="vision",
                    payload={"timestamp": time.monotonic()},
                ))

            # ── PID跟踪 ──
            if camera.tracker:
                camera.tracker.update(face_rect, camera.width, camera.height)
                if face_rect:
                    fx, fy, fw, fh = face_rect
                    to_main.put(IPCMessage(
                        type=MessageType.FACE_TRACKING,
                        source="vision",
                        payload={
                            "face_x": fx + fw // 2,
                            "face_y": fy + fh // 2,
                            "face_w": fw,
                            "face_h": fh,
                        },
                    ))

            # ── 走神检测（跳帧） ──
            if face_rect and frame_count % distract_interval == 0:
                dist = camera.detector.analyze(frame)
                if dist["distracted"]:
                    if dist["eyes_closed"]:
                        on_distraction_handler("eyes_closed")
                    elif dist["looking_away"]:
                        on_distraction_handler("looking_away")

            # ── 心跳 ──
            now = time.monotonic()
            if now - last_heartbeat > heartbeat_interval:
                last_heartbeat = now
                to_main.put(IPCMessage(
                    type=MessageType.HEARTBEAT,
                    source="vision",
                    payload={"uptime": now, "tracking": tracking_active},
                ))

        except Exception as e:
            logger.error(f"视觉循环异常: {e}")
            time.sleep(0.5)

        time.sleep(1.0 / fps)

    # ── 清理 ──
    try:
        camera.stop()
        if hasattr(camera, 'close'):
            camera.close()
    except Exception:
        pass
    logger.info("视觉子进程已停止")
