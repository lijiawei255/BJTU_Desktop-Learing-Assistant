"""设备管理器 - 根据Mock配置返回真实或Mock设备"""

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("devices")


def _is_mock(device: str) -> bool:
    """判断指定设备是否使用Mock模式"""
    return config.is_mock and config.mock_devices.get(device, True)


def get_pan_servo():
    """获取摄像头云台水平舵机"""
    if _is_mock("servo"):
        from .servo_mock import ServoMock
        return ServoMock("pan_servo")
    from .servo_controller import SingleServo
    return SingleServo(config.get("servo.pan_channel", 2), name="pan_servo")


def get_tilt_servo():
    """获取摄像头云台俯仰舵机"""
    if _is_mock("servo"):
        from .servo_mock import ServoMock
        return ServoMock("tilt_servo")
    from .servo_controller import SingleServo
    return SingleServo(config.get("servo.tilt_channel", 3), name="tilt_servo")


def get_box_servo_left():
    """获取手机盒左舵机"""
    if _is_mock("servo"):
        from .servo_mock import ServoMock
        return ServoMock("box_servo_left")
    from .servo_controller import SingleServo
    return SingleServo(config.get("servo.box_left_channel", 0), name="box_servo_left")


def get_box_servo_right():
    """获取手机盒右舵机"""
    if _is_mock("servo"):
        from .servo_mock import ServoMock
        return ServoMock("box_servo_right")
    from .servo_controller import SingleServo
    return SingleServo(config.get("servo.box_right_channel", 1), name="box_servo_right")


def get_ir_sensor():
    """获取红外避障传感器"""
    if _is_mock("ir"):
        from .ir_sensor_mock import IRSensorMock
        return IRSensorMock()
    from .ir_sensor import IRSensor
    return IRSensor()


def get_tof_sensor():
    """获取VL53L0X TOF距离传感器"""
    if _is_mock("tof"):
        from .tof_sensor_mock import TOFSensorMock
        return TOFSensorMock()
    from .tof_sensor import TOFSensor
    return TOFSensor()


def get_led():
    """获取RGB LED控制器"""
    if _is_mock("led"):
        from .led_mock import LEDMock
        return LEDMock()
    from .led_controller import LEDController
    return LEDController()


def get_camera(pan_servo=None, tilt_servo=None):
    """获取摄像头（可选传入云台舵机以启用PID跟踪）"""
    if _is_mock("camera"):
        from .camera import CameraMock
        return CameraMock(pan_servo, tilt_servo)
    from .camera import CameraController
    return CameraController(pan_servo, tilt_servo)


def get_button():
    """获取物理按钮"""
    if _is_mock("button"):
        from .gpio_button import ButtonMock
        return ButtonMock()
    from .gpio_button import GPIOButton
    return GPIOButton()
