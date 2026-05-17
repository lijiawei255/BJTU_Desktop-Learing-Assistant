"""唤醒词检测 - 基于 webrtcvad + 千问3-ASR-Flash-Realtime 流式识别 (M9: 模糊匹配 + 打断检测)"""

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
        "阿米呀", "阿米雅", "啊米娅", "阿咪娅",
        "阿米丫", "阿米压", "阿米鸭", "阿米",
        "阿蜜娅", "阿米哟", "armiya",
    ]
    # 核心唤醒词（用于前缀匹配、打断检测、前缀剥离）
    CORE_WAKE_PREFIXES = [
        "阿米娅", "阿米亚", "阿米呀", "阿米雅", "啊米娅", "阿咪娅",
        "阿米丫", "阿米压", "阿米鸭", "阿蜜娅",
        "amiya", "amia", "амия",
    ]
    COOLDOWN_SECONDS = 5

    def __init__(self):
        self.sample_rate = config.get("audio.sample_rate", 16000)
        self.chunk_size = config.get("audio.chunk_size", 480)
        self.vad_aggressiveness = config.get("audio.vad_aggressiveness", 2)
        self.fuzzy_threshold = config.get("audio.wake_word_fuzzy_threshold", 0.6)
        self._last_wake_time = 0.0
        logger.info("WakeWordDetector initialized (VAD + ASR-based, fuzzy matching)")

    # ── 模糊匹配 ──────────────────────────────────────────────

    @staticmethod
    def _char_similarity(a: str, b: str) -> bool:
        """判断两个字符是否被认为是相似的。
        处理常见的ASR错误：声母/韵母相近、同音字、形近字。
        """
        if a == b:
            return True
        similar_groups = [
            {"娅", "亚", "呀", "雅", "丫", "压", "鸭"},
            {"阿", "啊", "呵"},
            {"米", "咪", "蜜", "密"},
            {"i", "y"},
            {"a", "e"},
        ]
        for group in similar_groups:
            if a in group and b in group:
                return True
        return False

    @classmethod
    def _fuzzy_sequence_match(cls, text: str, pattern: str) -> float:
        """在 text 中寻找与 pattern 最相似的子序列，返回相似度分数 0.0~1.0。
        使用滑动窗口 + 字符级相似度比较。
        """
        if not text or not pattern:
            return 0.0
        text = text.lower().replace(" ", "")
        pattern = pattern.lower().replace(" ", "")
        if not pattern:
            return 0.0
        if pattern in text:
            return 1.0
        if len(pattern) > len(text):
            return 0.0

        best = 0.0
        # 滑动窗口
        for start in range(len(text) - len(pattern) + 1):
            matches = 0
            for i, pc in enumerate(pattern):
                tc = text[start + i]
                if cls._char_similarity(tc, pc):
                    matches += 1
            score = matches / len(pattern)
            if score > best:
                best = score
        return best

    def check_wake_word_in_text(self, text: str) -> bool:
        """检查ASR文本中是否包含唤醒词（先精确，后模糊）"""
        if not text:
            return False
        text_lower = text.lower().strip()
        # 精确匹配
        for word in self.WAKE_WORDS:
            if word in text_lower:
                return True
        # 模糊匹配
        return self.check_wake_word_fuzzy(text)

    def check_wake_word_fuzzy(self, text: str, threshold: float = None) -> bool:
        """模糊匹配：对核心唤醒词做字符级相似度匹配"""
        if threshold is None:
            threshold = self.fuzzy_threshold
        if not text:
            return False
        text_lower = text.lower().strip().replace(" ", "")
        for word in self.CORE_WAKE_PREFIXES:
            # 在文本中搜索 word 的近似子序列
            score = self._fuzzy_sequence_match(text_lower, word)
            if score >= threshold:
                logger.debug(f"Fuzzy match: '{text}' ~ '{word}' score={score:.2f}")
                return True
        return False

    def starts_with_wake_word(self, text: str) -> bool:
        """检查文本是否以唤醒词开头（用于打断检测门控）。
        要求唤醒词出现在文本的前几个字符位置，防止误打断。
        """
        if not text:
            return False
        text_lower = text.lower().strip().replace(" ", "")

        # 1. 精确前缀匹配
        for word in self.CORE_WAKE_PREFIXES:
            w = word.lower().replace(" ", "")
            if text_lower.startswith(w):
                return True

        # 2. 模糊前缀匹配：检查文本开头是否近似等于某个唤醒词
        for word in self.CORE_WAKE_PREFIXES:
            w = word.lower().replace(" ", "")
            if len(text_lower) >= len(w):
                prefix = text_lower[:len(w)]
                score = self._sequence_score(prefix, w)
                if score >= 0.6:  # 前缀匹配容许更低阈值
                    logger.debug(f"Prefix fuzzy match: '{prefix}' ~ '{w}' score={score:.2f}")
                    return True
            elif len(text_lower) >= 2:
                # 文本较短时，检查文本是否是唤醒词的前缀
                score = self._sequence_score(text_lower, w[:len(text_lower)])
                if score >= 0.7:
                    return True
        return False

    @staticmethod
    def _sequence_score(a: str, b: str) -> float:
        """计算两个等长字符串的字符级相似度"""
        if len(a) != len(b):
            return 0.0
        if not a:
            return 0.0
        matches = sum(1 for i in range(len(a)) if WakeWordDetector._char_similarity(a[i], b[i]))
        return matches / len(a)

    # ── 打断检测 ──────────────────────────────────────────────

    def check_barge_in(
        self,
        audio_handler,
        vad_handler,
        asr_client,
        timeout_seconds: float = 2.0,
    ) -> Optional[str]:
        """
        TTS播放期间的打断检测（非阻塞）。
        快速VAD检测 → 如果检测到语音则录音 → ASR → 检查是否以唤醒词开头。

        Returns:
            如果检测到"阿米娅"开头的语音，返回完整文本。
            否则返回 None。
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_check_barge_in()

        stream_close = None
        try:
            import pyaudio

            # 复用 AudioHandler 的 PyAudio 实例，避免每次轮询创建新实例
            pa = getattr(audio_handler, '_pa', None)
            if pa is None:
                pa = pyaudio.PyAudio()

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=getattr(audio_handler, '_input_device', None),
                frames_per_buffer=self.chunk_size,
            )

            # 阶段1: 快速VAD预检 — 读几帧看是否有语音
            pre_check_frames = 6  # ~180ms (reduced from 8)
            speech_count = 0
            pre_frames = []
            for _ in range(pre_check_frames):
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                except Exception:
                    stream.close()
                    return None
                pre_frames.append(data)
                if vad_handler.is_speech(data, self.sample_rate):
                    speech_count += 1

            if speech_count < 2:  # 至少2帧有语音才触发 (reduced from 3)
                stream.stop_stream()
                stream.close()
                return None

            # 阶段2: 有语音迹象，完整录音至静音
            logger.debug("Barge-in: speech detected during TTS, collecting utterance")
            audio_buffer = list(pre_frames)
            speech_frames = speech_count
            silence_frames = 0
            min_speech_frames = 10
            silence_to_end = 18  # ~540ms静音判定结束
            max_frames = 80  # 最多~2.4秒 (reduced from 120)

            while len(audio_buffer) < max_frames:
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                except Exception:
                    break
                audio_buffer.append(data)
                if vad_handler.is_speech(data, self.sample_rate):
                    speech_frames += 1
                    silence_frames = 0
                else:
                    silence_frames += 1
                if speech_frames >= min_speech_frames and silence_frames >= silence_to_end:
                    break

            stream.stop_stream()
            stream.close()

            if speech_frames < min_speech_frames:
                logger.debug("Barge-in: too few speech frames, ignoring")
                return None

            # 去除末尾静音帧
            trim_count = min(silence_frames, 8)
            effective = audio_buffer[:-trim_count] if trim_count > 0 else audio_buffer
            audio_data = b"".join(effective)

            # 阶段3: ASR + 唤醒词前缀检查
            if asr_client:
                result = asr_client.recognize_once(audio_data)
                if result:
                    logger.info(f"Barge-in ASR: '{result}'")
                    if self.starts_with_wake_word(result):
                        logger.info("Barge-in CONFIRMED — wake word at start")
                        return result
                    else:
                        logger.debug(f"Barge-in rejected: no wake word at start of '{result[:30]}'")

            return None

        except Exception as e:
            logger.warning(f"Barge-in check error: {e}")
            return None

    def _mock_check_barge_in(self) -> Optional[str]:
        """Mock模式打断检测：始终返回None（Mock下无法真实检测）"""
        return None

    # ── 冷却管理 ──────────────────────────────────────────────

    def is_in_cooldown(self) -> bool:
        """检查是否在唤醒冷却期"""
        return (time.time() - self._last_wake_time) < self.COOLDOWN_SECONDS

    def mark_awake(self):
        """标记唤醒成功，启动冷却计时"""
        self._last_wake_time = time.time()
        logger.info("Wake word confirmed! Entering cooldown.")

    # ── 主唤醒监听 ──────────────────────────────────────────

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

            collecting = False
            speech_frames = 0
            silence_frames = 0
            min_speech_frames = 8
            silence_to_end = 25
            max_frames = 200

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

                if collecting:
                    audio_buffer.append(data)

                if collecting and speech_frames >= min_speech_frames and silence_frames >= silence_to_end:
                    logger.debug(f"VAD: Speech ended ({len(audio_buffer)} frames)")
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

                    collecting = False
                    audio_buffer = []
                    speech_frames = 0
                    silence_frames = 0

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
