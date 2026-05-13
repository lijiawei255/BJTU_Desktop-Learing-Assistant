"""进程间消息总线 — M8 多进程架构的通信层

支持两种模式:
- Mock/PC模式: 使用 threading + queue.Queue（避免 Windows spawn 问题）
- 真实RPi模式: 使用 multiprocessing.Queue（真正的进程隔离）

消息流向:
  SensorProcess ──[TOF距离/IR手机状态]──> MainProcess
  VisionProcess ──[人脸跟踪/走神事件]──> MainProcess
  MainProcess   ──[舵机/LED控制命令]──> DeviceProcess
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union

# 根据运行环境选择 Queue 实现
try:
    from multiprocessing import Queue as MPQueue
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False

import queue as th_queue

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("message_bus")


# ═══════════════════════════════════════════════════════════════
# 消息类型枚举
# ═══════════════════════════════════════════════════════════════

class MessageType(Enum):
    """IPC 消息类型 — 覆盖视觉、传感器、外设、系统四大类"""

    # ── 视觉类（VisionProcess -> MainProcess） ──
    FACE_DETECTED = "face_detected"        # 检测到人脸
    FACE_LOST = "face_lost"                # 人脸丢失
    DISTRACTION = "distraction"            # 走神事件 (eyes_closed / looking_away)
    FACE_TRACKING = "face_tracking"        # 人脸跟踪位置更新

    # ── 传感器类（SensorProcess -> MainProcess） ──
    DISTANCE_TOF = "distance_tof"          # TOF距离读数 (mm)
    POSTURE_WARNING = "posture_warning"    # 坐姿不端正警告
    PHONE_DETECTED = "phone_detected"      # IR检测到手机放入
    PHONE_REMOVED = "phone_removed"        # IR检测到手机取出

    # ── 外设控制类（MainProcess -> DeviceProcess） ──
    SERVO_COMMAND = "servo_command"        # 舵机控制命令
    LED_COMMAND = "led_command"            # LED控制命令
    BOX_OPEN = "box_open"                  # 打开手机盒
    BOX_CLOSE = "box_close"                # 关闭手机盒

    # ── 系统类（双向） ──
    SYSTEM_EVENT = "system_event"          # 系统事件（状态变化通知）
    HEARTBEAT = "heartbeat"                # 心跳（子进程存活检测）
    SHUTDOWN = "shutdown"                  # 关闭信号


# ═══════════════════════════════════════════════════════════════
# IPC 消息数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class IPCMessage:
    """
    进程间通信消息

    Attributes:
        type: 消息类型
        source: 发送方标识 ("main" | "vision" | "sensor" | "device")
        target: 接收方标识 (None = 广播)
        timestamp: 消息时间戳 (time.monotonic)
        payload: 消息载荷 (dict)
    """
    type: MessageType
    source: str
    target: Optional[str] = None
    timestamp: float = field(default_factory=time.monotonic)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的字典（用于跨进程传输）"""
        return {
            "type": self.type.value,
            "source": self.source,
            "target": self.target,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IPCMessage":
        """从字典恢复（跨进程接收端使用）"""
        return cls(
            type=MessageType(data["type"]),
            source=data["source"],
            target=data.get("target"),
            timestamp=data.get("timestamp", time.monotonic()),
            payload=data.get("payload", {}),
        )


# ═══════════════════════════════════════════════════════════════
# Queue 工厂 — 根据运行模式选择实现
# ═══════════════════════════════════════════════════════════════

def _create_queue(maxsize: int = 100):
    """
    创建消息队列

    在 Mock 模式下使用 threading.Queue（轻量、Windows兼容），
    真实RPi模式下使用 multiprocessing.Queue（进程隔离）。
    """
    if config.is_mock or not _MP_AVAILABLE:
        return th_queue.Queue(maxsize=maxsize)
    else:
        return MPQueue(maxsize=maxsize)


# ═══════════════════════════════════════════════════════════════
# MessageBus — 消息总线
# ═══════════════════════════════════════════════════════════════

class MessageBus:
    """
    消息总线 — 管理各进程/线程间的消息队列

    架构:
        MainProcess (主进程)
          ├── to_sensor   → SensorProcess   (传感器采集)
          ├── to_vision   → VisionProcess   (摄像头跟踪)
          ├── to_device   → DeviceProcess   (外设控制)
          └── to_main     ← 所有子进程的消息汇总
    """

    def __init__(self):
        # 主进程 → 各子进程的命令队列
        self.to_sensor: Union[th_queue.Queue, MPQueue] = _create_queue()
        self.to_vision: Union[th_queue.Queue, MPQueue] = _create_queue()
        self.to_device: Union[th_queue.Queue, MPQueue] = _create_queue()

        # 各子进程 → 主进程的事件队列（所有子进程共用）
        self.to_main: Union[th_queue.Queue, MPQueue] = _create_queue()

        # 心跳追踪
        self._last_heartbeats: Dict[str, float] = {}
        self._heartbeat_lock = threading.Lock()

        logger.info(
            f"MessageBus 初始化 (模式: {'Mock/Threading' if config.is_mock else 'Multiprocessing'})"
        )

    # ── 发送 ──────────────────────────────────────────────────

    def send(self, target: str, msg: IPCMessage):
        """
        发送消息到指定目标

        Args:
            target: 目标标识 ("main" | "vision" | "sensor" | "device")
            msg: 要发送的消息
        """
        queue_map = {
            "main": self.to_main,
            "vision": self.to_vision,
            "sensor": self.to_sensor,
            "device": self.to_device,
        }
        if target in queue_map:
            msg.target = target
            try:
                # 跨进程时使用 dict 序列化
                if isinstance(queue_map[target], MPQueue) if _MP_AVAILABLE else False:
                    queue_map[target].put(msg.to_dict())
                else:
                    queue_map[target].put(msg)
            except Exception as e:
                logger.error(f"发送消息到 {target} 失败: {e}")
        else:
            logger.warning(f"未知目标: {target}")

    def broadcast(self, msg: IPCMessage):
        """广播消息到所有子进程"""
        for target in ["vision", "sensor", "device"]:
            self.send(target, msg)

    # ── 接收（主进程侧） ──────────────────────────────────────

    def receive(self, timeout: float = 0.01) -> Optional[IPCMessage]:
        """
        主进程从 to_main 队列接收消息（非阻塞）

        Args:
            timeout: 等待超时（秒），0 表示立即返回

        Returns:
            IPCMessage 或 None（队列为空时）
        """
        try:
            msg = self.to_main.get(timeout=timeout)
            # 如果是 dict（跨进程），转换回 IPCMessage
            if isinstance(msg, dict):
                msg = IPCMessage.from_dict(msg)
            return msg
        except th_queue.Empty:
            return None
        except Exception as e:
            logger.error(f"接收消息失败: {e}")
            return None

    def drain(self) -> list:
        """
        排空 to_main 队列，返回所有待处理消息
        用于主循环中批量处理事件
        """
        messages = []
        while True:
            msg = self.receive(timeout=0)
            if msg is None:
                break
            messages.append(msg)
        return messages

    # ── 心跳管理 ──────────────────────────────────────────────

    def update_heartbeat(self, source: str):
        """更新子进程心跳时间"""
        with self._heartbeat_lock:
            self._last_heartbeats[source] = time.monotonic()

    def check_heartbeats(self, timeout_seconds: float = 5.0) -> list:
        """
        检查子进程心跳超时

        Returns:
            超时的子进程名称列表
        """
        now = time.monotonic()
        timed_out = []
        with self._heartbeat_lock:
            for source, last in self._last_heartbeats.items():
                if now - last > timeout_seconds:
                    timed_out.append(source)
        return timed_out

    # ── 清理 ──────────────────────────────────────────────────

    def shutdown(self):
        """发送关闭信号到所有子进程并清理队列"""
        shutdown_msg = IPCMessage(
            type=MessageType.SHUTDOWN,
            source="main",
            payload={"reason": "normal_shutdown"},
        )
        self.broadcast(shutdown_msg)
        logger.info("MessageBus 已发送关闭信号")
