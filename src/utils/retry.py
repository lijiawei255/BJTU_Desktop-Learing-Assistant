"""API调用重试与超时工具"""

import time
from functools import wraps
from src.utils.logger import setup_logger

logger = setup_logger("retry")


def with_retry(max_retries: int = 1, backoff_seconds: float = 1.0):
    """装饰器：在函数抛出异常时自动重试。

    Args:
        max_retries: 最大重试次数（不含首次调用）
        backoff_seconds: 每次重试前的等待秒数
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} "
                            f"failed: {e}. Retrying in {backoff_seconds}s..."
                        )
                        time.sleep(backoff_seconds)
            raise last_exc

        return wrapper

    return decorator


def safe_call(func, *args, fallback=None, **kwargs):
    """安全调用函数，异常时返回fallback值而不抛出。"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"safe_call: {func.__name__} failed: {e}")
        return fallback
