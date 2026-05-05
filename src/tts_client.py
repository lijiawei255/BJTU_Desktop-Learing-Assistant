"""CosyVoice-v3-Flash TTS 客户端 - HTTP流式下载边下边播"""

import os
import time
import requests
from pathlib import Path
from typing import Optional

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("tts")

TTS_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"


class TTSClient:
    """语音合成客户端 - 百炼CosyVoice API，支持流式播放"""

    def __init__(self):
        self.api_key = config.api_key_alibaba
        if not self.api_key:
            logger.error("TTS: Alibaba API key not configured!")
            raise ValueError("ALIBABA_API_KEY required")

        self.model = config.get("tts.model", "cosyvoice-v3-flash")
        self.voice = config.get("tts.voice", "longanrou_v3")
        self.speed = config.get("tts.speed", 1.0)
        self.sample_rate = config.get("tts.sample_rate", 24000)
        self.output_sample_rate = config.get("audio.sample_rate", 16000)

        logger.info(f"TTSClient initialized: model={self.model}, voice={self.voice}")

    def speak(self, text: str) -> bool:
        """
        流式下载并播放：边从OSS下载音频边通过音箱播放。
        音频一旦开始下载就立即播放，无需等待完整文件。
        """
        if config.is_mock and config.mock_devices.get("audio"):
            audio = self._mock_synthesize(text)
            from src.audio_handler import AudioHandler
            AudioHandler().play_audio(audio)
            return True

        try:
            logger.info(f"TTS speak: {text[:40]}...")
            t0 = time.time()

            # Step 1: 请求TTS合成
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": {
                    "text": text,
                    "voice": self.voice,
                    "format": "pcm",
                    "sample_rate": self.sample_rate,
                },
                "parameters": {},
            }

            resp = requests.post(TTS_API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error(f"TTS HTTP error: {resp.status_code}")
                return False

            result = resp.json()
            audio_url = result.get("output", {}).get("audio", {}).get("url")
            if not audio_url:
                logger.error("TTS no audio URL in response")
                return False

            t1 = time.time()
            logger.debug(f"TTS API responded in {t1 - t0:.2f}s, streaming download...")

            # Step 2: 流式下载 + 即时播放
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.output_sample_rate,
                output=True,
            )

            total_bytes = 0
            buffer = b""
            chunk_size = 4096  # 4KB chunks

            with requests.get(audio_url, stream=True, timeout=30) as audio_resp:
                if audio_resp.status_code != 200:
                    logger.error(f"TTS download failed: {audio_resp.status_code}")
                    stream.close()
                    pa.terminate()
                    return False

                for chunk in audio_resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        buffer += chunk
                        # 积累足够数据后重采样并播放（24k→16k=2/3比例，取3的倍数）
                        while len(buffer) >= chunk_size * 3:
                            frame_24k = buffer[:chunk_size * 3]
                            buffer = buffer[chunk_size * 3:]
                            if self.sample_rate != self.output_sample_rate:
                                frame_16k = TTSClient.resample_24k_to_16k(frame_24k)
                            else:
                                frame_16k = frame_24k
                            stream.write(frame_16k)
                            total_bytes += len(frame_16k)

                # 播放剩余缓冲
                if buffer:
                    if self.sample_rate != self.output_sample_rate:
                        buffer = TTSClient.resample_24k_to_16k(buffer)
                    stream.write(buffer)
                    total_bytes += len(buffer)

            stream.stop_stream()
            stream.close()
            pa.terminate()

            t2 = time.time()
            logger.info(f"TTS done: {total_bytes} bytes played in {t2 - t0:.1f}s "
                        f"(API: {t1 - t0:.1f}s, stream: {t2 - t1:.1f}s)")
            return True

        except Exception as e:
            logger.error(f"TTS speak failed: {e}")
            return False

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        合成语音，返回完整PCM音频数据（24kHz, 16bit）
        非流式模式，用于需要完整音频的场景（如保存文件）
        """
        if config.is_mock and config.mock_devices.get("audio"):
            return self._mock_synthesize(text)

        try:
            logger.info(f"TTS synthesizing: {text[:50]}...")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": {
                    "text": text,
                    "voice": self.voice,
                    "format": "pcm",
                    "sample_rate": self.sample_rate,
                },
                "parameters": {},
            }

            resp = requests.post(
                "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.error(f"TTS HTTP error: {resp.status_code}")
                return None

            result = resp.json()
            audio_url = result.get("output", {}).get("audio", {}).get("url")
            if not audio_url:
                logger.error("TTS no audio URL in response")
                return None

            audio_resp = requests.get(audio_url, timeout=30)
            if audio_resp.status_code != 200:
                logger.error(f"TTS download failed: {audio_resp.status_code}")
                return None

            audio_data = audio_resp.content
            logger.info(f"TTS success: {len(audio_data)} bytes @ {self.sample_rate}Hz")
            return audio_data

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
        duration_sec = max(1.0, len(text) * 0.1)
        sample_rate = config.get("audio.sample_rate", 16000)
        silent_bytes = int(duration_sec * sample_rate * 2)
        return b"\x00" * silent_bytes

    @staticmethod
    def resample_24k_to_16k(audio_24k: bytes) -> bytes:
        """将24kHz PCM重采样到16kHz：每3个采样取2个"""
        import array
        import struct

        samples = array.array("h", audio_24k)
        resampled = []
        for i in range(0, len(samples) - 1, 3):
            resampled.append(samples[i])
            resampled.append(samples[i + 1])

        return struct.pack("h" * len(resampled), *resampled)
