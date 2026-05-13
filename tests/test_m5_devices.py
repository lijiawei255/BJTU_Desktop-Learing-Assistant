"""Milestone 5 设备层与工具执行器测试"""

from src.config import config
from src.devices.servo_mock import ServoMock
from src.devices.ir_sensor_mock import IRSensorMock
from src.devices.tof_sensor_mock import TOFSensorMock
from src.devices.led_mock import LEDMock
from src.tool_executor import ToolExecutor


class TestServoMock:
    def test_init_defaults(self):
        s = ServoMock("test")
        assert s.name == "test"
        assert s.current_angle == 0.0

    def test_set_angle_clamping(self):
        s = ServoMock("test")
        s.set_angle(-10)
        assert s.current_angle == 0.0
        s.set_angle(200)
        assert s.current_angle == 180.0

    def test_set_angle_valid(self):
        s = ServoMock("test")
        s.set_angle(90)
        assert s.current_angle == 90.0

    def test_get_angle(self):
        s = ServoMock("test")
        s.set_angle(45)
        assert s.get_angle() == 45.0


class TestIRSensorMock:
    def test_init_state_false(self):
        ir = IRSensorMock()
        assert ir.read() is False

    def test_simulate_phone_inserted(self):
        ir = IRSensorMock()
        ir.simulate_phone_inserted()
        assert ir.read() is True

    def test_simulate_phone_removed(self):
        ir = IRSensorMock()
        ir.simulate_phone_inserted()
        ir.simulate_phone_removed()
        assert ir.read() is False


class TestTOFSensorMock:
    def test_read_distance_normal(self):
        tof = TOFSensorMock()
        tof.set_pattern("normal")
        for _ in range(10):
            d = tof.read_distance()
            assert 400 <= d <= 600

    def test_read_distance_too_close(self):
        tof = TOFSensorMock()
        tof.set_pattern("too_close")
        for _ in range(10):
            d = tof.read_distance()
            assert 250 <= d <= 350

    def test_default_distance(self):
        tof = TOFSensorMock()
        assert tof._distance == 500


class TestLEDMock:
    def test_colors_complete(self):
        expected = {"blue", "green", "red", "yellow", "cyan", "purple", "orange", "white", "off"}
        assert set(LEDMock.COLORS.keys()) == expected

    def test_set_color_updates_state(self):
        led = LEDMock()
        led.set_color("red", "solid")
        assert led.current_color == "red"
        assert led.current_pattern == "solid"

    def test_set_color_default_pattern(self):
        led = LEDMock()
        led.set_color("blue")
        assert led.current_pattern == "solid"

    def test_init_state(self):
        led = LEDMock()
        assert led.current_color == "off"
        assert led.current_pattern == "off"


class TestDeviceManager:
    def test_get_pan_servo_returns_mock(self):
        from src.devices import get_pan_servo
        s = get_pan_servo()
        assert isinstance(s, ServoMock)
        assert s.name == "pan_servo"

    def test_get_tilt_servo_returns_mock(self):
        from src.devices import get_tilt_servo
        s = get_tilt_servo()
        assert isinstance(s, ServoMock)
        assert s.name == "tilt_servo"

    def test_get_box_servos_return_mock(self):
        from src.devices import get_box_servo_left, get_box_servo_right
        sl = get_box_servo_left()
        sr = get_box_servo_right()
        assert isinstance(sl, ServoMock)
        assert isinstance(sr, ServoMock)

    def test_get_ir_returns_mock(self):
        from src.devices import get_ir_sensor
        ir = get_ir_sensor()
        assert isinstance(ir, IRSensorMock)

    def test_get_tof_returns_mock(self):
        from src.devices import get_tof_sensor
        tof = get_tof_sensor()
        assert isinstance(tof, TOFSensorMock)

    def test_get_led_returns_mock(self):
        from src.devices import get_led
        led = get_led()
        assert isinstance(led, LEDMock)

    def test_get_camera_returns_mock(self):
        from src.devices import get_camera
        from src.devices.camera import CameraMock
        cam = get_camera()
        assert isinstance(cam, CameraMock)

    def test_get_button_returns_mock(self):
        from src.devices import get_button
        from src.devices.gpio_button import ButtonMock
        btn = get_button()
        assert isinstance(btn, ButtonMock)


class TestToolExecutor:
    def setup_method(self):
        self.tools = ToolExecutor()
        # Mock IR默认自动检测成功，确保测试快速通过

    def test_set_focus_mode(self):
        result = self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        assert result["success"] is True
        assert "25分钟" in result["result"]
        assert self.tools.state_ctrl.is_active is True

    def test_open_phone_box_temporary(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        # 暂停：mock IR自动模拟 取走→放回，所以会完整走完暂停→恢复流程
        result = self.tools.execute("open_phone_box", {"reason": "temporary"})
        assert result["success"] is True
        # 自动恢复后 is_paused 为 False
        assert self.tools.state_ctrl.is_paused is False

    def test_open_phone_box_complete(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        result = self.tools.execute("open_phone_box", {"reason": "complete"})
        assert result["success"] is True
        assert self.tools.state_ctrl.is_active is False

    def test_end_focus_mode(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        result = self.tools.execute("end_focus_mode", {})
        assert result["success"] is True
        assert self.tools.state_ctrl.is_active is False
        assert self.tools.state_ctrl.is_paused is False

    def test_end_focus_mode_inactive(self):
        # State is IDLE by default, so end_focus_mode should fail
        result = self.tools.execute("end_focus_mode", {})
        assert result["success"] is False

    def test_set_focus_mode_conflict(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        result = self.tools.execute("set_focus_mode", {"duration_minutes": 10})
        assert result["success"] is False
        assert "当前专注模式还在进行中" in result["result"]
        assert self.tools.state_ctrl.is_active is True

    def test_get_focus_status_inactive(self):
        result = self.tools.execute("get_focus_status", {})
        assert result["success"] is True
        assert "未开启" in result["result"]

    def test_get_focus_status_active(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 30})
        result = self.tools.execute("get_focus_status", {})
        assert result["success"] is True
        assert "30分" in result["result"] or "专注中" in result["result"]

    def test_get_status_for_llm_inactive(self):
        status = self.tools.get_status_for_llm()
        assert "未开启" in status

    def test_get_status_for_llm_active(self):
        self.tools.execute("set_focus_mode", {"duration_minutes": 25})
        status = self.tools.get_status_for_llm()
        assert "专注中" in status

    def test_set_user_nickname(self):
        result = self.tools.execute("set_user_nickname", {"nickname": "博士"})
        assert result["success"] is True
        assert self.tools.user_nickname == "博士"

    def test_unknown_function(self):
        result = self.tools.execute("unknown_function", {})
        assert result["success"] is False

    def test_nickname_persists_to_config(self):
        self.tools.execute("set_user_nickname", {"nickname": "测试用户"})
        assert config.get("system.nickname") == "测试用户"
        config.set("system.nickname", "博士")

    def test_focus_timer_start_stop(self):
        self.tools.timer.start(60)
        assert self.tools.timer.is_running
        self.tools.timer.stop()
        assert not self.tools.timer.is_running

    def test_focus_timer_pause_resume(self):
        self.tools.timer.start(60)
        self.tools.timer.pause()
        assert not self.tools.timer.is_running
        self.tools.timer.resume()
        assert self.tools.timer.is_running
        self.tools.timer.stop()

    def test_available_tools_count(self):
        from src.llm_client import AVAILABLE_TOOLS
        assert len(AVAILABLE_TOOLS) == 5
        names = [t["function"]["name"] for t in AVAILABLE_TOOLS]
        assert "end_focus_mode" in names
        assert "set_focus_mode" in names
