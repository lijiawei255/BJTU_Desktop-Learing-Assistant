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
                    # Paraformer返回的是句子列表，提取每个句子的text
                    texts = []
                    for s in sentences:
                        if isinstance(s, dict):
                            texts.append(s.get("text", ""))
                        elif hasattr(s, "text"):
                            texts.append(s.text)
                    full_text = "".join(texts).strip()
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
