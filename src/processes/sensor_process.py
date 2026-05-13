"""传感器子进程 — TOF距离传感器 + IR红外传感器

Mock 模式：以 daemon 线程运行（共享 queue.Queue）
真实模式：以独立 multiprocessing.Process 运行

职责:
- 周期性读取 TOF 距离传感器（坐姿检测）
- 周期性读取 IR 红外传感器（手机放入/取出检测）
- 检测到状态变化时发送 IPC 消息到主进程
- 响应主进程的 SHUTDOWN 信号

通信:
- Input:  from_main (接收 SHUTDOWN / 查询命令)
- Output: to_main   (发送 DISTANCE_TOF / POSTURE_WARNING / PHONE_DETECTED / PHONE_REMOVED / HEARTBEAT)
"""

import time
import threading
from typing import Union

# 根据运行模式选择 Queue
try:
    from multiprocessing import Queue as MPQueue
    from multiprocessing.synchronize import Event as MPEvent
except ImportError:
    MPQueue = None
    MPEvent = None

import queue as th_queue

from src.config import config
from src.devices import get_tof_sensor, get_ir_sensor
from src.message_bus import IPCMessage, MessageType
from src.utils.logger import setup_logger

logger = setup_logger("sensor_proc")

# 传感器读取间隔（秒）
SENSOR_LOOP_INTERVAL = 0.2  # 200ms，与 config 中的 sample_interval_ms 对齐


def sensor_process_main(
    to_main: Union[th_queue.Queue, MPQueue],
    from_main: Union[th_queue.Queue, MPQueue],
    shutdown_event: threading.Event,
):
    """
    传感器子进程主函数

    可在独立线程或独立进程中运行。
    在子进程内部自行创建设备实例（避免跨进程传递非picklable对象）。

    Args:
        to_main: 发送消息到主进程的队列
        from_main: 接收主进程命令的队列
        shutdown_event: 关闭信号
    """
    logger.info("传感器子进程启动中...")

    # ── 在子进程内部创建设备实例 ──
    try:
        tof = get_tof_sensor()
        ir_sensor = get_ir_sensor()
        logger.info("传感器设备初始化完成")
    except Exception as e:
        logger.error(f"传感器设备初始化失败: {e}")
        return

    # ── 状态追踪（仅在变化时发送消息，减少通信量） ──
    last_phone_state: bool = False       # 上一次手机存在状态
    last_distance: int = 0               # 上一次TOF距离
    last_posture_warning: bool = False   # 上一次坐姿警告状态

    # ── 采样间隔配置 ──
    tof_interval = config.get("posture.sample_interval_ms", 500) / 1000.0
    ir_interval = config.get("ir_sensor.sample_interval_ms", 200) / 1000.0
    last_tof_sample_time = 0.0
    last_ir_sample_time = 0.0

    # TOF坐姿检测阈值
    tof_threshold = config.get("posture.tof_threshold_mm", 350)
    tof_recovery = config.get("posture.tof_recovery_mm", 450)
    confirm_count = config.get("posture.confirm_count", 3)
    posture_cooldown = config.get("posture.cooldown_seconds", 30)

    # 坐姿确认计数器 + 冷却
    too_close_count = 0
    normal_count = 0
    last_posture_alert_time = 0.0

    # IR 去抖：连续 N 次状态一致才确认
    ir_debounce_count = config.get("ir_sensor.debounce_count", 3)
    ir_samples: list = []

    # 心跳计时
    heartbeat_interval = 1.0  # 每秒心跳
    last_heartbeat = time.monotonic()

    logger.info(
        f"传感器循环启动 (TOF阈值={tof_threshold}mm, 恢复={tof_recovery}mm, "
        f"确认帧={confirm_count}, 冷却={posture_cooldown}s, "
        f"IR去抖={ir_debounce_count})"
    )

    # ── 主循环 ──
    while not shutdown_event.is_set():
        try:
            now = time.monotonic()

            # ── 检查主进程命令（非阻塞） ──
            try:
                if isinstance(from_main, th_queue.Queue) or not hasattr(from_main, 'empty'):
                    cmd = from_main.get_nowait() if not from_main.empty() else None
                else:
                    cmd = from_main.get_nowait()
            except (th_queue.Empty, Exception):
                cmd = None

            if cmd is not None:
                # 处理命令（如果是 dict 则转换）
                if isinstance(cmd, dict):
                    cmd = IPCMessage.from_dict(cmd)
                if isinstance(cmd, IPCMessage) and cmd.type == MessageType.SHUTDOWN:
                    logger.info("收到 SHUTDOWN 信号，传感器子进程退出")
                    break

            # ── 读取 TOF 距离传感器 ──
            if now - last_tof_sample_time >= tof_interval:
                last_tof_sample_time = now
                distance = tof.read_distance()

                # 距离变化超过阈值才发送（减少噪声）
                if abs(distance - last_distance) > 50:
                    last_distance = distance
                    to_main.put(IPCMessage(
                        type=MessageType.DISTANCE_TOF,
                        source="sensor",
                        payload={"distance_mm": distance},
                    ))

                # ── 坐姿检测（TOF距离 < 阈值 = 太近） ──
                if distance < tof_threshold:
                    too_close_count += 1
                    normal_count = 0
                    # 连续N帧确认 + 冷却检查
                    if (too_close_count >= confirm_count and
                        now - last_posture_alert_time > posture_cooldown):
                        last_posture_alert_time = now
                        last_posture_warning = True
                        to_main.put(IPCMessage(
                            type=MessageType.POSTURE_WARNING,
                            source="sensor",
                            payload={
                                "distance_mm": distance,
                                "threshold_mm": tof_threshold,
                                "message": "坐姿过近",
                            },
                        ))
                        logger.info(f"坐姿警告: {distance}mm < {tof_threshold}mm")
                elif distance > tof_recovery:
                    normal_count += 1
                    too_close_count = 0
                    # 连续N帧确认恢复
                    if normal_count >= confirm_count and last_posture_warning:
                        last_posture_warning = False
                        to_main.put(IPCMessage(
                            type=MessageType.POSTURE_WARNING,
                            source="sensor",
                            payload={
                                "distance_mm": distance,
                                "recovered": True,
                                "message": "坐姿已恢复",
                            },
                        ))
                        logger.info(f"坐姿恢复: {distance}mm > {tof_recovery}mm")

            # ── 读取 IR 红外传感器（手机检测，带去抖） ──
            if now - last_ir_sample_time >= ir_interval:
                last_ir_sample_time = now
                phone_present = ir_sensor.read()
                ir_samples.append(phone_present)
                if len(ir_samples) > ir_debounce_count:
                    ir_samples.pop(0)

                # 去抖：连续 N 次状态一致才确认变化
                if len(ir_samples) >= ir_debounce_count:
                    all_same = all(s == ir_samples[0] for s in ir_samples)
                    if all_same and phone_present != last_phone_state:
                        last_phone_state = phone_present
                        msg_type = MessageType.PHONE_DETECTED if phone_present else MessageType.PHONE_REMOVED
                        to_main.put(IPCMessage(
                            type=msg_type,
                            source="sensor",
                            payload={"timestamp": time.time()},
                        ))
                        logger.info(f"IR状态变化: phone={'存在' if phone_present else '不存在'}")

            # ── 心跳 ──
            if now - last_heartbeat > heartbeat_interval:
                last_heartbeat = now
                to_main.put(IPCMessage(
                    type=MessageType.HEARTBEAT,
                    source="sensor",
                    payload={"uptime": now},
                ))

        except Exception as e:
            logger.error(f"传感器循环异常: {e}")
            time.sleep(1.0)  # 出错后等待再重试

        time.sleep(SENSOR_LOOP_INTERVAL)

    # ── 清理 ──
    try:
        if hasattr(tof, 'close'):
            tof.close()
        if hasattr(ir_sensor, 'close'):
            ir_sensor.close()
    except Exception:
        pass
    logger.info("传感器子进程已停止")
