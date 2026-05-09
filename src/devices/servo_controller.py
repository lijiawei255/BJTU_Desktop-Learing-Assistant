"""PCA9685 Servo Controller - 真实舵机驱动（树莓派5）"""

import time
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("servo")

_controller = None  # 模块级PCA9685单例，多个舵机共享同一I2C总线


def _get_controller():
    """懒加载初始化PCA9685 ServoKit控制器"""
    global _controller
    if _controller is None:
        from adafruit_servokit import ServoKit

        addr = config.get("servo.pca9685_addr", 0x40)
        freq = config.get("servo.pwm_frequency", 50)
        _controller = ServoKit(channels=16, address=addr)
        _controller.frequency = freq
        logger.info(f"PCA9685 initialized at 0x{addr:02X}, {freq}Hz")
    return _controller


class SingleServo:
    """单个SG90舵机控制器，封装一个PCA9685通道，接口与ServoMock一致"""

    def __init__(self, channel: int, name: str = "servo"):
        self.name = name
        self._channel = channel
        self._kit = _get_controller()
        self._servo = self._kit.servo[channel]
        try:
            self.current_angle = self._servo.angle or 90.0
        except Exception:
            self.current_angle = 90.0
        logger.info(
            f"Servo '{name}' on channel {channel} initialized at {self.current_angle:.1f}°"
        )

    def set_angle(self, angle: float):
        """设置角度 0-180°，含运动时间模拟"""
        angle = max(0, min(180, angle))
        move_time = abs(angle - self.current_angle) / 90.0
        if move_time > 0:
            time.sleep(min(move_time, 2.0))
        self._servo.angle = angle
        self.current_angle = angle
        logger.info(f"[SERVO] {self.name} (ch{self._channel}) -> {angle:.1f}°")

    def get_angle(self) -> float:
        return self.current_angle
