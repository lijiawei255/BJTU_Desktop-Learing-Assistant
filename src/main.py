"""Amiya 桌面学习助手 - 主程序入口"""

import signal
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("main")


class AmiyaSystem:
    """系统主类"""

    def __init__(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("=" * 50)
        logger.info("Amiya Desktop Learning Assistant Starting...")
        logger.info(f"Project root: {PROJECT_ROOT}")
        logger.info(f"Mock mode: {config.is_mock}")
        logger.info("=" * 50)

    def _handle_signal(self, signum, frame):
        """处理 Ctrl+C 信号"""
        logger.info("Received stop signal.")
        self._running = False

    def run(self):
        """主循环"""
        logger.info("System running. Press Ctrl+C to stop.")
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Received stop signal.")
        finally:
            self.shutdown()

    def shutdown(self):
        """优雅关闭"""
        logger.info("Shutting down...")
        logger.info("Goodbye!")


def main():
    app = AmiyaSystem()
    app.run()


if __name__ == "__main__":
    main()
