"""配置管理 - 支持 .env 环境变量和 config.json 文件"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# 加载 .env 文件
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# 默认配置
DEFAULT_CONFIG = {
    "system": {
        "device_name": "amiya",
        "language": "zh",
        "first_run": True,
        "debug_mode": False,
    },
    "audio": {
        "sample_rate": 16000,
        "chunk_size": 480,
        "input_device_index": None,
        "output_device_index": None,
        "vad_aggressiveness": 2,
        "vad_timeout_ms": 1500,
        "max_record_seconds": 15,
        "min_speech_ms": 500,
        "wake_words": ["阿米娅", "Amiya"],
        "wake_cooldown_seconds": 5,
        "wake_confirm_ms": 1500,
        "wake_asr_streaming": True,
    },
    "llm": {
        "provider": "alibaba_bailian",
        "model": "qwen-plus",
        "max_tokens": 512,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_context_rounds": 10,
        "context_token_limit": 3000,
        "summary_max_tokens": 200,
    },
    "asr": {
        "provider": "alibaba_bailian",
        "model": "paraformer-realtime-v2",
        "sample_rate": 16000,
        "format": "pcm",
        "language": "zh",
        "streaming": True,
        "max_audio_seconds": 60,
    },
    "tts": {
        "provider": "alibaba_bailian",
        "model": "cosyvoice-v3-flash",
        "voice": "longanrou_v3",
        "speed": 1.0,
        "pitch": 1.0,
        "volume": 1.0,
        "sample_rate": 24000,
        "output_format": "pcm",
    },
    "vision": {
        "camera_width": 640,
        "camera_height": 480,
        "fps": 15,
        "face_detection_interval": 3,
        "face_confidence_threshold": 0.7,
        "dead_zone_x": 40,
        "dead_zone_y": 30,
        "pan_pid": {"kp": 0.08, "ki": 0.01, "kd": 0.02},
        "tilt_pid": {"kp": 0.06, "ki": 0.008, "kd": 0.015},
        "pan_range": [0, 180],
        "tilt_range": [0, 90],
        "face_lost_timeout": 10,
        "search_timeout": 3,
    },
    "focus_mode": {
        "default_duration_minutes": 25,
        "min_duration_minutes": 5,
        "max_duration_minutes": 120,
        "reminder_intervals": [600, 300, 60],
        "pause_timeout_minutes": 10,
        "waiting_phone_timeout_seconds": 60,
    },
    "posture": {
        "tof_threshold_mm": 350,
        "tof_recovery_mm": 450,
        "confirm_count": 3,
        "cooldown_seconds": 30,
        "sample_interval_ms": 500,
    },
    "ir_sensor": {
        "sample_interval_ms": 200,
        "debounce_count": 3,
    },
    "servo": {
        "box_open_angle": 0,
        "box_close_angle": 90,
        "box_movement_seconds": 1.0,
        "pwm_frequency": 50,
    },
    "led": {
        "pins": {"r": 23, "g": 24, "b": 25},
        "breath_interval_ms": 4000,
    },
    "button": {
        "pin": 5,
        "short_press_max_seconds": 1.0,
        "long_press_seconds": 3.0,
        "debounce_ms": 50,
    },
    "memory": {
        "max_today_sessions": 5,
        "auto_archive_hour": 4,
        "data_dir": "data",
    },
    "mock": {
        "enabled": True,
        "audio": True,
        "camera": True,
        "servo": True,
        "tof": True,
        "ir": True,
        "led": True,
        "button": True,
    },
}


class Config:
    """配置管理类 - 合并文件配置、环境变量和默认值"""

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """加载配置：默认值 <- 文件配置 <- 环境变量"""
        config = DEFAULT_CONFIG.copy()

        # 尝试加载 config.json
        config_path = PROJECT_ROOT / "data" / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                self._deep_update(config, file_config)

        # 环境变量覆盖（仅限阿里云百炼）
        if os.getenv("ALIBABA_API_KEY"):
            config.setdefault("api_keys", {})
            config["api_keys"]["alibaba"] = os.getenv("ALIBABA_API_KEY")

        return config

    def _deep_update(self, base: dict, update: dict):
        """递归更新字典"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def get(self, key_path: str, default=None):
        """通过点路径获取配置，如 get('llm.model')"""
        keys = key_path.split(".")
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value):
        """设置配置并保存到文件"""
        keys = key_path.split(".")
        target = self._config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        self._save_config()

    def _save_config(self):
        """保存当前配置到 data/config.json"""
        config_path = PROJECT_ROOT / "data" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    @property
    def is_mock(self) -> bool:
        """是否启用 Mock 模式"""
        return self.get("mock.enabled", True)

    @property
    def mock_devices(self) -> dict:
        """获取各设备的 Mock 开关状态"""
        return self.get("mock", {})

    @property
    def api_key_alibaba(self) -> Optional[str]:
        return self.get("api_keys.alibaba")


# 全局配置实例
config = Config()
