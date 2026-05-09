"""VL53L0X TOF Distance Sensor - I2C距离传感器（树莓派5）"""

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("tof_sensor")


class TOFSensor:
    """真实VL53L0X TOF距离传感器，接口与TOFSensorMock一致"""

    def __init__(self):
        import board
        import busio
        import adafruit_vl53l0x

        i2c = busio.I2C(board.SCL, board.SDA)
        self._vl53 = adafruit_vl53l0x.VL53L0X(i2c)
        logger.info("VL53L0X TOF sensor initialized on I2C bus 1")

    def read_distance(self) -> int:
        """返回距离（毫米），无目标时返回8190"""
        try:
            dist = self._vl53.range
            return dist if dist is not None else 8190
        except Exception as e:
            logger.warning(f"TOF read error: {e}")
            return 8190
