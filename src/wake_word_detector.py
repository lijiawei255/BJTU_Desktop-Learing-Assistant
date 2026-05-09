"""唤醒词检测 - 基于 webrtcvad + 千问3-ASR-Flash-Realtime 流式识别"""

import time
from collections import deque
from typing import Optional
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("wake_word")


class WakeWordDetector:
    """唤醒词检测器 - 使用VAD检测语音 + ASR识别确认唤醒词"""

    WAKE_WORDS = [
        "阿米娅", "amiya", "amia", "阿米亚", "амия",
        "am iya", "am ia", "a miya",
    ]
    COOLDOWN_SECONDS = 5

    def __init__(self):
        self.sample_rate = config.get("audio.sample_rate", 16000)
        self.chunk_size = config.get("audio.chunk_size", 480)
        self.vad_aggressiveness = config.get("audio.vad_aggressiveness", 2)
        self._last_wake_time = 0.0
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
        流程: VAD检测语音起始 → 持续收集直到静音 → 完整语音发ASR → 检查唤醒词
        返回: 是否唤醒成功
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_listen()

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

            # VAD状态机
            collecting = False          # 是否正在收集语音
            speech_frames = 0           # 检测到的语音帧计数
            silence_frames = 0          # 连续静音帧计数
            min_speech_frames = 8       # 至少240ms语音才开始收集
            silence_to_end = 25         # 连续750ms静音判定语音结束
            max_frames = 200            # 最多6秒

            audio_buffer = []

            logger.info("Waiting for speech... (say '阿米娅' or 'Amiya')")

            while True:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                is_speech = vad_handler.is_speech(data, self.sample_rate)

                if is_speech:
                    if not collecting:
                        logger.debug(f"VAD: Speech detected, starting collection...")
                        collecting = True
                        audio_buffer = []
                        speech_frames = 0
                        silence_frames = 0
                    speech_frames += 1
                    silence_frames = 0
                else:
                    if collecting:
                        silence_frames += 1

                # 收集语音帧
                if collecting:
                    audio_buffer.append(data)

                # 语音结束判定：收集足够语音后出现长静音
                if collecting and speech_frames >= min_speech_frames and silence_frames >= silence_to_end:
                    logger.debug(f"VAD: Speech ended ({len(audio_buffer)} frames)")
                    # 去除末尾的静音帧
                    trim_count = min(silence_frames, 10)
                    effective_frames = audio_buffer[:-trim_count] if trim_count > 0 else audio_buffer

                    if len(effective_frames) >= min_speech_frames:
                        audio_data = b"".join(effective_frames)
                        logger.info(f"Sending {len(audio_data)} bytes ({len(effective_frames)*30}ms) to ASR...")

                        if asr_client:
                            result = asr_client.recognize_once(audio_data)
                            if result:
                                logger.info(f"ASR result: '{result}'")
                                if self.check_wake_word_in_text(result):
                                    logger.info("Wake word DETECTED!")
                                    stream.stop_stream()
                                    stream.close()
                                    pa.terminate()
                                    return True
                                else:
                                    logger.info(f"No wake word in: '{result[:30]}'")
                            else:
                                logger.debug("ASR returned empty, discarding...")
                    else:
                        logger.debug("Audio too short, discarding...")

                    # 重置，准备下一轮监听
                    collecting = False
                    audio_buffer = []
                    speech_frames = 0
                    silence_frames = 0

                # 超长语音截断（避免无限收集）
                if collecting and len(audio_buffer) >= max_frames:
                    logger.debug(f"VAD: Max frames reached, flushing...")
                    audio_data = b"".join(audio_buffer)
                    if asr_client:
                        result = asr_client.recognize_once(audio_data)
                        if result and self.check_wake_word_in_text(result):
                            logger.info("Wake word detected in long utterance!")
                            stream.stop_stream()
                            stream.close()
                            pa.terminate()
                            return True
                    collecting = False
                    audio_buffer = []
                    speech_frames = 0
                    silence_frames = 0

        except Exception as e:
            logger.error(f"Wake word listen error: {e}")
            return False

    def _mock_listen(self) -> bool:
        """Mock模式：终端输入模拟唤醒"""
        try:
            user_input = input("[MOCK] 输入唤醒词后按 Enter（直接按Enter模拟触发）: ")
        except (EOFError, KeyboardInterrupt):
            logger.info("[MOCK] Input stream ended (EOF/Interrupt), returning to IDLE.")
            return False
        if user_input.strip().lower() in self.WAKE_WORDS or user_input.strip() == "":
            logger.info("[MOCK] Wake word triggered")
            return True
        logger.info("[MOCK] Not a wake word, continuing listen...")
        return self._mock_listen()

