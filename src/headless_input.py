"""无头模式输入系统 — 替代stdin input()，支持脚本化队列输入进行自动化测试。

检测逻辑（优先级从高到低）：
  1. 配置 mock.headless = true   → 强制无头模式
  2. 配置 mock.headless = false  → 强制交互模式
  3. sys.stdin.isatty() = False  → 自动无头模式（管道/测试环境）
  4. 其他情况                     → 交互模式（回退到 input()）
"""

import sys
import threading
import queue
from typing import Optional, List
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("headless_input")


class HeadlessInput:
    """线程安全的无头输入单例，用于Mock模式自动化测试。"""

    _instance: Optional["HeadlessInput"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._queue = queue.Queue()
                    instance._default_timeout = 30.0
                    # 检测模式：配置显式设置 > 自动检测
                    explicit = config.get("mock.headless")
                    if explicit is True:
                        instance._enabled = True
                    elif explicit is False:
                        instance._enabled = False
                    else:
                        instance._enabled = not sys.stdin.isatty()
                    cls._instance = instance
                    if instance._enabled:
                        logger.info("Headless input mode ENABLED (automated testing)")
        return cls._instance

    @property
    def enabled(self) -> bool:
        return self._enabled

    def feed(self, text: str) -> None:
        """向队列推送一条脚本化输入（线程安全）。"""
        self._queue.put(text)

    def feed_sequence(self, texts: List[str]) -> None:
        """批量推送输入序列，保持顺序。"""
        for t in texts:
            self._queue.put(t)

    def get_input(self, prompt: str = "") -> str:
        """获取下一条输入。
        无头模式：从队列取，超时返回空串（空串=触发唤醒，与现有Mock约定一致）。
        交互模式：回退到内置 input()。
        """
        if not self._enabled:
            return input(prompt)
        try:
            value = self._queue.get(timeout=self._default_timeout)
            logger.debug(f"[HEADLESS] Input: '{value[:40]}...'")
            return value
        except queue.Empty:
            logger.warning("[HEADLESS] Input queue timeout — returning empty")
            return ""

    def clear(self) -> None:
        """清空所有待处理输入。"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


# 模块级单例
headless_input = HeadlessInput()
