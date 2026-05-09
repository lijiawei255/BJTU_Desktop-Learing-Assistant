"""舵机Mock - 打印角度到日志"""

import time
from src.utils.logger import setup_logger

logger = setup_logger("mock_servo")


class ServoMock:
    """模拟舵机控制器"""

    def __init__(self, name: str = "servo"):
        self.name = name
        self.current_angle = 0.0
        logger.info(f"[MOCK] Servo '{name}' initialized")

    def set_angle(self, angle: float):
        """设置角度"""
        angle = max(0, min(180, angle))
        # 模拟运动时间
        move_time = abs(angle - self.current_angle) / 90.0  # 90度/秒
        if move_time > 0:
            time.sleep(min(move_time, 2.0))
        self.current_angle = angle
        logger.info(f"[MOCK SERVO] {self.name} -> {angle:.1f}°")

    def get_angle(self) -> float:
        return self.current_angle

    def close(self):
        pass
