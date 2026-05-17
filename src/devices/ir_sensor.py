"""IR Obstacle Avoidance Sensor — 标准红外避障传感器 (3.3V供电, 单IO输出)

硬件行为：
  - 无障碍物: 传感器输出 HIGH → GPIO读取 HIGH → Button.is_pressed = False
  - 有障碍物: 传感器输出 LOW  → GPIO读取 LOW  → Button.is_pressed = True
  - 接线: GPIO 17, 内部上拉(pull_up=True)
"""

import time
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("ir_sensor")


class IRSensor:
    """标准红外避障传感器 — 遮挡时输出LOW，gpiozero.Button(pull_up) 将LOW映射为is_pressed=True"""

    def __init__(self):
        pin = config.get("ir_sensor.pin", 17)
        from gpiozero import Button

        self._sensor = Button(pin, pull_up=True)
        logger.info(f"IR Obstacle Sensor initialized on GPIO{pin} (pull_up, LOW=obstacle)")

    def read(self) -> bool:
        """True = 有遮挡（手机存在），False = 无遮挡"""
        return self._sensor.is_pressed

    def wait_for_phone(self, timeout_seconds: float = 60) -> bool:
        """阻塞等待手机稳定放入，含防夹手缓冲"""
        required = config.get("ir_sensor.debounce_count", 3)
        interval = config.get("ir_sensor.sample_interval_ms", 200) / 1000.0
        deadline = time.time() + timeout_seconds
        stable_count = 0
        while time.time() < deadline:
            if self.read():
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= required:
                time.sleep(1.5)  # 防夹手缓冲
                logger.info(f"Phone detected (stable {stable_count} samples)")
                return True
            time.sleep(interval)
        logger.warning(f"wait_for_phone timeout ({timeout_seconds}s)")
        return False

    def wait_for_phone_removed(self, timeout_seconds: float = 30) -> bool:
        """阻塞等待手机被取走"""
        required = config.get("ir_sensor.debounce_count", 3)
        interval = config.get("ir_sensor.sample_interval_ms", 200) / 1000.0
        deadline = time.time() + timeout_seconds
        stable_count = 0
        while time.time() < deadline:
            if not self.read():
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= required:
                logger.info(f"Phone removed (stable {stable_count} samples)")
                return True
            time.sleep(interval)
        logger.warning(f"wait_for_phone_removed timeout ({timeout_seconds}s)")
        return False

    def close(self):
        if hasattr(self._sensor, "close"):
            self._sensor.close()
