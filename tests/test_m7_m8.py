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
        assert result["success"] is True
        assert sc.state == FocusState.WAITING_PHONE
        assert sc.is_active
        assert sc.focus_duration_sec == 25 * 60
        assert sc.remaining_seconds == 0  # 等待手机时还没有启动计时

    def test_cannot_start_focus_when_active(self):
        sc = StateController()
        sc.start_focus(25)
        # 已在 WAITING_PHONE
        result = sc.start_focus(30)
        assert result["success"] is False
        assert sc.state == FocusState.WAITING_PHONE

    def test_phone_inserted_from_waiting(self):
        sc = StateController()
        sc.start_focus(25)
        result = sc.phone_inserted()
        assert result["success"] is True
        assert sc.state == FocusState.FOCUSING
        assert sc.is_focusing

    def test_phone_inserted_not_in_waiting(self):
        sc = StateController()
        result = sc.phone_inserted()
        assert result["success"] is False
        assert sc.state == FocusState.IDLE

    def test_phone_removed_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.phone_removed()
        assert result["success"] is True
        assert sc.state == FocusState.PAUSED
        assert sc.is_paused

    def test_phone_removed_not_in_focusing(self):
        sc = StateController()
        result = sc.phone_removed()
        assert result["success"] is False

    def test_phone_inserted_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        assert sc.state == FocusState.PAUSED
        result = sc.phone_inserted()
        assert result["success"] is True
        assert sc.state == FocusState.FOCUSING

    def test_complete_focus_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.complete_focus()
        assert result["success"] is True
        assert sc.state == FocusState.IDLE

    @pytest.mark.xfail(strict=True, raises=AssertionError, reason="FOCUS-PAUSED: complete_focus rejects PAUSED; runtime change deferred for RPi validation")
    def test_complete_focus_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        assert sc.state == FocusState.PAUSED
        result = sc.complete_focus()
        assert result["success"] is True
        assert sc.state == FocusState.IDLE

    def test_cancel_focus_from_waiting(self):
        sc = StateController()
        sc.start_focus(25)
        result = sc.cancel_focus()
        assert result["success"] is True
        assert sc.state == FocusState.IDLE
        assert not sc.is_active

    def test_cancel_focus_from_focusing(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.cancel_focus()
        assert result["success"] is True
        assert sc.state == FocusState.IDLE

    def test_cancel_focus_from_paused(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        sc.phone_removed()
        result = sc.cancel_focus()
        assert result["success"] is True
        assert sc.state == FocusState.IDLE

    def test_request_pause(self):
        sc = StateController()
        sc.start_focus(25)
        sc.phone_inserted()
        result = sc.request_pause()
        assert result["success"] is True
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
        assert sc.start_focus(5)["success"]
        assert sc.state == FocusState.WAITING_PHONE

        # 2. 放手机
        assert sc.phone_inserted()["success"]
        assert sc.state == FocusState.FOCUSING

        # 3. 暂停
        assert sc.phone_removed()["success"]
        assert sc.state == FocusState.PAUSED

        # 4. 放回手机
        assert sc.phone_inserted()["success"]
        assert sc.state == FocusState.FOCUSING

        # 5. 完成
        assert sc.complete_focus()["success"]
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
        assert "专注模式进行中" in sc.get_status_text()

        sc.phone_removed()
        assert "专注模式暂停中" in sc.get_status_text()

    def test_remaining_seconds_after_phone_inserted(self):
        sc = StateController()
        sc.start_focus(30)
        assert sc.phone_inserted()["success"]
        assert sc.remaining_seconds == 30 * 60

    def test_is_active_states(self):
        sc = StateController()
        assert not sc.is_active
        sc.start_focus(25)
        assert sc.is_active
        sc.phone_inserted()
        assert sc.is_active
        sc.phone_removed()
        assert sc.is_active
        assert sc.cancel_focus()["success"]
        assert not sc.is_active

    def test_timer_expired_flag(self):
        sc = StateController()
        assert not sc.timer_expired
        sc.timer_expired = True
        assert sc.timer_expired
        sc.timer_expired = False
        assert not sc.timer_expired

    def test_tick_returns_configured_reminder(self):
        sc = StateController()
        assert sc.start_focus(25)["success"]
        assert sc.phone_inserted()["success"]
        sc.timer.pause()
        with sc.timer._lock:
            sc.timer._remaining = 300
        assert sc.tick() == "还剩5分钟，继续加油哦！"

    def test_timer_expiry_sets_polling_flag(self):
        sc = StateController()
        finished = threading.Event()
        original = sc.timer._on_expire

        def on_expire():
            original()
            finished.set()

        sc.timer._on_expire = on_expire
        sc.timer.start(1)
        assert finished.wait(timeout=3), "Timer did not report expiry"
        assert sc.timer_expired
        assert sc.timer.remaining == 0

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
        assert result["result"] == "当前没有进行专注模式。"

    def test_execute_end_focus_mode_when_idle(self):
        te = ToolExecutor()
        result = te.execute("end_focus_mode", {})
        assert result["success"] is False
        assert "没有进行中" in result["result"]

    def test_execute_unknown_function(self):
        te = ToolExecutor()
        result = te.execute("nonexistent_func", {})
        assert result["success"] is False
        assert result["result"] == "未知函数: nonexistent_func"

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

    def test_device_callbacks_are_bound(self):
        te = ToolExecutor()
        for name in ("on_box_open", "on_box_close", "on_led_change",
                     "on_camera_start", "on_camera_stop", "on_state_change"):
            assert callable(getattr(te.state_ctrl, name)), name



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
    """Exercise current public API; keep the send defect visible as strict xfail."""

    def test_bus_initialization(self):
        import queue
        bus = MessageBus()
        for name in ("to_main", "to_sensor", "to_vision", "to_device"):
            assert isinstance(getattr(bus, name), queue.Queue)

    @pytest.mark.parametrize("target", ["main", "sensor", "vision", "device"])
    @pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUS-SEND: MPQueue factory used as isinstance type; runtime unchanged")
    def test_send_delivers_message(self, target):
        bus = MessageBus()
        msg = IPCMessage(type=MessageType.HEARTBEAT, source="test", payload={"count": 1})
        bus.send(target, msg)
        destination = getattr(bus, "to_" + target)
        assert destination.qsize() == 1
        received = destination.get_nowait()
        if isinstance(received, dict):
            received = IPCMessage.from_dict(received)
        assert received.type == msg.type
        assert received.payload == {"count": 1}
        assert received.target == target

    @pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUS-SEND: broadcast delegates to broken send; runtime unchanged")
    def test_broadcast_delivers_to_each_child(self):
        bus = MessageBus()
        bus.broadcast(IPCMessage(type=MessageType.SHUTDOWN, source="main"))
        for target in ("sensor", "vision", "device"):
            assert getattr(bus, "to_" + target).qsize() == 1
        assert bus.receive(timeout=0) is None

    def test_receive_empty(self):
        assert MessageBus().receive(timeout=0) is None

    def test_receive_and_drain_preserve_order(self):
        # Sensor's production path puts IPCMessage directly into to_main.
        bus = MessageBus()
        messages = [IPCMessage(type=t, source="sensor") for t in
                    (MessageType.PHONE_DETECTED, MessageType.PHONE_REMOVED, MessageType.DISTANCE_TOF)]
        for msg in messages:
            bus.to_main.put(msg)
        assert bus.receive(timeout=0) == messages[0]
        assert bus.drain() == messages[1:]
        assert bus.receive(timeout=0) is None

    def test_receive_serialized_message(self):
        bus = MessageBus()
        msg = IPCMessage(type=MessageType.DISTANCE_TOF, source="sensor", payload={"distance_mm": 350})
        bus.to_main.put(msg.to_dict())
        assert bus.receive(timeout=0) == msg

    def test_heartbeat_timeout(self, monkeypatch):
        from types import SimpleNamespace
        from src import message_bus
        monkeypatch.setattr(message_bus, "time", SimpleNamespace(monotonic=lambda: 10.0))
        bus = MessageBus()
        bus.update_heartbeat("sensor")
        assert bus.check_heartbeats(timeout_seconds=5) == []
        monkeypatch.setattr(message_bus, "time", SimpleNamespace(monotonic=lambda: 16.0))
        assert bus.check_heartbeats(timeout_seconds=5) == ["sensor"]

    @pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUS-SEND: shutdown broadcasts via broken send; runtime unchanged")
    def test_shutdown_delivers_to_children(self):
        bus = MessageBus()
        bus.shutdown()
        for target in ("sensor", "vision", "device"):
            assert getattr(bus, "to_" + target).qsize() == 1
            assert getattr(bus, "to_" + target).get_nowait().type == MessageType.SHUTDOWN

    def test_unknown_target_is_logged(self, caplog):
        bus = MessageBus()
        bus.send("nonexistent", IPCMessage(type=MessageType.HEARTBEAT, source="test"))
        assert "未知目标" in caplog.text
        assert bus.drain() == []


class TestSensorProcess:
    """传感器子进程/线程测试"""

    def test_sensor_loop_starts_and_stops(self):
        """验证传感器循环可以正常启动和停止"""
        from src.processes.sensor_process import sensor_process_loop

        bus = MessageBus()
        shutdown = threading.Event()

        thread = threading.Thread(
            target=sensor_process_loop,
            args=(bus, shutdown, 0.1),
            daemon=True,
        )
        thread.start()
        try:
            msg = bus.receive(timeout=2)
            assert msg is not None
            assert msg.type == MessageType.DISTANCE_TOF
        finally:
            shutdown.set()
            thread.join(timeout=2.0)
        assert not thread.is_alive()

    def test_sensor_loop_sends_messages(self):
        """验证传感器循环会发送消息到总线"""
        from src.processes.sensor_process import sensor_process_loop

        bus = MessageBus()
        shutdown = threading.Event()

        thread = threading.Thread(
            target=sensor_process_loop,
            args=(bus, shutdown, 0.05),
            daemon=True,
        )
        thread.start()
        try:
            msg = bus.receive(timeout=2)
            assert msg is not None, "Sensor loop must emit an initial TOF reading"
            assert msg.source == "sensor"
            assert msg.type == MessageType.DISTANCE_TOF
            assert 400 <= msg.payload["distance_mm"] <= 600
        finally:
            shutdown.set()
            thread.join(timeout=2.0)
        assert not thread.is_alive()

    def test_sensor_process_imports(self):
        """验证传感器进程模块可正确导入"""
        from src.processes import sensor_process
        assert hasattr(sensor_process, "sensor_process_loop")
