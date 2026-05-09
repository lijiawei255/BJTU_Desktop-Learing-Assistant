"""红外传感器Mock"""

import time
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("mock_ir")


class IRSensorMock:
    """模拟红外传感器（检测手机放入）"""

    def __init__(self):
        self._state = False  # False = 无遮挡, True = 有遮挡
        self._auto_detect = True  # Mock模式下自动模拟检测成功
        logger.info("[MOCK] IR Sensor initialized")

    def read(self) -> bool:
        return self._state

    def set_auto_detect(self, enabled: bool = True):
        """设置是否自动模拟检测成功（False=按真实轮询等待，可测试超时路径）"""
        self._auto_detect = enabled
        logger.info(f"[MOCK IR] auto_detect={'ON' if enabled else 'OFF'}")

    def simulate_phone_inserted(self):
        self._state = True
        logger.info("[MOCK IR] 手机已放入 (phone_inserted)")

    def simulate_phone_removed(self):
        self._state = False
        logger.info("[MOCK IR] 手机已取出 (phone_removed)")

    def wait_for_phone(self, timeout_seconds: float = 60) -> bool:
        """阻塞等待手机稳定放入（Mock模式：立即模拟成功）"""
        debounce_sec = config.get("ir_sensor.ir_debounce_seconds", 3)
        if self._auto_detect:
            time.sleep(0.1)  # 模拟短暂等待
            self.simulate_phone_inserted()
            logger.info(f"[MOCK IR] wait_for_phone OK (mock, debounce={debounce_sec}s)")
            return True
        # 非自动模式：轮询等待
        deadline = time.time() + timeout_seconds
        stable_count = 0
        required = config.get("ir_sensor.debounce_count", 3)
        interval = config.get("ir_sensor.sample_interval_ms", 200) / 1000.0
        while time.time() < deadline:
            if self.read():
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= required:
                time.sleep(1.5)  # 防夹手缓冲
                logger.info(f"[MOCK IR] Phone detected (stable {stable_count} samples)")
                return True
            time.sleep(interval)
        logger.warning(f"[MOCK IR] wait_for_phone timeout ({timeout_seconds}s)")
        return False

    def wait_for_phone_removed(self, timeout_seconds: float = 30) -> bool:
        """阻塞等待手机被取走（Mock模式：立即模拟成功）"""
        if self._auto_detect:
            time.sleep(0.1)
            self.simulate_phone_removed()
            logger.info("[MOCK IR] wait_for_phone_removed OK (mock)")
            return True
        deadline = time.time() + timeout_seconds
        required = config.get("ir_sensor.debounce_count", 3)
        interval = config.get("ir_sensor.sample_interval_ms", 200) / 1000.0
        stable_count = 0
        while time.time() < deadline:
            if not self.read():
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= required:
                logger.info(f"[MOCK IR] Phone removed (stable {stable_count} samples)")
                return True
            time.sleep(interval)
        logger.warning(f"[MOCK IR] wait_for_phone_removed timeout ({timeout_seconds}s)")
        return False

    def close(self):
        pass
