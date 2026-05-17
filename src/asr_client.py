"""语音识别客户端 - 百炼 Paraformer Realtime API"""

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
    """语音识别客户端 - 百炼Paraformer实时识别"""

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

        logger.info(f"ASRClient initialized: model={self.model}")

    def recognize_once(self, audio_data: bytes) -> Optional[str]:
        """
        单次识别（非流式）：传入完整音频，返回识别文本
        适用于短语音（<60秒）
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_recognize()

        try:
            # 保存临时WAV文件
            tmp_path = str(Path("logs") / f"asr_temp_{int(time.time())}.wav")
            self._save_pcm_to_wav(audio_data, tmp_path)

            # 使用Recognition实例调用
            recognition = Recognition(
                model=self.model,
                format="wav",
                sample_rate=self.sample_rate,
                callback=None,
            )
            result = recognition.call(tmp_path)

            # 清理临时文件
            os.unlink(tmp_path)

            if result.status_code == 200:
                sentences = result.get_sentence()
                if sentences:
                    full_text = self._extract_text(sentences)
                    if full_text:
                        logger.info(f"ASR result: {full_text}")
                        return full_text
                logger.info("ASR returned empty text")
                return None
            else:
                logger.error(f"ASR API error: {result.status_code} - {result.message}")
                return None

        except Exception as e:
            logger.error(f"ASR recognition failed: {e}")
            return None

    def _extract_text(self, sentences) -> str:
        """从dashscope返回的sentence列表提取文本，兼容dict和object两种格式。

        dashscope的get_sentence()返回格式不一致：
        - 有时返回 [{"text": "...", "words": [...]}, ...]
        - 有时text不在顶层而只在words[].text中
        - 也可能是SDK对象（有.text/.words属性）
        """
        texts = []
        for s in sentences:
            if isinstance(s, dict):
                text = s.get("text", "").strip()
                if text:
                    texts.append(text)
                else:
                    for w in s.get("words", []):
                        if isinstance(w, dict):
                            wt = w.get("text", "")
                            if wt:
                                texts.append(wt)
            elif hasattr(s, "text"):
                if s.text and s.text.strip():
                    texts.append(s.text.strip())
                elif hasattr(s, "words"):
                    for w in s.words:
                        wt = getattr(w, "text", "")
                        if wt:
                            texts.append(wt)
        return "".join(texts).strip()

    def _save_pcm_to_wav(self, pcm_data: bytes, wav_path: str):
        """将PCM数据保存为WAV文件"""
        import wave
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_data)

    def _mock_recognize(self) -> Optional[str]:
        """Mock识别：无头从队列获取，交互从终端输入获取"""
        from src.headless_input import headless_input
        if headless_input.enabled:
            text = headless_input.get_input("[MOCK ASR]")
            if text.strip():
                logger.info(f"[MOCK ASR] Recognized: {text}")
                return text.strip()
            return None

        text = input("[MOCK ASR] 请输入用户说的话（模拟ASR识别结果）: ")
        if text.strip():
            logger.info(f"[MOCK ASR] Recognized: {text}")
            return text.strip()
        return None


# 兼容旧接口的别名
class SpeechRecognizer(ASRClient):
    pass
