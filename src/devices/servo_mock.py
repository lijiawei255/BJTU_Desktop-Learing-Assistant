"""舵机Mock - 打印角度到日志"""

import time
from src.utils.logger import setup_logger

logger = setup_logger("mock_servo")


class ServoMock:
    """模拟舵机控制器"""

    def __init__(self, name: str = "servo",
                 angle_min: float = 0.0, angle_max: float = 180.0):
        self.name = name
        self.current_angle = 0.0
        self._angle_min = angle_min
        self._angle_max = angle_max
        logger.info(f"[MOCK] Servo '{name}' initialized (limit: {angle_min}°-{angle_max}°)")

    def set_angle(self, angle: float):
        """设置角度（自动钳位到限位范围）"""
        angle = max(self._angle_min, min(self._angle_max, angle))
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
