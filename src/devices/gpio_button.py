"""GPIO Button - 物理按钮驱动（树莓派5）+ Mock"""

import time
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("button")


class ButtonMock:
    """模拟物理按钮"""

    def __init__(self):
        self._pressed = False
        logger.info("[MOCK] Button initialized")

    @property
    def is_pressed(self) -> bool:
        return self._pressed

    def simulate_press(self, duration: float = 0.1):
        """模拟按下：duration < 1.0s = 短按，>= 3.0s = 长按"""
        self._pressed = True
        logger.info(f"[MOCK BUTTON] Pressed ({duration:.1f}s)")
        time.sleep(duration)
        self._pressed = False

    def wait_for_press(self, timeout: float = None):
        """模拟等待按下（永远等不到，返回None）"""
        logger.debug("[MOCK BUTTON] Waiting for press...")
        return None

    def close(self):
        pass


class GPIOButton:
    """真实GPIO按钮，支持短按/长按检测"""

    def __init__(self):
        pin = config.get("button.pin", 27)
        debounce = config.get("button.debounce_ms", 50) / 1000.0
        from gpiozero import Button

        self._button = Button(pin, pull_up=True, bounce_time=debounce)
        self._pressed_time = None
        self._on_short_press = None
        self._on_long_press = None

        self._button.when_pressed = self._on_press
        self._button.when_released = self._on_release
        logger.info(f"Button initialized on GPIO{pin}")

    def _on_press(self):
        self._pressed_time = time.time()

    def _on_release(self):
        if self._pressed_time is None:
            return
        duration = time.time() - self._pressed_time
        self._pressed_time = None

        long_threshold = config.get("button.long_press_seconds", 3.0)
        if duration >= long_threshold and self._on_long_press:
            logger.info(f"Long press detected: {duration:.1f}s")
            self._on_long_press()
        elif self._on_short_press:
            logger.info(f"Short press detected: {duration:.1f}s")
            self._on_short_press()

    @property
    def is_pressed(self) -> bool:
        return self._button.is_pressed

    def on_short_press(self, callback):
        self._on_short_press = callback

    def on_long_press(self, callback):
        self._on_long_press = callback

    def close(self):
        if hasattr(self._button, "close"):
            self._button.close()
