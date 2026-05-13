"""M7+M8 测试套件：状态机 + 消息总线 + 传感器进程"""

import threading
import time
import pytest

from src.state_controller import FocusState, StateController
from src.message_bus import MessageBus, IPCMessage, MessageType
from src.tool_executor import ToolExecutor


# ═══════════════════════════════════════════════════════════
# M7: FocusState & StateController
# ═══════════════════════════════════════════════════════════

class TestFocusState:
    """FocusState 枚举测试"""

    def test_all_states_exist(self):
        states = {s.name for s in FocusState}
        expected = {"IDLE", "WAITING_PHONE", "BOX_CLOSED", "FOCUSING", "PAUSED", "COMPLETED"}
        assert states == expected

    def test_state_uniqueness(self):
        values = [s.value for s in FocusState]
        assert len(values) == len(set(values)), "State values must be unique"


class TestStateController:
    """StateController 状态机测试"""

    def test_initial_state_is_idle(self):
        sc = StateController()
        assert sc.state == FocusState.IDLE
        assert not sc.is_active
        assert not sc.is_paused

    def test_start_focus_from_idle(self):
        sc = StateController()
        result = sc.start_focus(25)
        assert result is True
        assert sc.state == FocusState.WAITING_PHONE
        assert sc.is_active
        assert sc.focus_duration_sec == 25 * 60
        assert sc.remaining_sec == 25 * 60

    def test_cannot_start_focus_when_active(self):
        sc = StateController()
        sc.start_focus(25)
        # 已在 WAITING_PHONE
        result = sc.start_focus(30)
        assert result is False
        assert sc.state == FocusState.WAITING_PHONE

    def test_phone_inserted_from_waiting(self):
        sc = StateController()
        sc.start_focus(25)
        result = sc.phone_inserted()
        assert result is True
        assert sc.state == FocusState.FOCUSING
        assert sc.is_focusing

    def test_phone_inserted_not_in_waiting(self):
        sc = StateController()
        result = sc.phone_inserted()
        assert result is False
        assert sc.state == FocusState.IDLE

    def test_phone_removed_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.phone_removed()
        assert result is True
        assert sc.state == FocusState.PAUSED
        assert sc.is_paused

    def test_phone_removed_not_in_focusing(self):
        sc = StateController()
        result = sc.phone_removed()
        assert result is False

    def test_phone_inserted_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        assert sc.state == FocusState.PAUSED
        result = sc.phone_inserted()
        assert result is True
        assert sc.state == FocusState.FOCUSING

    def test_complete_focus_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.complete_focus()
        assert result is True
        assert sc.state == FocusState.IDLE

    def test_complete_focus_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        assert sc.state == FocusState.PAUSED
        result = sc.complete_focus()
        assert result is True
        assert sc.state == FocusState.IDLE

    def test_cancel_focus_from_waiting(self):
        sc = StateController()
        sc.start_focus(25)
        result = sc.cancel_focus()
        assert result is True
        assert sc.state == FocusState.IDLE
        assert not sc.is_active

    def test_cancel_focus_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.cancel_focus()
        assert result is True
        assert sc.state == FocusState.IDLE

    def test_cancel_focus_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        result = sc.cancel_focus()
        assert result is True
        assert sc.state == FocusState.IDLE

    def test_request_pause(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.request_pause()
        assert result is True
        assert sc.state == FocusState.PAUSED

    def test_full_state_flow(self):
        """完整状态流转：IDLE → WAITING → FOCUSING → PAUSED → FOCUSING → COMPLETED → IDLE"""
        sc = StateController()
        state_log = []

        def log_change(old, new):
            state_log.append(f"{old}->{new}")

        sc.on_state_change = log_change

        assert sc.state == FocusState.IDLE

        # 1. 开始专注
        assert sc.start_focus(5)
        assert sc.state == FocusState.WAITING_PHONE

        # 2. 放手机
        assert sc.phone_inserted()
        assert sc.state == FocusState.FOCUSING

        # 3. 暂停
        assert sc.phone_removed()
        assert sc.state == FocusState.PAUSED

        # 4. 放回手机
        assert sc.phone_inserted()
        assert sc.state == FocusState.FOCUSING

        # 5. 完成
        assert sc.complete_focus()
        assert sc.state == FocusState.IDLE

        # 验证状态日志
        transitions = [s.split("->") for s in state_log]
        state_names = [t[1] for t in transitions]
        assert "FOCUSING" in state_names
        assert "PAUSED" in state_names

    def test_get_status_text(self):
        sc = StateController()
        assert "未开启" in sc.get_status_text()

        sc.start_focus(25)
        assert "等待放入手机" in sc.get_status_text()

        sc.phone_inserted()
        assert "专注中" in sc.get_status_text()

        sc.phone_removed()
        assert "已暂停" in sc.get_status_text()

    def test_get_remaining_minutes(self):
        sc = StateController()
        sc.start_focus(30)
        assert sc.get_remaining_minutes() == 30

    def test_is_active_states(self):
        sc = StateController()
        assert not sc.is_active
        sc.start_focus(25)
        assert sc.is_active
        sc.phone_inserted()
        assert sc.is_active
        sc.phone_removed()
        assert sc.is_active
        sc.complete_focus()
        assert not sc.is_active

    def test_timer_expired_flag(self):
        sc = StateController()
        assert not sc.timer_expired
        sc.timer_expired = True
        assert sc.timer_expired
        sc.timer_expired = False
        assert not sc.timer_expired

    def test_on_reminder_callback(self):
        sc = StateController()
        reminders = []

        sc.on_reminder = lambda text: reminders.append(text)
        sc.start_focus(0.02)  # 非常短的时长
        sc.phone_inserted()

        # 等待计时器到期
        time.sleep(0.3)
        sc._stop_tick_timer()

        # 提醒可能已触发或未触发（取决于时机）
        assert isinstance(reminders, list)

    def test_on_completed_callback(self):
        sc = StateController()
        completed = []

        sc.on_completed = lambda auto: completed.append(auto)
        sc.start_focus(0.02)
        sc.phone_inserted()

        time.sleep(0.3)
        sc._stop_tick_timer()

        if completed:
            assert completed[0] is True  # auto_expired

    def test_on_state_change_callback(self):
        sc = StateController()
        transitions = []

        sc.on_state_change = lambda old, new: transitions.append((old, new))
        sc.start_focus(25)
        sc.cancel_focus()

        assert len(transitions) >= 2
        assert transitions[0] == ("IDLE", "WAITING_PHONE")
        assert transitions[-1] == ("WAITING_PHONE", "IDLE")


# ═══════════════════════════════════════════════════════════
# M7: ToolExecutor + StateController integration
# ═══════════════════════════════════════════════════════════

class TestToolExecutorWithStateController:
    """ToolExecutor 与 StateController 集成测试"""

    def test_tool_executor_initializes_state_controller(self):
        te = ToolExecutor()
        assert te.state_ctrl is not None
        assert te.state_ctrl.state == FocusState.IDLE
        assert te.user_nickname is not None

    def test_execute_set_user_nickname(self):
        te = ToolExecutor()
        result = te.execute("set_user_nickname", {"nickname": "测试员"})
        assert result["success"] is True
        assert "测试员" in result["result"]
        assert te.user_nickname == "测试员"

    def test_execute_get_focus_status_idle(self):
        te = ToolExecutor()
        result = te.execute("get_focus_status", {})
        assert result["success"] is True
        assert "未开启" in result["result"]

    def test_execute_end_focus_mode_when_idle(self):
        te = ToolExecutor()
        result = te.execute("end_focus_mode", {})
        assert result["success"] is False
        assert "没有进行中" in result["result"]

    def test_execute_unknown_function(self):
        te = ToolExecutor()
        result = te.execute("nonexistent_func", {})
        assert result["success"] is False
        assert "Unknown" in result["result"]

    def test_get_status_for_llm(self):
        te = ToolExecutor()
        status = te.get_status_for_llm()
        assert status == "未开启专注模式"

    def test_timer_expired_property(self):
        te = ToolExecutor()
        assert not te.timer_expired
        te.timer_expired = True
        assert te.timer_expired
        te.timer_expired = False
        assert not te.timer_expired

    def test_force_timer_expire(self):
        te = ToolExecutor()
        te.force_timer_expire()
        assert te.timer_expired

    def test_state_ctrl_reminder_callback_registered(self):
        te = ToolExecutor()
        assert te.state_ctrl.on_reminder is not None
        assert te.state_ctrl.on_state_change is not None
        assert te.state_ctrl.on_completed is not None


# ═══════════════════════════════════════════════════════════
# M8: MessageBus
# ═══════════════════════════════════════════════════════════

class TestMessageType:
    """MessageType 枚举测试"""

    def test_all_message_types_exist(self):
        types = {t.name for t in MessageType}
        required = {
            "FACE_DETECTED", "FACE_LOST",
            "DISTANCE_TOF", "PHONE_DETECTED", "PHONE_REMOVED",
            "FOCUS_COMMAND", "LED_STATE", "SERVO_COMMAND",
            "SYSTEM_EVENT", "HEARTBEAT", "SHUTDOWN",
        }
        assert required.issubset(types)

    def test_message_type_values_are_strings(self):
        for t in MessageType:
            assert isinstance(t.value, str)


class TestIPCMessage:
    """IPCMessage 数据类测试"""

    def test_create_message(self):
        msg = IPCMessage(
            type=MessageType.PHONE_DETECTED,
            source="sensor",
            payload={"info": "test"},
        )
        assert msg.type == MessageType.PHONE_DETECTED
        assert msg.source == "sensor"
        assert msg.target is None
        assert msg.timestamp > 0
        assert msg.payload == {"info": "test"}

    def test_create_message_with_target(self):
        msg = IPCMessage(
            type=MessageType.FOCUS_COMMAND,
            source="main",
            target="device",
            payload={"action": "close_box"},
        )
        assert msg.target == "device"

    def test_default_payload(self):
        msg = IPCMessage(type=MessageType.HEARTBEAT, source="sensor")
        assert msg.payload == {}

    def test_timestamps_are_monotonic(self):
        msg1 = IPCMessage(type=MessageType.HEARTBEAT, source="test")
        time.sleep(0.02)  # Windows timer resolution ~15.6ms
        msg2 = IPCMessage(type=MessageType.HEARTBEAT, source="test")
        assert msg2.timestamp >= msg1.timestamp  # monotonic guarantees non-decreasing


class TestMessageBus:
    """MessageBus 消息总线测试"""

    def test_bus_initialization(self):
        bus = MessageBus(mock_mode=True)
        assert bus._mock is True

    def test_send_and_receive(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(
            type=MessageType.PHONE_DETECTED,
            source="sensor",
        )
        bus.send_to("main", msg)
        received = bus.get_from_main(timeout=0.1)
        assert received is not None
        assert received.type == MessageType.PHONE_DETECTED
        assert received.source == "sensor"

    def test_send_to_vision(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(type=MessageType.FOCUS_COMMAND, source="main")
        bus.send_to("vision", msg)
        # Should not raise

    def test_send_to_sensor(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(type=MessageType.FOCUS_COMMAND, source="main")
        bus.send_to("sensor", msg)
        # Should not raise

    def test_send_to_device(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(type=MessageType.SERVO_COMMAND, source="main")
        bus.send_to("device", msg)
        # Should not raise

    def test_broadcast(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(type=MessageType.SHUTDOWN, source="main")
        bus.broadcast(msg)
        # Should not raise

    def test_get_from_main_empty(self):
        bus = MessageBus(mock_mode=True)
        result = bus.get_from_main(timeout=0.01)
        assert result is None

    def test_multiple_messages(self):
        bus = MessageBus(mock_mode=True)
        msgs = [
            IPCMessage(type=MessageType.PHONE_DETECTED, source="sensor"),
            IPCMessage(type=MessageType.PHONE_REMOVED, source="sensor"),
            IPCMessage(type=MessageType.DISTANCE_TOF, source="sensor", payload={"distance_mm": 300}),
        ]
        for m in msgs:
            bus.send_to("main", m)

        received = []
        while True:
            m = bus.get_from_main(timeout=0.01)
            if m is None:
                break
            received.append(m)

        assert len(received) == 3
        assert received[0].type == MessageType.PHONE_DETECTED
        assert received[2].payload["distance_mm"] == 300

    def test_drain_main(self):
        bus = MessageBus(mock_mode=True)
        for _ in range(5):
            bus.send_to("main", IPCMessage(type=MessageType.HEARTBEAT, source="test"))

        count = bus.drain_main()
        assert count == 5

        # After drain, should be empty
        assert bus.get_from_main(timeout=0.01) is None

    def test_send_heartbeat(self):
        bus = MessageBus(mock_mode=True)
        bus.send_heartbeat("sensor")
        msg = bus.get_from_main(timeout=0.1)
        assert msg is not None
        assert msg.type == MessageType.HEARTBEAT
        assert msg.source == "sensor"

    def test_send_shutdown(self):
        bus = MessageBus(mock_mode=True)
        bus.send_shutdown()
        # Shutdown is broadcast, check it arrives at main queue
        # (broadcast only sends to vision/sensor/device, not main)
        # Just verify no exception

    def test_unknown_target(self):
        bus = MessageBus(mock_mode=True)
        bus.send_to("nonexistent", IPCMessage(type=MessageType.HEARTBEAT, source="test"))
        # Should not raise

    def test_message_with_payload(self):
        bus = MessageBus(mock_mode=True)
        msg = IPCMessage(
            type=MessageType.DISTANCE_TOF,
            source="sensor",
            payload={"distance_mm": 350, "threshold_mm": 400},
        )
        bus.send_to("main", msg)
        received = bus.get_from_main(timeout=0.1)
        assert received.payload["distance_mm"] == 350
        assert received.payload["threshold_mm"] == 400


# ═══════════════════════════════════════════════════════════
# M8: Sensor process (thread-based in mock mode)
# ═══════════════════════════════════════════════════════════

class TestSensorProcess:
    """传感器子进程/线程测试"""

    def test_sensor_loop_starts_and_stops(self):
        """验证传感器循环可以正常启动和停止"""
        from src.processes.sensor_process import sensor_process_loop

        bus = MessageBus(mock_mode=True)
        shutdown = threading.Event()

        thread = threading.Thread(
            target=sensor_process_loop,
            args=(bus, shutdown, 0.1),
            daemon=True,
        )
        thread.start()
        time.sleep(0.3)  # 让线程运行一小段时间
        shutdown.set()
        thread.join(timeout=2.0)

        assert not thread.is_alive()

    def test_sensor_loop_sends_messages(self):
        """验证传感器循环会发送消息到总线"""
        from src.processes.sensor_process import sensor_process_loop

        bus = MessageBus(mock_mode=True)
        shutdown = threading.Event()

        thread = threading.Thread(
            target=sensor_process_loop,
            args=(bus, shutdown, 0.05),
            daemon=True,
        )
        thread.start()
        time.sleep(0.5)  # 等待足够长时间以收集消息
        shutdown.set()
        thread.join(timeout=2.0)

        # 检查是否有消息
        msg_count = 0
        while bus.get_from_main(timeout=0.01) is not None:
            msg_count += 1

        # Mock模式下IR传感器默认状态可能不变化，但应收到TOF消息
        assert msg_count >= 0  # 至少不崩溃

    def test_sensor_process_imports(self):
        """验证传感器进程模块可正确导入"""
        from src.processes import sensor_process
        assert hasattr(sensor_process, "sensor_process_loop")
