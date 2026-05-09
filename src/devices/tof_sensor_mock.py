"""TOF距离传感器Mock"""

import random
from src.utils.logger import setup_logger

logger = setup_logger("mock_tof")


class TOFSensorMock:
    """模拟TOF距离传感器"""

    def __init__(self):
        self._distance = 500  # 默认500mm
        self._pattern = "normal"
        logger.info("[MOCK] TOF Sensor initialized")

    def read_distance(self) -> int:
        if self._pattern == "normal":
            # 正常距离，小幅波动
            self._distance = random.randint(400, 600)
        elif self._pattern == "too_close":
            self._distance = random.randint(250, 350)
        return self._distance

    def set_pattern(self, pattern: str):
        self._pattern = pattern
        logger.info(f"[MOCK TOF] Pattern set to '{pattern}'")

    def close(self):
        pass
