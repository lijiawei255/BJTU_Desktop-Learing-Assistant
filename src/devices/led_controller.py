"""RGB LED Controller - GPIO PWM LED驱动（树莓派5）"""

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("led")


class LEDController:
    """真实RGB LED控制器，接口与LEDMock一致"""

    COLORS = {
        "blue": (0, 0, 1),
        "green": (0, 1, 0),
        "red": (1, 0, 0),
        "yellow": (1, 1, 0),
        "cyan": (0, 1, 1),
        "purple": (1, 0, 1),
        "orange": (1, 0.65, 0),
        "white": (1, 1, 1),
        "off": (0, 0, 0),
    }

    def __init__(self):
        r = config.get("led.pins.r", 23)
        g = config.get("led.pins.g", 24)
        b = config.get("led.pins.b", 25)
        self.current_color = "off"
        self.current_pattern = "off"
        from gpiozero import RGBLED

        self._led = RGBLED(r, g, b, active_high=True)
        self._led.color = (0, 0, 0)
        logger.info(f"RGB LED initialized on R={r}, G={g}, B={b}")

    def set_color(self, color: str, pattern: str = "solid"):
        """设置颜色和模式（solid/blink/breath/off）"""
        self.current_color = color
        self.current_pattern = pattern
        rgb = self.COLORS.get(color, (0.5, 0.5, 0.5))
        logger.info(f"[LED] Color={color} ({rgb}), Pattern={pattern}")

        if pattern == "off":
            self._led.color = (0, 0, 0)
        else:
            self._led.color = rgb
            if pattern == "blink":
                self._led.blink(on_time=0.5, off_time=0.5)

    def off(self):
        self._led.color = (0, 0, 0)
        self.current_color = "off"
        self.current_pattern = "off"

    def close(self):
        self.off()
        if hasattr(self._led, "close"):
            self._led.close()
