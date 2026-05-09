"""LED Mock"""

from src.utils.logger import setup_logger

logger = setup_logger("mock_led")


class LEDMock:
    """模拟LED控制器"""

    COLORS = {
        "blue": (0, 0, 255),
        "green": (0, 255, 0),
        "red": (255, 0, 0),
        "yellow": (255, 255, 0),
        "cyan": (0, 255, 255),
        "purple": (255, 0, 255),
        "orange": (255, 165, 0),
        "white": (255, 255, 255),
        "off": (0, 0, 0),
    }

    def __init__(self):
        self.current_color = "off"
        self.current_pattern = "off"
        logger.info("[MOCK] LED initialized")

    def set_color(self, color: str, pattern: str = "solid"):
        rgb = self.COLORS.get(color, (128, 128, 128))
        self.current_color = color
        self.current_pattern = pattern
        logger.info(f"[MOCK LED] Color={color} ({rgb}), Pattern={pattern}")

    def close(self):
        pass
