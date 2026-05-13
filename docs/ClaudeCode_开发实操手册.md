# 桌面学习助手（Amiya）Claude Code 开发实操手册

> 本文档配套《开发规格文档 v1.1》使用，供 Claude Code 按步骤从零搭建项目并调试。  
> 当前处于 **阶段1（PC模拟开发）**，所有硬件交互使用 Mock 实现。  
> 开发环境：Windows 11 / VSCode / Anaconda3 / Python 3.11

---

## 0. 如何使用本文档

1. **每次只执行一个里程碑**，完成后验证通过再进入下一个。
2. **每个里程碑末尾都有"验证命令"**，运行后输出符合预期才算通过。
3. **遇到报错先看该章节的"常见问题"**，仍无法解决再回退到上一个里程碑检查。
4. **所有代码可直接复制到文件中使用**，文件路径以项目根目录 `/home/pi/amiya/` 为基准（PC开发时可用任意目录）。
5. **`.env` 文件不要提交到 Git**，API Key 只存本地。

> **重要提醒：以下各里程碑中的代码清单反映开发早期的设计快照。实际源码已在此基础上演进并优化。模型名称、默认配置值、工具函数清单、架构细节等以 `src/` 中的实际代码为准。本文档的核心概念和架构思路仍然适用。**

---

## 1. 环境准备（一次性）

### 1.1 安装 Anaconda 并创建环境

```bash
# 打开 Anaconda Prompt（或终端）
conda create -n amiya python=3.11 -y
conda activate amiya

# 安装核心依赖（全部中国大陆可用）
pip install webrtcvad==2.0.10
pip install pyaudio numpy opencv-python
pip install dashscope==1.14 pydantic python-dotenv requests
pip install pytest pytest-asyncio black

# 验证安装
python -c "import webrtcvad, pyaudio, dashscope, cv2; print('OK')"
```

**国内用户 pip 加速建议：**
```bash
# 使用清华镜像源（中国大陆访问更快）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
# 或临时使用
pip install <package> -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**预期输出**：`OK`

### 1.2 获取必要密钥

1. **阿里云百炼**：访问 https://bailian.console.aliyun.com/ 创建 API Key（中国大陆可直接访问）
2. 在项目根目录创建 `.env` 文件：

```bash
ALIBABA_API_KEY=sk-your-bailian-api-key
```

### 1.3 创建项目目录

```bash
# 在 PC 上选择工作目录（示例用 D:\projects\amiya）
mkdir -p amiya/{src/{processes,devices,utils,models},system_prompts,data/session_history,logs,scripts}
touch amiya/src/__init__.py
touch amiya/src/processes/__init__.py
touch amiya/src/devices/__init__.py
touch amiya/src/utils/__init__.py
```

---

## 里程碑 1：项目骨架与配置系统

### 目标
搭建可运行的项目骨架，实现配置加载、日志系统、目录结构。

### 1.1 配置文件

创建 `src/config.py`：

```python
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
        "default_duration_minutes": 40,
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
        "pin": 27,
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
```

### 1.2 日志系统

创建 `src/utils/logger.py`：

```python
"""日志配置"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """创建并配置日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f'amiya_{datetime.now().strftime("%Y%m%d")}.log'

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
```

### 1.3 主入口文件

创建 `src/main.py`（初始骨架）：

```python
"""Amiya 桌面学习助手 - 主程序入口"""

import signal
import sys
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
        logger.info("=" * 50)
        logger.info("Amiya Desktop Learning Assistant Starting...")
        logger.info(f"Project root: {PROJECT_ROOT}")
        logger.info(f"Mock mode: {config.is_mock}")
        logger.info("=" * 50)

    def run(self):
        """主循环"""
        logger.info("System running. Press Ctrl+C to stop.")
        try:
            while True:
                signal.pause()
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
```

### 1.4 人格提示词

创建 `system_prompts/amiya_persona.txt`：

```
你是阿米娅（Amiya），来自《明日方舟》的角色。你是罗德岛的公开领袖，温柔、坚强、关心他人，有时会展现与年龄不符的成熟。

与用户交互时：
1. 语气温柔亲切，称呼用户为"{nickname}"（如果未设置则询问）
2. 关心用户的学习状态，适时给予鼓励
3. 检测到用户走神时，温柔提醒："{nickname}，现在还不可以休息哦"
4. 用户坐姿不端正时，关切提醒："{nickname}，离桌面远一点对眼睛比较好"
5. 用户完成专注模式时，真诚夸奖："{nickname}很努力了，休息一下吧"
6. 回答学习问题时耐心详细，像朋友一样
7. 允许用户随时更改称呼
8. 只有当用户明确呼唤"阿米娅"或"Amiya"时系统才会响应（由VAD+ASR唤醒检测处理，你无需判断）
9. 当用户表示要离开时，礼貌道别，等待用户回来

当前时间：{datetime}
用户称呼：{nickname}
```

### 验证命令

```bash
cd amiya
conda activate amiya
python -m src.main
```

**预期输出**：
```
==================================================
Amiya Desktop Learning Assistant Starting...
Project root: D:\projects\amiya
Mock mode: True
==================================================
System running. Press Ctrl+C to stop.
```

按 `Ctrl+C` 后应看到 `Shutting down...` 并正常退出。

### 常见问题

| 问题 | 解决 |
|------|------|
| `ModuleNotFoundError: No module named 'src'` | 确认在 `amiya` 目录下运行，且 `src/__init__.py` 存在 |
| `dotenv` 相关报错 | 运行 `pip install python-dotenv` |

---

## 里程碑 2：音频管道 + VAD语音检测 + ASR唤醒确认

### 目标
实现音频采集/播放、VAD语音活动检测、基于ASR的唤醒词确认三大基础能力。

### 说明
由于 Picovoice/Porcupine 在中国大陆个人开发者场景下注册受限，本项目采用 **webrtcvad 本地检测语音活动 + Paraformer-Realtime-V2 流式识别确认唤醒词** 的方案。该方案无需任何海外注册，纯中国大陆可用。

### 2.1 音频处理模块（含Mock）

创建 `src/audio_handler.py`：

```python
"""音频采集与播放 - 支持真实PyAudio和Mock模式"""

import time
import wave
import tempfile
from pathlib import Path
from typing import Optional, Callable
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("audio")


class AudioHandler:
    """音频处理器 - 录音和播放"""

    def __init__(self):
        self.sample_rate = config.get("audio.sample_rate", 16000)
        self.chunk_size = config.get("audio.chunk_size", 480)
        self._input_device = config.get("audio.input_device_index")
        self._output_device = config.get("audio.output_device_index")
        self._pa = None
        self._stream_in = None
        self._stream_out = None

        if not config.is_mock or not config.mock_devices.get("audio"):
            self._init_pyaudio()
        else:
            logger.info("[MOCK] AudioHandler in mock mode")

    def _init_pyaudio(self):
        """初始化 PyAudio"""
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
            logger.info(f"PyAudio initialized. Devices: {self._pa.get_device_count()}")
        except Exception as e:
            logger.error(f"PyAudio init failed: {e}")
            self._pa = None

    def record_until_silence(
        self,
        vad_detector,
        max_seconds: int = 15,
        min_speech_ms: int = 500,
    ) -> Optional[bytes]:
        """
        录音直到检测到语音结束（通过VAD）
        返回: PCM音频数据（16kHz, 16bit, mono）
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_record()

        if not self._pa:
            logger.error("PyAudio not available")
            return None

        import pyaudio

        frames = []
        speech_started = False
        silence_frames = 0
        silence_threshold = int(
            (config.get("audio.vad_timeout_ms", 1500) / 1000) * self.sample_rate / self.chunk_size
        )
        min_frames = int((min_speech_ms / 1000) * self.sample_rate / self.chunk_size)
        max_frames = int(max_seconds * self.sample_rate / self.chunk_size)

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=self._input_device,
            frames_per_buffer=self.chunk_size,
        )

        logger.debug("Recording started...")
        frame_count = 0

        try:
            while frame_count < max_frames:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                frames.append(data)
                frame_count += 1

                # VAD检测
                is_speech = vad_detector.is_speech(data, self.sample_rate)

                if is_speech:
                    speech_started = True
                    silence_frames = 0
                else:
                    if speech_started:
                        silence_frames += 1

                # 检测到足够长的静音，且已采集到最小语音长度
                if speech_started and silence_frames >= silence_threshold and frame_count >= min_frames:
                    logger.debug(f"Recording stopped by silence detection ({silence_frames} silent frames)")
                    break

                # 从未检测到语音但达到超时
                if not speech_started and frame_count >= max_frames:
                    logger.debug("No speech detected, discarding")
                    return None

        finally:
            stream.stop_stream()
            stream.close()

        if not speech_started or frame_count < min_frames:
            logger.debug("Speech too short or not detected")
            return None

        audio_data = b"".join(frames)
        logger.info(f"Recorded {len(frames)} frames ({len(audio_data)} bytes)")
        return audio_data

    def play_audio(self, audio_data: bytes):
        """播放PCM音频数据"""
        if config.is_mock and config.mock_devices.get("audio"):
            self._mock_play(audio_data)
            return

        if not self._pa:
            logger.error("PyAudio not available")
            return

        import pyaudio

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            output=True,
            output_device_index=self._output_device,
        )

        try:
            stream.write(audio_data)
            logger.info(f"Played {len(audio_data)} bytes")
        finally:
            stream.stop_stream()
            stream.close()

    def _mock_record(self) -> Optional[bytes]:
        """Mock录音：从用户输入模拟，或返回预置音频"""
        logger.info("[MOCK RECORD] Simulating audio recording...")
        # 方案1：等待用户按Enter模拟"说话结束"
        input("[MOCK] 按 Enter 模拟用户说话结束（或输入文字直接作为ASR结果）: ")
        # 返回空数据，由上层 Mock ASR 处理文字输入
        return b"\x00" * 1600  # 返回100ms静音作为占位

    def _mock_play(self, audio_data: bytes):
        """Mock播放：保存到日志"""
        logger.info(f"[MOCK PLAY] 播放音频: {len(audio_data)} bytes")
        # 保存到文件便于检查
        mock_dir = Path("logs/mock_audio")
        mock_dir.mkdir(exist_ok=True)
        timestamp = int(time.time())
        with open(mock_dir / f"tts_{timestamp}.pcm", "wb") as f:
            f.write(audio_data)

    def save_wav(self, audio_data: bytes, filepath: str):
        """保存PCM数据为WAV文件（调试用）"""
        import wave
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data)
        logger.debug(f"Saved WAV: {filepath}")

    def __del__(self):
        if self._pa:
            self._pa.terminate()
```

### 2.2 VAD包装器

创建 `src/vad_handler.py`：

```python
"""VAD (Voice Activity Detection) 包装器"""

import webrtcvad
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("vad")


class VADHandler:
    """WebRTC VAD 包装器"""

    def __init__(self):
        aggressiveness = config.get("audio.vad_aggressiveness", 2)
        self.vad = webrtcvad.Vad(aggressiveness)
        logger.info(f"VAD initialized with aggressiveness={aggressiveness}")

    def is_speech(self, audio_frame: bytes, sample_rate: int = 16000) -> bool:
        """
        判断音频帧是否包含语音
        audio_frame: bytes, 必须是 10/20/30ms 的 PCM 16bit 数据
        """
        try:
            return self.vad.is_speech(audio_frame, sample_rate)
        except Exception as e:
            logger.warning(f"VAD error: {e}")
            return False

    @staticmethod
    def frame_duration_ms(frame_bytes: bytes, sample_rate: int = 16000) -> int:
        """计算音频帧时长（毫秒）"""
        # 16bit = 2 bytes per sample
        num_samples = len(frame_bytes) // 2
        return int(num_samples * 1000 / sample_rate)
```

### 2.3 唤醒词检测器（VAD + 流式ASR方案）

创建 `src/wake_word_detector.py`：

```python
"""唤醒词检测 - 基于 webrtcvad + Paraformer-Realtime-V2 流式识别"""

import time
import threading
from collections import deque
from typing import Optional, Callable
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("wake_word")


class WakeWordDetector:
    """唤醒词检测器 - 使用VAD检测语音 + ASR流式识别确认唤醒词"""

    # 唤醒词列表（小写，用于匹配）
    WAKE_WORDS = ["阿米娅", "amiya", "amia", "阿米亚", "am iya", "a miya"]
    # 唤醒后冷却时间（秒）
    COOLDOWN_SECONDS = 5

    def __init__(self):
        self.sample_rate = config.get("audio.sample_rate", 16000)
        self.chunk_size = config.get("audio.chunk_size", 480)  # 30ms
        self.vad_aggressiveness = config.get("audio.vad_aggressiveness", 2)
        self._last_wake_time = 0.0
        self._is_listening = True
        self._asr_client = None
        logger.info("WakeWordDetector initialized (VAD + ASR-based)")

    def check_wake_word_in_text(self, text: str) -> bool:
        """检查ASR文本中是否包含唤醒词"""
        if not text:
            return False
        text_lower = text.lower().strip()
        for word in self.WAKE_WORDS:
            if word in text_lower:
                return True
        return False

    def is_in_cooldown(self) -> bool:
        """检查是否在唤醒冷却期"""
        return (time.time() - self._last_wake_time) < self.COOLDOWN_SECONDS

    def mark_awake(self):
        """标记唤醒成功，启动冷却计时"""
        self._last_wake_time = time.time()
        logger.info("Wake word confirmed! Entering cooldown.")

    def listen_for_wake_word(
        self,
        audio_handler,
        vad_handler,
        asr_client=None,
        timeout_seconds: float = None,
    ) -> bool:
        """
        监听唤醒词（阻塞方法）
        流程: VAD检测语音 → 收集音频 → ASR识别 → 检查唤醒词
        返回: 是否唤醒成功
        """
        # Mock模式：直接终端输入模拟
        if config.is_mock:
            return self._mock_listen()

        # 真实模式：VAD + 流式ASR
        logger.info("Listening for wake word (VAD + ASR)...")
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
            )

            audio_buffer = deque(maxlen=200)  # 约6秒音频
            speech_started = False
            silence_frames = 0
            silence_threshold = 15  # 450ms静音判定结束
            speech_frames = 0
            min_speech_frames = 10  # 300ms最小语音

            while True:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                is_speech = vad_handler.is_speech(data, self.sample_rate)

                if is_speech:
                    speech_started = True
                    silence_frames = 0
                    speech_frames += 1
                else:
                    if speech_started:
                        silence_frames += 1

                # 缓存音频（仅在检测到语音后）
                if speech_started:
                    audio_buffer.append(data)

                # 检测到足够语音，尝试ASR确认唤醒词
                if speech_started and speech_frames >= min_speech_frames:
                    # 收集约1.5秒音频做唤醒确认
                    if len(audio_buffer) >= 50:  # 50 * 30ms = 1.5s
                        audio_data = b"".join(audio_buffer)
                        # 简化版：使用非流式ASR做唤醒确认（生产环境改用流式）
                        if asr_client:
                            result = asr_client.recognize_once(audio_data)
                            if result and self.check_wake_word_in_text(result):
                                logger.info(f"Wake word detected via ASR: {result}")
                                stream.stop_stream()
                                stream.close()
                                pa.terminate()
                                return True
                        # 未检测到唤醒词，清空缓冲区继续监听
                        audio_buffer.clear()
                        speech_started = False
                        speech_frames = 0

                # 超时检测（静音过久则重置）
                if silence_frames > silence_threshold and speech_started:
                    audio_buffer.clear()
                    speech_started = False
                    speech_frames = 0
                    silence_frames = 0

        except Exception as e:
            logger.error(f"Wake word listen error: {e}")
            return False

    def _mock_listen(self) -> bool:
        """Mock模式：终端输入模拟唤醒"""
        user_input = input("[MOCK] 输入唤醒词后按 Enter（直接按Enter模拟触发）: ")
        if user_input.strip().lower() in self.WAKE_WORDS or user_input.strip() == "":
            logger.info("[MOCK] Wake word triggered")
            return True
        logger.info("[MOCK] Not a wake word, continuing listen...")
        return self._mock_listen()
```

### 2.4 更新 main.py 测试音频管道

修改 `src/main.py`，添加里程碑2的测试逻辑：

```python
"""Amiya 桌面学习助手 - 主程序入口"""

import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.utils.logger import setup_logger
from src.audio_handler import AudioHandler
from src.vad_handler import VADHandler
from src.wake_word_detector import WakeWordDetector

logger = setup_logger("main")


class AmiyaSystem:
    def __init__(self):
        logger.info("=" * 50)
        logger.info("Amiya Desktop Learning Assistant Starting...")
        logger.info(f"Mock mode: {config.is_mock}")
        logger.info("=" * 50)

        # 初始化音频组件
        self.audio = AudioHandler()
        self.vad = VADHandler()
        self.wake = WakeWordDetector()

    def run(self):  # 实际代码中为 run() → _run_voice_loop()
        """里程碑2测试：VAD语音检测 + ASR唤醒确认 + 录音"""
        logger.info("\n[Milestone 2 Test] VAD + ASR Wake Word + Recording")
        logger.info("Step 1: Waiting for wake word (VAD + ASR)...")

        # 测试唤醒（Mock模式下输入唤醒词模拟）
        detected = self.wake.listen_for_wake_word(self.audio, self.vad)
        if not detected:
            logger.warning("Wake word not detected")
            return

        logger.info("Step 2: Recording user speech...")
        audio_data = self.audio.record_until_silence(self.vad)

        if audio_data:
            logger.info(f"Recorded {len(audio_data)} bytes of audio")
            # 保存调试用
            self.audio.save_wav(audio_data, "logs/test_recording.wav")
            logger.info("Saved to logs/test_recording.wav")
        else:
            logger.info("No speech detected or recording cancelled")

    def run(self):
        """主循环"""
        try:
            self.run()  # 实际代码中为 run() → _run_voice_loop()
            logger.info("\nTest complete. Exiting.")
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.shutdown()

    def shutdown(self):
        logger.info("Shutting down...")


def main():
    app = AmiyaSystem()
    app.run()


if __name__ == "__main__":
    main()
```

### 验证命令

```bash
cd amiya
conda activate amiya
python -m src.main
```

**预期输出（Mock模式）**：
```
==================================================
Amiya Desktop Learning Assistant Starting...
Mock mode: True
==================================================

[Milestone 2 Test] VAD + ASR Wake Word + Recording
Step 1: Waiting for wake word (VAD + ASR)...
[MOCK] 输入唤醒词后按 Enter（直接按Enter模拟触发）: 阿米娅    <-- 你输入"阿米娅"
[MOCK] Wake word triggered
Wake word confirmed! Entering cooldown.
Step 2: Recording user speech...
[MOCK RECORD] Simulating audio recording...
[MOCK] 按 Enter 模拟用户说话结束... <-- 你再按Enter
Recorded 1600 bytes of audio
Saved to logs/test_recording.wav

Test complete. Exiting.
```

### 常见问题

| 问题 | 解决 |
|------|------|
| `webrtcvad` 安装失败（Windows） | 用 conda 安装：`conda install -c conda-forge webrtcvad` |
| PyAudio 找不到麦克风 | 运行 `python -c "import pyaudio; pa=pyaudio.PyAudio(); [print(i, pa.get_device_info_by_index(i)['name']) for i in range(pa.get_device_count())]"` 查看设备索引 |
| 阿里百炼API连接超时 | 检查网络连接和 `.env` 中的 `ALIBABA_API_KEY` 是否正确 |

---

## 里程碑 3：大模型链路（LLM客户端）

### 目标
实现与阿里云百炼的 LLM 对话能力，支持系统提示词和函数调用声明。

### 3.1 LLM 客户端

创建 `src/llm_client.py`：

```python
"""阿里云百炼 LLM 客户端 - 支持对话和函数调用"""

import json
import time
from typing import List, Dict, Optional, Callable
import dashscope
from dashscope import Generation

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("llm")


class LLMClient:
    """大模型对话客户端"""

    def __init__(self):
        self.api_key = config.api_key_alibaba
        if not self.api_key:
            logger.error("Alibaba API key not configured!")
            raise ValueError("ALIBABA_API_KEY required")

        dashscope.api_key = self.api_key
        self.model = config.get("llm.model", "qwen-plus")
        self.max_tokens = config.get("llm.max_tokens", 512)
        self.temperature = config.get("llm.temperature", 0.7)
        self.top_p = config.get("llm.top_p", 0.9)

        # 加载人格提示词
        self.system_prompt_template = self._load_persona()
        logger.info(f"LLMClient initialized: model={self.model}")

    def _load_persona(self) -> str:
        """加载Amiya人格提示词"""
        persona_path = (
            Path(__file__).parent.parent / "system_prompts" / "amiya_persona.txt"
        )
        if persona_path.exists():
            return persona_path.read_text(encoding="utf-8")
        logger.warning("Persona file not found, using default")
        return "你是阿米娅，用户的贴心学习助手。"

    def build_system_prompt(
        self,
        nickname: str = "博士",
        focus_status: str = "未开启",
        memory_summary: str = "",
    ) -> str:
        """构建完整的系统提示词"""
        from datetime import datetime

        prompt = self.system_prompt_template.format(
            nickname=nickname,
            datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 追加当前状态和记忆摘要
        prompt += f"\n\n[当前状态] 专注模式：{focus_status}"
        if memory_summary:
            prompt += f"\n[记忆摘要] {memory_summary}"

        return prompt

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict:
        """
        发送对话请求
        messages: OpenAI格式消息列表 [{"role": "user", "content": "..."}]
        tools: 可选的函数调用声明
        返回: 完整的API响应字典
        """
        try:
            logger.debug(f"Sending chat request with {len(messages)} messages")

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

            response = Generation.call(**kwargs)

            if response.status_code == 200:
                result = response.output
                logger.debug(f"LLM response: {json.dumps(result, ensure_ascii=False)[:200]}...")
                return {"success": True, "data": result, "raw": response}
            else:
                logger.error(f"LLM API error: {response.status_code} - {response.message}")
                return {"success": False, "error": response.message}

        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            return {"success": False, "error": str(e)}

    def simple_chat(self, user_message: str, system_prompt: str = None) -> str:
        """
        简化的单轮对话，直接返回文本回复
        用于测试和快速调用
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        result = self.chat(messages)
        if result["success"]:
            try:
                return result["data"]["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                return "（助手似乎不知道怎么回答）"
        return f"（请求失败: {result.get('error', 'unknown')}）"


# 工具函数声明（供LLM function calling使用）
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_focus_mode",
            "description": "开启专注模式。用户说类似'我要学习'、'开始专注'、'我要专注25分钟'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {
                        "type": "integer",
                        "description": "专注时长（分钟），默认25",
                        "minimum": 5,
                        "maximum": 120,
                    }
                },
                "required": ["duration_minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_phone_box",
            "description": "打开或临时打开手机盒。当用户说'我要接电话'、'拿手机'、'暂停一下'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "打开原因：temporary（临时拿手机/暂停专注）",
                        "enum": ["temporary"],
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_focus_status",
            "description": "查询当前专注模式状态。用户问'还剩多久'、'专注模式状态'时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_user_nickname",
            "description": "设置或修改用户称呼。当用户说'叫我XX'、'以后叫我XX'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "nickname": {
                        "type": "string",
                        "description": "用户对Amiya的称呼，如'博士'、'指挥官'、'同学'等",
                    }
                },
                "required": ["nickname"],
            },
        },
    },
]
```

### 3.2 测试 LLM 连接

修改 `src/main.py` 的 `run` 方法（实际代码中为 `run()` → `_run_voice_loop()`）：

```python
    def run(self):  # 实际代码中为 run() → _run_voice_loop()
        """里程碑3测试：LLM对话"""
        logger.info("\n[Milestone 3 Test] LLM Chat")

        # 初始化LLM客户端
        try:
            llm = LLMClient()
        except ValueError as e:
            logger.error(f"Cannot initialize LLM: {e}")
            return

        # 测试1：简单对话
        logger.info("Test 1: Simple chat")
        system = llm.build_system_prompt(nickname="博士")
        reply = llm.simple_chat("你好阿米娅，我叫博士", system_prompt=system)
        logger.info(f"User: 你好阿米娅，我叫博士")
        logger.info(f"Amiya: {reply}")

        # 测试2：带上下文的对话
        logger.info("\nTest 2: Contextual chat")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "你好阿米娅，我叫博士"},
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "能帮我讲一下牛顿第二定律吗？"},
        ]
        result = llm.chat(messages)
        if result["success"]:
            content = result["data"]["choices"][0]["message"]["content"]
            logger.info(f"Amiya: {content[:150]}...")
        else:
            logger.error(f"Chat failed: {result.get('error')}")
```

同时更新 imports：

```python
from src.llm_client import LLMClient
```

### 验证命令

```bash
python -m src.main
```

**预期输出**：
```
[Milestone 3 Test] LLM Chat
Test 1: Simple chat
User: 你好阿米娅，我叫博士
Amiya: 博士你好！我是阿米娅，很高兴见到你。今天有什么学习计划吗？...（Amiya风格的回复）

Test 2: Contextual chat
Amiya: 牛顿第二定律说的是...（耐心讲解的内容）...
```

如果看到 API Key 相关错误，检查 `.env` 文件。

---

## 里程碑 4：ASR + TTS 接入（百炼API）

### 目标
接入Paraformer-Realtime-V2 和 cosyvoice-v3-flash，实现完整的语音输入输出。

### 4.1 ASR 客户端

创建 `src/asr_client.py`：

```python
"""Paraformer-Realtime-V2 语音识别客户端"""

import os
import json
import time
import wave
import tempfile
from pathlib import Path
from typing import Optional, Callable
import dashscope
from dashscope.audio.asr import Recognition

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("asr")


class ASRClient:
    """语音识别客户端 - 百炼API流式识别"""

    def __init__(self):
        self.api_key = config.api_key_alibaba
        if not self.api_key:
            logger.error("ASR: Alibaba API key not configured!")
            raise ValueError("ALIBABA_API_KEY required")

        dashscope.api_key = self.api_key
        self.model = config.get("asr.model", "paraformer-realtime-v2")
        self.sample_rate = config.get("asr.sample_rate", 16000)
        self.language = config.get("asr.language", "zh")
        self.max_audio_seconds = config.get("asr.max_audio_seconds", 60)

        self._recognition = None
        self._result_text = ""
        self._is_final = False

        logger.info(f"ASRClient initialized: model={self.model}")

    def recognize_once(self, audio_data: bytes) -> Optional[str]:
        """
        单次识别（非流式）：传入完整音频，返回识别文本
        适用于短语音（<5秒）
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_recognize()

        try:
            # 保存临时WAV文件（百炼API需要文件或URL）
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                self._save_pcm_to_wav(audio_data, tmp_path)

            # 调用百炼ASR API
            result = Recognition.call(
                model=self.model,
                audio=tmp_path,
                sample_rate=self.sample_rate,
                format="wav",
                api_key=self.api_key,
            )

            # 清理临时文件
            os.unlink(tmp_path)

            if result.status_code == 200:
                text = self._extract_text(result.output)
                logger.info(f"ASR result: {text}")
                return text
            else:
                logger.error(f"ASR API error: {result.status_code} - {result.message}")
                return None

        except Exception as e:
            logger.error(f"ASR recognition failed: {e}")
            return None

    def _extract_text(self, output) -> str:
        """从API响应中提取文本"""
        try:
            if isinstance(output, dict):
                return output.get("text", "")
            if hasattr(output, "text"):
                return output.text
            return str(output)
        except:
            return ""

    def _save_pcm_to_wav(self, pcm_data: bytes, wav_path: str):
        """将PCM数据保存为WAV文件"""
        import wave
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_data)

    def _mock_recognize(self) -> Optional[str]:
        """Mock识别：从用户输入获取文本"""
        text = input("[MOCK ASR] 请输入用户说的话（模拟ASR识别结果）: ")
        if text.strip():
            logger.info(f"[MOCK ASR] Recognized: {text}")
            return text.strip()
        return None


# 兼容旧接口的别名
class SpeechRecognizer(ASRClient):
    pass
```

### 4.2 TTS 客户端

创建 `src/tts_client.py`：

```python
"""cosyvoice-v3-flash TTS 客户端"""

import os
import tempfile
from pathlib import Path
from typing import Optional
import dashscope
from dashscope.audio.tts import SpeechSynthesizer

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("tts")


class TTSClient:
    """语音合成客户端"""

    def __init__(self):
        self.api_key = config.api_key_alibaba
        if not self.api_key:
            logger.error("TTS: Alibaba API key not configured!")
            raise ValueError("ALIBABA_API_KEY required")

        dashscope.api_key = self.api_key
        self.model = config.get("tts.model", "cosyvoice-v3-flash")
        self.voice = config.get("tts.voice", "longanrou_v3")
        self.speed = config.get("tts.speed", 1.0)
        self.pitch = config.get("tts.pitch", 1.0)
        self.volume = config.get("tts.volume", 1.0)
        self.sample_rate = config.get("tts.sample_rate", 24000)

        logger.info(f"TTSClient initialized: model={self.model}, voice={self.voice}")

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        合成语音，返回PCM音频数据（24kHz, 16bit）
        如果音频设备是16kHz，播放前需要重采样
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_synthesize(text)

        try:
            logger.info(f"TTS synthesizing: {text[:50]}...")

            result = SpeechSynthesizer.call(
                model=self.model,
                text=text,
                voice=self.voice,
                speed=str(self.speed),
                pitch=str(self.pitch),
                volume=str(self.volume),
                sample_rate=self.sample_rate,
                format="pcm",
                api_key=self.api_key,
            )

            if result.get_audio_data():
                audio_data = result.get_audio_data()
                logger.info(f"TTS success: {len(audio_data)} bytes @ {self.sample_rate}Hz")
                return audio_data
            else:
                logger.error(f"TTS failed: {result.get_response()}")
                return None

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return None

    def synthesize_to_file(self, text: str, filepath: str) -> bool:
        """合成并保存到文件（调试使用）"""
        audio = self.synthesize(text)
        if audio:
            with open(filepath, "wb") as f:
                f.write(audio)
            logger.info(f"TTS saved to {filepath}")
            return True
        return False

    def _mock_synthesize(self, text: str) -> Optional[bytes]:
        """Mock合成：打印并返回静音数据"""
        logger.info(f"[MOCK TTS] 合成语音: {text[:60]}...")
        # 生成1秒的静音数据（16kHz, 16bit = 32000 bytes）
        # 实际播放时会听到1秒静音，证明链路通了
        duration_sec = max(1.0, len(text) * 0.1)  # 粗略估计：每个字约100ms
        sample_rate = config.get("audio.sample_rate", 16000)
        silent_bytes = int(duration_sec * sample_rate * 2)  # 2 bytes per sample
        return b"\x00" * silent_bytes

    @staticmethod
    def resample_24k_to_16k(audio_24k: bytes) -> bytes:
        """
        将24kHz PCM重采样到16kHz
        简单实现：线性采样（生产环境可用librosa或scipy）
        """
        import array
        import struct

        # 每3个采样取2个 (24k -> 16k = 2/3)
        samples = array.array("h", audio_24k)
        resampled = []
        for i in range(0, len(samples) - 1, 3):
            resampled.append(samples[i])
            resampled.append(samples[i + 1])

        return struct.pack("h" * len(resampled), *resampled)
```

### 4.3 里程碑4测试

修改 `src/main.py`：

```python
from src.asr_client import ASRClient
from src.tts_client import TTSClient
```

```python
    def run(self):  # 实际代码中为 run() → _run_voice_loop()
        """里程碑4测试：ASR + TTS + LLM完整链路"""
        logger.info("\n[Milestone 4 Test] Full Voice Pipeline")

        # 初始化客户端
        try:
            asr = ASRClient()
            tts = TTSClient()
            llm = LLMClient()
        except ValueError as e:
            logger.error(f"Init failed: {e}")
            return

        # 步骤1: Mock ASR获取用户输入
        logger.info("Step 1: Mock user speech (ASR)")
        user_text = asr.recognize_once(b"")  # Mock模式会要求输入文字
        if not user_text:
            logger.info("No input, skipping")
            return

        # 步骤2: 构建系统提示词并对话
        logger.info("Step 2: LLM processing")
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        result = llm.chat(messages)

        if not result["success"]:
            logger.error("LLM failed")
            return

        reply = result["data"]["choices"][0]["message"]["content"]
        logger.info(f"Amiya: {reply[:100]}...")

        # 步骤3: TTS合成并播放
        logger.info("Step 3: TTS synthesis and playback")
        audio_data = tts.synthesize(reply)
        if audio_data:
            # Mock模式会播放静音；真实模式播放合成语音
            self.audio.play_audio(audio_data)
            logger.info("Playback complete")
```

### 验证命令

```bash
python -m src.main
```

**预期交互流程（Mock模式）**：
```
[Milestone 4 Test] Full Voice Pipeline
Step 1: Mock user speech (ASR)
[MOCK ASR] 请输入用户说的话（模拟ASR识别结果）: 你好阿米娅
[MOCK ASR] Recognized: 你好阿米娅
Step 2: LLM processing
Amiya: 博士你好！我是阿米娅，很高兴见到你...
Step 3: TTS synthesis and playback
[MOCK TTS] 合成语音: 博士你好！我是阿米娅...
[MOCK PLAY] 播放音频: 6400 bytes
Playback complete
```

---

## 里程碑 5：函数调用 + Mock外设

### 目标
让LLM能调用设备控制函数，并实现Mock外设层。

### 5.1 Mock外设层

创建 `src/devices/` 目录下的 Mock 文件：

**`src/devices/servo_mock.py`**：

```python
"""舵机Mock - 打印角度到日志"""

import time
from src.utils.logger import setup_logger

logger = setup_logger("mock_servo")


class ServoMock:
    """模拟舵机控制器"""

    def __init__(self, name: str = "servo"):
        self.name = name
        self.current_angle = 0.0
        logger.info(f"[MOCK] Servo '{name}' initialized")

    def set_angle(self, angle: float):
        """设置角度"""
        angle = max(0, min(180, angle))
        # 模拟运动时间
        move_time = abs(angle - self.current_angle) / 90.0  # 90度/秒
        if move_time > 0:
            time.sleep(min(move_time, 2.0))
        self.current_angle = angle
        logger.info(f"[MOCK SERVO] {self.name} -> {angle:.1f}°")

    def get_angle(self) -> float:
        return self.current_angle
```

**`src/devices/ir_sensor_mock.py`**：

```python
"""红外传感器Mock"""

from src.utils.logger import setup_logger

logger = setup_logger("mock_ir")


class IRSensorMock:
    """模拟红外传感器（检测手机放入）"""

    def __init__(self):
        self._state = False  # False = 无遮挡, True = 有遮挡
        logger.info("[MOCK] IR Sensor initialized")

    def read(self) -> bool:
        return self._state

    def simulate_phone_inserted(self):
        self._state = True
        logger.info("[MOCK IR] 手机已放入 (phone_inserted)")

    def simulate_phone_removed(self):
        self._state = False
        logger.info("[MOCK IR] 手机已取出 (phone_removed)")
```

**`src/devices/tof_sensor_mock.py`**：

```python
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
```

**`src/devices/led_mock.py`**：

```python
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
```

### 5.2 设备管理器（统一入口）

创建 `src/devices/__init__.py`：

```python
"""设备管理 - 根据Mock配置返回真实或Mock设备"""

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("devices")


def get_box_servo():
    """获取手机盒舵机"""
    if config.is_mock and config.mock_devices.get("servo"):
        from .servo_mock import ServoMock
        return ServoMock("box_servo")
    # TODO: 真实设备时导入 servo_controller
    from .servo_mock import ServoMock
    return ServoMock("box_servo")


def get_ir_sensor():
    """获取红外传感器"""
    if config.is_mock and config.mock_devices.get("ir"):
        from .ir_sensor_mock import IRSensorMock
        return IRSensorMock()
    from .ir_sensor_mock import IRSensorMock
    return IRSensorMock()


def get_tof_sensor():
    """获取TOF传感器"""
    if config.is_mock and config.mock_devices.get("tof"):
        from .tof_sensor_mock import TOFSensorMock
        return TOFSensorMock()
    from .tof_sensor_mock import TOFSensorMock
    return TOFSensorMock()


def get_led():
    """获取LED控制器"""
    if config.is_mock and config.mock_devices.get("led"):
        from .led_mock import LEDMock
        return LEDMock()
    from .led_mock import LEDMock
    return LEDMock()
```

> **注意：实际设备管理器 `src/devices/__init__.py` 暴露 10 个工厂函数**（含 `get_pan_servo`、`get_tilt_servo`、`get_box_servo_left`、`get_box_servo_right`、`get_camera`、`get_button` 等），支持独立的左右舵机和摄像头/按钮管理。以上代码为 M5 早期的简化版。

### 5.3 工具函数执行器

创建 `src/tool_executor.py`：

```python
"""工具函数执行器 - 执行LLM请求的函数调用"""

import json
from typing import Dict, Any
from src.config import config
from src.devices import get_box_servo, get_ir_sensor, get_led
from src.utils.logger import setup_logger

logger = setup_logger("tools")


class ToolExecutor:
    """执行LLM调用的工具函数"""

    def __init__(self):
        # 初始化设备（Mock或真实）
        self.box_servo = get_box_servo()
        self.ir_sensor = get_ir_sensor()
        self.led = get_led()

        # 专注模式状态（简化版，完整状态机在里程碑6）
        self.focus_duration = 0
        self.focus_remaining = 0
        self.focus_active = False
        self.focus_paused = False
        self.user_nickname = "博士"

        logger.info("ToolExecutor initialized")

    def execute(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行函数调用
        返回: {"success": bool, "result": str}
        """
        logger.info(f"Executing tool: {function_name}({arguments})")

        try:
            if function_name == "set_focus_mode":
                return self._set_focus_mode(arguments)
            elif function_name == "open_phone_box":
                return self._open_phone_box(arguments)
            elif function_name == "get_focus_status":
                return self._get_focus_status()
            elif function_name == "set_user_nickname":
                return self._set_user_nickname(arguments)
            else:
                return {"success": False, "result": f"Unknown function: {function_name}"}
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"success": False, "result": f"Error: {str(e)}"}

    def _set_focus_mode(self, args: Dict) -> Dict:
        duration = args.get("duration_minutes", 25)
        self.focus_duration = duration
        self.focus_remaining = duration * 60  # 转秒
        self.focus_active = True
        self.focus_paused = False

        # Mock: 关闭盒盖
        self.box_servo.set_angle(config.get("servo.box_close_angle", 90))
        self.led.set_color("green", "solid")

        return {
            "success": True,
            "result": f"专注模式已开启，时长{duration}分钟。请把手机放入盒子中。",
        }

    def _open_phone_box(self, args: Dict) -> Dict:
        reason = args.get("reason", "temporary")

        if reason == "temporary":
            self.focus_paused = True
            self.box_servo.set_angle(config.get("servo.box_open_angle", 0))
            self.led.set_color("yellow", "solid")
            return {
                "success": True,
                "result": "盒盖已打开，专注计时暂停。记得放回来后告诉我继续哦。",
            }
        else:
            self.focus_active = False
            self.box_servo.set_angle(config.get("servo.box_open_angle", 0))
            self.led.set_color("blue", "breath")
            return {
                "success": True,
                "result": "专注模式已结束，盒盖已打开。辛苦啦！",
            }

    def _get_focus_status(self) -> Dict:
        if not self.focus_active:
            return {"success": True, "result": "当前没有进行专注模式。"}

        minutes = self.focus_remaining // 60
        seconds = self.focus_remaining % 60
        status = "暂停中" if self.focus_paused else "进行中"
        return {
            "success": True,
            "result": f"专注模式{status}，还剩{minutes}分{seconds}秒。",
        }

    def _set_user_nickname(self, args: Dict) -> Dict:
        nickname = args.get("nickname", "博士")
        self.user_nickname = nickname
        # 保存到配置文件
        config.set("system.nickname", nickname)
        return {
            "success": True,
            "result": f"好的，以后我就叫你{nickname}了。",
        }

    def get_status_for_llm(self) -> str:
        """生成当前状态摘要，供LLM system prompt使用"""
        if self.focus_active:
            mins = self.focus_remaining // 60
            return f"专注模式进行中，剩余{mins}分钟"
        return "未开启专注模式"
```

> **注意：实际 `ToolExecutor` 实现更为完整**，包含：`FocusTimer` 独立守护线程（每秒倒计时）、IR 传感器 debounce 滤波、摄像头跟踪集成（`_on_distraction` 回调）、`end_focus_mode` 工具、冲突检测、`timer_expired` 属性等。详见 `src/tool_executor.py`。

### 5.4 更新 main.py 测试函数调用

```python
from src.tool_executor import ToolExecutor
```

```python
    def run(self):  # 实际代码中为 run() → _run_voice_loop()
        """里程碑5测试：函数调用 + Mock设备"""
        logger.info("\n[Milestone 5 Test] Function Calling + Mock Devices")

        llm = LLMClient()
        tools = ToolExecutor()

        # 测试场景1：开启专注模式
        logger.info("\n--- Test 1: Set Focus Mode ---")
        user_input = input("[MOCK ASR] 用户说: ") or "我要专注25分钟"
        logger.info(f"User: {user_input}")

        system = llm.build_system_prompt(
            nickname=tools.user_nickname,
            focus_status=tools.get_status_for_llm(),
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_input},
        ]

        # 第一轮：LLM可能返回函数调用
        result = llm.chat(messages, tools=AVAILABLE_TOOLS)
        if result["success"]:
            msg = result["data"]["choices"][0]["message"]

            # 检查是否有函数调用
            if "tool_calls" in msg:
                tool_call = msg["tool_calls"][0]
                func_name = tool_call["function"]["name"]
                func_args = json.loads(tool_call["function"]["arguments"])

                logger.info(f"LLM requests tool call: {func_name}({func_args})")

                # 执行工具
                exec_result = tools.execute(func_name, func_args)
                logger.info(f"Tool result: {exec_result}")

                # 将工具结果追加到上下文，再次请求LLM生成回复
                messages.append(msg)  # assistant的tool_calls消息
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": exec_result["result"],
                })

                result2 = llm.chat(messages)
                if result2["success"]:
                    reply = result2["data"]["choices"][0]["message"]["content"]
                    logger.info(f"Amiya: {reply}")
            else:
                reply = msg["content"]
                logger.info(f"Amiya (no tool): {reply}")
```

### 验证命令

```bash
python -m src.main
```

**预期交互**：
```
[Milestone 5 Test] Function Calling + Mock Devices

--- Test 1: Set Focus Mode ---
[MOCK ASR] 用户说: 我要专注25分钟
User: 我要专注25分钟
LLM requests tool call: set_focus_mode({'duration_minutes': 25})
[MOCK SERVO] box_servo -> 90.0°
[MOCK LED] Color=green, Pattern=solid
Tool result: {'success': True, 'result': '专注模式已开启...'}
Amiya: 好的博士，25分钟专注模式已经开始了...
```

---

## 里程碑 6：上下文管理 + 记忆系统

### 目标
实现对话上下文滑动窗口、自动摘要、短期/长期记忆存储。

> **✅ M6 已实现。`MemoryManager`（`src/memory_manager.py`）提供上下文压缩、会话持久化、长期记忆归档、昵称/偏好管理。`DialogManager` 已集成记忆系统，主循环在会话结束时自动保存记忆。**

### 6.1 记忆管理器

创建 `src/memory_manager.py`：

```python
"""记忆管理 - 上下文窗口、摘要、长期记忆（JSON存储）"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from src.config import config, PROJECT_ROOT
from src.utils.logger import setup_logger

logger = setup_logger("memory")


class MemoryManager:
    """对话记忆管理器"""

    def __init__(self):
        self.max_rounds = config.get("llm.max_context_rounds", 10)
        self.token_limit = config.get("llm.context_token_limit", 3000)
        self.data_dir = PROJECT_ROOT / config.get("memory.data_dir", "data")
        self.data_dir.mkdir(exist_ok=True)

        # 实时上下文（当前会话）
        self.current_messages: List[Dict] = []
        self.session_start_time = datetime.now().isoformat()

        # 加载已有记忆
        self.longterm = self._load_longterm()
        self.today_memory = self._load_today_memory()

        logger.info("MemoryManager initialized")

    def add_message(self, role: str, content: str):
        """添加消息到当前上下文"""
        self.current_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._check_compression()

    def get_context_messages(self, system_prompt: str) -> List[Dict]:
        """
        获取完整的上下文消息列表（System + 历史对话）
        如果超过轮数限制，会自动压缩旧对话为摘要
        """
        messages = [{"role": "system", "content": system_prompt}]

        # 追加今日会话摘要作为system提示的一部分（如果有）
        if self.today_memory.get("recent_sessions"):
            summary = self.today_memory["recent_sessions"][-1].get("summary", "")
            if summary:
                messages[0]["content"] += f"\n\n[近期对话摘要] {summary}"

        # 追加当前会话消息
        messages.extend(self._format_messages_for_llm(self.current_messages))
        return messages

    def _format_messages_for_llm(self, messages: List[Dict]) -> List[Dict]:
        """转换为LLM需要的格式（去掉内部timestamp字段）"""
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def _check_compression(self):
        """检查是否需要压缩上下文"""
        # 简单轮数检查（实际生产环境应估算token数）
        user_assistant_pairs = len([m for m in self.current_messages if m["role"] in ("user", "assistant")])
        if user_assistant_pairs > self.max_rounds:
            logger.info(f"Context exceeds {self.max_rounds} rounds, compressing...")
            self._compress_context()

    def _compress_context(self):
        """压缩上下文：保留最近4轮，旧的做摘要"""
        # 保留最近的消息（user+assistant各2轮 = 4条）
        keep_count = 4
        old_messages = self.current_messages[:-keep_count]
        self.current_messages = self.current_messages[-keep_count:]

        # 生成摘要（简化版：拼接旧对话的前100字）
        summary_text = " | ".join([
            f"{m['role']}: {m['content'][:50]}"
            for m in old_messages[:6]
        ])
        logger.info(f"Context compressed. Summary: {summary_text[:100]}...")

    def save_session(self):
        """保存本次会话到今日记忆"""
        if not self.current_messages:
            return

        session_summary = self._generate_session_summary()
        session_record = {
            "session_id": f"{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "start_time": self.session_start_time,
            "end_time": datetime.now().isoformat(),
            "summary": session_summary,
            "message_count": len(self.current_messages),
        }

        self.today_memory.setdefault("recent_sessions", [])
        self.today_memory["recent_sessions"].append(session_record)
        self.today_memory["session_count"] = len(self.today_memory["recent_sessions"])
        self.today_memory["date"] = datetime.now().strftime("%Y-%m-%d")

        # 限制保留最近5次会话
        if len(self.today_memory["recent_sessions"]) > 5:
            self._archive_to_longterm()
            self.today_memory["recent_sessions"] = self.today_memory["recent_sessions"][-5:]

        self._save_today_memory()
        logger.info("Session saved to memory")

    def _generate_session_summary(self) -> str:
        """生成本次会话的简单摘要"""
        user_msgs = [m["content"] for m in self.current_messages if m["role"] == "user"]
        if not user_msgs:
            return "无对话内容"
        topics = " | ".join([m[:30] for m in user_msgs[:3]])
        return f"用户询问了: {topics}"

    def _archive_to_longterm(self):
        """归档旧记忆到长期记忆"""
        old_sessions = self.today_memory["recent_sessions"][:1]  # 归档最旧的一条
        for session in old_sessions:
            self.longterm.setdefault("conversation_summaries", [])
            self.longterm["conversation_summaries"].append({
                "date": session["start_time"][:10],
                "summary": session["summary"],
            })
        self._save_longterm()

    def _load_longterm(self) -> Dict:
        """加载长期记忆"""
        path = self.data_dir / "longterm_memory.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"version": "1.0", "user_profile": {}, "interaction_memory": {}, "conversation_summaries": []}

    def _save_longterm(self):
        """保存长期记忆"""
        path = self.data_dir / "longterm_memory.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.longterm, f, ensure_ascii=False, indent=2)

    def _load_today_memory(self) -> Dict:
        """加载今日记忆"""
        path = self.data_dir / "memory_today.json"
        today = datetime.now().strftime("%Y-%m-%d")
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 检查是否是今天的数据
                if data.get("date") == today:
                    return data
        return {"date": today, "session_count": 0, "recent_sessions": []}

    def _save_today_memory(self):
        """保存今日记忆"""
        path = self.data_dir / "memory_today.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.today_memory, f, ensure_ascii=False, indent=2)

    def get_memory_summary(self) -> str:
        """获取记忆摘要，用于注入System Prompt"""
        summaries = []
        if self.today_memory.get("recent_sessions"):
            last = self.today_memory["recent_sessions"][-1]
            summaries.append(f"上次对话: {last.get('summary', '')}")
        return "; ".join(summaries) if summaries else ""

    def get_nickname(self) -> str:
        """获取用户称呼"""
        return self.longterm.get("user_profile", {}).get("nickname", "博士")

    def set_nickname(self, nickname: str):
        """设置用户称呼"""
        if "user_profile" not in self.longterm:
            self.longterm["user_profile"] = {}
        self.longterm["user_profile"]["nickname"] = nickname
        self._save_longterm()
```

### 6.2 对话调度器（集成版）

创建 `src/dialog_manager.py`：

```python
"""对话调度器 - 整合唤醒、VAD、ASR、LLM、TTS、记忆、工具调用"""

import json
from typing import Optional
from src.config import config
from src.utils.logger import setup_logger
from src.memory_manager import MemoryManager
from src.llm_client import LLMClient, AVAILABLE_TOOLS
from src.asr_client import ASRClient
from src.tts_client import TTSClient
from src.tool_executor import ToolExecutor
from src.audio_handler import AudioHandler
from src.vad_handler import VADHandler

logger = setup_logger("dialog")


class DialogManager:
    """对话管理器 - 协调语音交互全流程"""

    def __init__(self):
        self.memory = MemoryManager()
        self.llm = LLMClient()
        self.asr = ASRClient()
        self.tts = TTSClient()
        self.tools = ToolExecutor()
        self.audio = AudioHandler()
        self.vad = VADHandler()

        logger.info("DialogManager initialized")

    def process_turn(self, user_text: Optional[str] = None) -> str:
        """
        处理单轮对话
        user_text: 如果提供则跳过ASR（Mock模式或测试用）
        返回: 助手的回复文本
        """
        # Step 1: ASR（如果没有提供文本）
        if user_text is None:
            if config.is_mock:
                user_text = input("[用户] ")
            else:
                audio_data = self.audio.record_until_silence(self.vad)
                if not audio_data:
                    return ""
                user_text = self.asr.recognize_once(audio_data)

        if not user_text:
            return ""

        logger.info(f"User: {user_text}")
        self.memory.add_message("user", user_text)

        # Step 2: 构建System Prompt + 上下文
        system = self.llm.build_system_prompt(
            nickname=self.memory.get_nickname(),
            focus_status=self.tools.get_status_for_llm(),
            memory_summary=self.memory.get_memory_summary(),
        )
        messages = self.memory.get_context_messages(system)

        # Step 3: LLM对话（可能触发函数调用）
        result = self.llm.chat(messages, tools=AVAILABLE_TOOLS)
        if not result["success"]:
            return f"（出错: {result.get('error')}）"

        msg = result["data"]["choices"][0]["message"]

        # Step 4: 处理函数调用
        if "tool_calls" in msg:
            tool_call = msg["tool_calls"][0]
            func_name = tool_call["function"]["name"]
            func_args = json.loads(tool_call["function"]["arguments"])

            logger.info(f"Tool call: {func_name}({func_args})")
            exec_result = self.tools.execute(func_name, func_args)

            # 将结果追加回LLM
            messages.append({"role": "assistant", "content": msg.get("content", "")})
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": exec_result["result"],
            })

            result2 = self.llm.chat(messages)
            if result2["success"]:
                reply = result2["data"]["choices"][0]["message"]["content"]
            else:
                reply = exec_result["result"]
        else:
            reply = msg["content"]

        # Step 5: 保存回复到记忆
        self.memory.add_message("assistant", reply)
        logger.info(f"Amiya: {reply[:100]}...")

        # Step 6: TTS播放
        audio = self.tts.synthesize(reply)
        if audio:
            self.audio.play_audio(audio)

        return reply

    def save_session(self):
        """保存当前会话"""
        self.memory.save_session()
```

### 6.3 测试

修改 `src/main.py`：

```python
from src.dialog_manager import DialogManager
```

```python
    def run(self):  # 实际代码中为 run() → _run_voice_loop()
        """里程碑6测试：完整对话循环（含记忆）"""
        logger.info("\n[Milestone 6 Test] Dialog Loop with Memory")
        dialog = DialogManager()

        print("\n=== 开始对话（输入 'quit' 退出）===")
        while True:
            try:
                # Mock模式下直接输入文字
                user_input = input("\n[用户] ")
                if user_input.lower() in ("quit", "exit", "再见"):
                    break

                reply = dialog.process_turn(user_input)
                print(f"[阿米娅] {reply}")

            except KeyboardInterrupt:
                break

        dialog.save_session()
        logger.info("Session saved.")
```

### 验证命令

```bash
python -m src.main
```

**预期交互**：
```
=== 开始对话（输入 'quit' 退出）===

[用户] 你好阿米娅
[阿米娅] 博士你好！我是阿米娅...

[用户] 我要专注25分钟
[MOCK SERVO] box_servo -> 90.0°
[MOCK LED] Color=green, Pattern=solid
[阿米娅] 好的博士，25分钟专注模式已经开始了...

[用户] quit
Session saved.
```

检查 `data/memory_today.json` 和 `data/longterm_memory.json` 是否已生成。

---

## 里程碑 7：专注模式状态机

### 目标
实现完整的专注模式状态机（IDLE → WAITING_PHONE → BOX_CLOSED → FOCUSING ↔ PAUSED → COMPLETED）。

> **⚠️ M7 里程碑代码清单仅作为规划参考。`StateController` 和 `FocusState` 枚举尚未实现。当前专注模式状态管理使用 `src/tool_executor.py` 中的布尔标志 + `FocusTimer` 守护线程完成。**

### 7.1 状态机实现

创建 `src/state_controller.py`：

```python
"""专注模式状态机 + 系统状态管理"""

import time
from enum import Enum, auto
from typing import Optional, Callable
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("state")


class FocusState(Enum):
    IDLE = auto()              # 空闲
    WAITING_PHONE = auto()     # 等待放手机
    BOX_CLOSED = auto()        # 盒盖已关闭（过渡）
    FOCUSING = auto()          # 专注中
    PAUSED = auto()            # 已暂停（临时开盒）
    COMPLETED = auto()         # 已完成


class StateController:
    """专注模式状态机控制器"""

    def __init__(self):
        self.state = FocusState.IDLE
        self.focus_duration_sec = 0      # 总时长（秒）
        self.remaining_sec = 0           # 剩余秒数
        self.elapsed_sec = 0             # 已过秒数
        self.pause_start_time = 0.0      # 暂停开始时间
        self.last_tick_time = 0.0        # 上次计时 tick

        # 回调函数（由外部设置）
        self.on_state_change: Optional[Callable] = None
        self.on_box_open: Optional[Callable] = None
        self.on_box_close: Optional[Callable] = None
        self.on_tts_speak: Optional[Callable] = None

        logger.info("StateController initialized (IDLE)")

    # ---- 状态转移方法 ----

    def start_focus(self, duration_minutes: int = 25) -> bool:
        """用户请求开始专注模式"""
        if self.state != FocusState.IDLE:
            logger.warning(f"Cannot start focus from state {self.state.name}")
            return False

        self.focus_duration_sec = duration_minutes * 60
        self.remaining_sec = self.focus_duration_sec
        self.elapsed_sec = 0
        self._transition_to(FocusState.WAITING_PHONE)
        return True

    def phone_inserted(self) -> bool:
        """红外传感器检测到手机放入"""
        if self.state == FocusState.WAITING_PHONE:
            self._transition_to(FocusState.BOX_CLOSED)
            # 触发关盖
            if self.on_box_close:
                self.on_box_close()
            # 短暂延迟后进入专注
            time.sleep(1.0)
            self._transition_to(FocusState.FOCUSING)
            self.last_tick_time = time.monotonic()
            if self.on_tts_speak:
                self.on_tts_speak("专注模式正式开始，加油哦！")
            return True

        elif self.state == FocusState.PAUSED:
            # 暂停期间放回手机，恢复专注
            self._transition_to(FocusState.BOX_CLOSED)
            if self.on_box_close:
                self.on_box_close()
            time.sleep(1.0)
            self._transition_to(FocusState.FOCUSING)
            self.last_tick_time = time.monotonic()
            if self.on_tts_speak:
                self.on_tts_speak("欢迎回来，专注继续！")
            return True

        return False

    def phone_removed(self) -> bool:
        """红外传感器检测到手机取出"""
        if self.state == FocusState.FOCUSING:
            self._transition_to(FocusState.PAUSED)
            self.pause_start_time = time.monotonic()
            if self.on_box_open:
                self.on_box_open()
            return True
        return False

    def request_pause(self, reason: str = "") -> bool:
        """用户语音请求临时暂停（如接电话）"""
        if self.state == FocusState.FOCUSING:
            self.phone_removed()
            if self.on_tts_speak:
                self.on_tts_speak(f"好的，专注计时暂停。{reason}")
            return True
        return False

    def complete_focus(self) -> bool:
        """专注完成（计时归零）"""
        if self.state == FocusState.FOCUSING:
            self._transition_to(FocusState.COMPLETED)
            if self.on_box_open:
                self.on_box_open()
            if self.on_tts_speak:
                self.on_tts_speak("专注时间到！辛苦啦，休息一下吧。")
            # 3秒后回到IDLE
            time.sleep(3.0)
            self._transition_to(FocusState.IDLE)
            return True
        return False

    def cancel_focus(self) -> bool:
        """取消专注模式"""
        if self.state in (FocusState.WAITING_PHONE, FocusState.FOCUSING, FocusState.PAUSED):
            self._transition_to(FocusState.IDLE)
            if self.on_box_open:
                self.on_box_open()
            return True
        return False

    def tick(self) -> Optional[str]:
        """
        状态机心跳（每秒调用一次）
        返回: 需要播报的提醒文本，或 None
        """
        now = time.monotonic()

        if self.state == FocusState.FOCUSING:
            # 更新剩余时间
            delta = now - self.last_tick_time
            self.last_tick_time = now
            self.remaining_sec -= delta
            self.elapsed_sec += delta

            # 检查是否完成
            if self.remaining_sec <= 0:
                self.remaining_sec = 0
                self.complete_focus()
                return None

            # 检查提醒点（10分钟/5分钟/1分钟）
            reminders = config.get("focus_mode.reminder_intervals", [600, 300, 60])
            for rem in reminders:
                if int(self.remaining_sec) == rem:
                    mins = rem // 60
                    return f"还剩{mins}分钟，继续加油哦！"

        elif self.state == FocusState.PAUSED:
            # 检查暂停超时（10分钟）
            pause_timeout = config.get("focus_mode.pause_timeout_minutes", 10) * 60
            if now - self.pause_start_time > pause_timeout:
                self.cancel_focus()
                return "暂停时间太长了，专注模式已取消。"

        elif self.state == FocusState.WAITING_PHONE:
            # 检查等待超时（60秒）
            # 实际实现需要记录进入WAITING_PHONE的时间
            pass

        return None

    def get_status_text(self) -> str:
        """获取当前状态描述"""
        if self.state == FocusState.IDLE:
            return "未开启专注模式"
        elif self.state == FocusState.WAITING_PHONE:
            return "等待放入手机"
        elif self.state == FocusState.FOCUSING:
            mins = int(self.remaining_sec) // 60
            secs = int(self.remaining_sec) % 60
            return f"专注中，剩余{mins}分{secs}秒"
        elif self.state == FocusState.PAUSED:
            return f"已暂停，已专注{self.elapsed_sec//60}分钟"
        elif self.state == FocusState.COMPLETED:
            return "专注完成"
        return "未知状态"

    def _transition_to(self, new_state: FocusState):
        """状态转移"""
        old = self.state.name
        self.state = new_state
        logger.info(f"State transition: {old} -> {new_state.name}")
        if self.on_state_change:
            self.on_state_change(old, new_state.name)
```

### 7.2 集成到 ToolExecutor

修改 `src/tool_executor.py`，将状态控制委托给 StateController：

```python
from src.state_controller import StateController, FocusState

# 在 ToolExecutor.__init__ 中添加:
self.state = StateController()

# 修改 _set_focus_mode:
def _set_focus_mode(self, args: Dict) -> Dict:
    duration = args.get("duration_minutes", 25)
    if self.state.start_focus(duration):
        return {
            "success": True,
            "result": f"专注模式已开启，时长{duration}分钟。请把手机放入盒子中，我会帮你关上盒盖。",
        }
    return {"success": False, "result": "当前无法进行专注模式，请先退出当前状态。"}
```

（完整集成代码在最终版 `main.py` 中体现）

### 7.3 测试

```bash
python -m src.main
```

**测试对话**：
```
[用户] 我要专注25分钟
[阿米娅] 好的博士，25分钟专注模式已开启...
[MOCK] 请模拟红外检测到手机放入（按Enter）
[MOCK SERVO] box_servo -> 90.0°
[阿米娅] 专注模式正式开始，加油哦！

[用户] 我要接电话
[MOCK SERVO] box_servo -> 0.0°
[阿米娅] 好的，专注计时暂停...
[MOCK] 模拟放回手机（按Enter）
[MOCK SERVO] box_servo -> 90.0°
[阿米娅] 欢迎回来，专注继续！
```

---

## 里程碑 8：多进程架构 + 消息总线

### 目标
将视觉、传感器、外设控制拆分为独立子进程，通过 Queue 通信。

> **⚠️ M8 里程碑代码清单仅作为规划参考。多进程架构和消息总线尚未实现。当前所有模块在单进程中运行。**

### 8.1 消息总线

创建 `src/message_bus.py`：

```python
"""进程间消息总线 - 基于 multiprocessing.Queue"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from multiprocessing import Queue


class MessageType(Enum):
    # 视觉
    FACE_DETECTED = "face_detected"
    FACE_LOST = "face_lost"
    # 传感器
    DISTANCE_TOF = "distance_tof"
    PHONE_DETECTED = "phone_detected"
    PHONE_REMOVED = "phone_removed"
    # 外设控制
    FOCUS_COMMAND = "focus_command"
    LED_STATE = "led_state"
    SERVO_COMMAND = "servo_command"
    # 系统
    SYSTEM_EVENT = "system_event"
    HEARTBEAT = "heartbeat"
    SHUTDOWN = "shutdown"


@dataclass
class IPCMessage:
    type: MessageType
    source: str  # "main" | "vision" | "sensor" | "device"
    target: Optional[str] = None  # None = broadcast
    timestamp: float = field(default_factory=time.monotonic)
    payload: Dict[str, Any] = field(default_factory=dict)


class MessageBus:
    """消息总线 - 管理各进程间的Queue"""

    def __init__(self):
        # 主进程发送给子进程的Queue
        self.to_vision = Queue(maxsize=100)
        self.to_sensor = Queue(maxsize=100)
        self.to_device = Queue(maxsize=100)

        # 子进程发送给主进程的Queue
        self.to_main = Queue(maxsize=100)

        logger.info("MessageBus initialized")

    def send_to(self, target: str, msg: IPCMessage):
        """发送消息到指定进程"""
        queue_map = {
            "vision": self.to_vision,
            "sensor": self.to_sensor,
            "device": self.to_device,
            "main": self.to_main,
        }
        if target in queue_map:
            queue_map[target].put(msg)

    def broadcast(self, msg: IPCMessage):
        """广播到所有子进程"""
        for queue in [self.to_vision, self.to_sensor, self.to_device]:
            queue.put(msg)

    def get_from_main(self, timeout: float = 0.01) -> Optional[IPCMessage]:
        """主进程读取子进程消息（非阻塞）"""
        if not self.to_main.empty():
            return self.to_main.get()
        return None
```

### 8.2 子进程模板

创建 `src/processes/sensor_process.py`：

```python
"""传感器子进程 - TOF + 红外"""

import time
from multiprocessing import Queue
from src.message_bus import MessageBus, IPCMessage, MessageType
from src.devices import get_tof_sensor, get_ir_sensor
from src.utils.logger import setup_logger

logger = setup_logger("sensor_proc")


def sensor_process_main(
    to_main: Queue,
    from_main: Queue,
    shutdown_event,
):
    """传感器子进程主函数"""
    logger.info("Sensor process started")

    tof = get_tof_sensor()
    ir = get_ir_sensor()

    last_phone_state = False
    last_distance = 0
    loop_interval = 0.2  # 200ms

    while not shutdown_event.is_set():
        try:
            # 读取TOF
            distance = tof.read_distance()
            if abs(distance - last_distance) > 50:
                last_distance = distance
                to_main.put(IPCMessage(
                    type=MessageType.DISTANCE_TOF,
                    source="sensor",
                    payload={"distance_mm": distance},
                ))

            # 读取红外
            phone_present = ir.read()
            if phone_present != last_phone_state:
                last_phone_state = phone_present
                msg_type = MessageType.PHONE_DETECTED if phone_present else MessageType.PHONE_REMOVED
                to_main.put(IPCMessage(
                    type=msg_type,
                    source="sensor",
                    payload={"timestamp": time.time()},
                ))

            time.sleep(loop_interval)

        except Exception as e:
            logger.error(f"Sensor process error: {e}")
            time.sleep(1)

    logger.info("Sensor process stopped")
```

（视觉子进程和外设子进程结构类似，里程碑8重点验证通信机制）

### 8.3 主进程集成

在 `src/main.py` 的最终版本中集成多进程：

```python
from multiprocessing import Process, Event
from src.message_bus import MessageBus, IPCMessage, MessageType
from src.processes.sensor_process import sensor_process_main
# from src.processes.vision_process import vision_process_main
# from src.processes.device_process import device_process_main
```

```python
    def __init__(self):
        # ... 其他初始化 ...
        self.bus = MessageBus()
        self.shutdown_event = Event()
        self.subprocesses = []

    def start_subprocesses(self):
        """启动子进程"""
        # 传感器子进程
        p_sensor = Process(
            target=sensor_process_main,
            args=(self.bus.to_main, self.bus.to_sensor, self.shutdown_event),
        )
        p_sensor.start()
        self.subprocesses.append(p_sensor)
        logger.info("Sensor subprocess started")

    def check_messages(self):
        """检查子进程消息"""
        msg = self.bus.get_from_main(timeout=0)
        while msg:
            if msg.type == MessageType.DISTANCE_TOF:
                logger.debug(f"TOF: {msg.payload['distance_mm']}mm")
            elif msg.type == MessageType.PHONE_DETECTED:
                logger.info("Phone inserted detected")
                self.dialog.tools.state.phone_inserted()
            elif msg.type == MessageType.PHONE_REMOVED:
                logger.info("Phone removed detected")
                self.dialog.tools.state.phone_removed()
            msg = self.bus.get_from_main(timeout=0)
```

### 验证命令

```bash
python -m src.main
```

**Mock模式下的多进程测试**：
- 传感器子进程会模拟TOF数据波动
- 模拟红外状态变化时会发送消息到主进程
- 主进程收到消息后会触发状态机转移

---

## 阶段1完成检查清单

在进入阶段2（树莓派硬件联调）之前，确认以下项目：

| 检查项 | 状态 |
|--------|------|
| [ ] 项目骨架运行正常，日志输出正确 | |
| [ ] VAD+ASR唤醒检测Mock测试通过 | |
| [ ] VAD能正确判断语音起止 | |
| [ ] LLM对话能返回符合Amiya人格的回复 | |
| [ ] ASR+LLM+TTS链路跑通（Mock） | |
| [ ] 函数调用能正确触发专注模式 | |
| [ ] 专注模式状态机流转正确 | |
| [ ] 上下文压缩和记忆保存正常工作 | |
| [ ] 多进程通信机制验证通过 | |
| [ ] 所有Mock外设行为符合预期 | |
| [ ] `.env` 和 `data/` 已加入 `.gitignore` | |

全部通过后，进入 **阶段2：树莓派硬件联调**。

---

## 附录：阶段2树莓派移植速查

### 环境移植命令

```bash
# 在树莓派5上执行
# 1. 安装 miniconda（aarch64版）
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh
bash Miniconda3-latest-Linux-aarch64.sh

# 2. 创建环境
conda create -n amiya python=3.11 -y
conda activate amiya

# 3. 安装依赖（全部中国大陆可用）
pip install webrtcvad pyaudio numpy opencv-python
dashscope pydantic python-dotenv requests
gpiozero pigpio smbus2

# 4. 启用I2C和GPIO
sudo raspi-config  # 启用 I2C, SPI, Camera
sudo usermod -a -G gpio,i2c,spi $USER

# 5. 测试硬件（实际测试文件为 tests/test_m5_devices.py）
python -m pytest tests/test_m5_devices.py -v
```

### 切换Mock到真实设备

修改 `data/config.json`：

```json
{
  "mock": {
    "enabled": false,
    "audio": false,
    "camera": false,
    "servo": false,
    "tof": false,
    "ir": false,
    "led": false,
    "button": false
  }
}
```

或直接改 `src/config.py` 中的默认值。

### 真实设备驱动文件

已在 M5 实现（阶段1已完成）：
- `src/devices/servo_controller.py` — PCA9685 I2C PWM 控制舵机 ✅
- `src/devices/tof_sensor.py` — I2C 读取 VL53L0X ✅
- `src/devices/ir_sensor.py` — GPIO 读取红外传感器 ✅
- `src/devices/led_controller.py` — GPIO PWM 控制 RGB LED ✅
- `src/devices/camera.py` — PID 跟踪 + MediaPipe 走神检测 ✅
- `src/devices/gpio_button.py` — GPIO 物理按钮 + Mock ✅
- `src/devices/gpio_button.py` - GPIO中断读取按键

---

*本文档随代码迭代更新。如与规格文档有冲突，以本文档实现代码为准。*
