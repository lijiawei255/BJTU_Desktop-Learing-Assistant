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

                is_speech = vad_detector.is_speech(data, self.sample_rate)

                if is_speech:
                    speech_started = True
                    silence_frames = 0
                else:
                    if speech_started:
                        silence_frames += 1

                if speech_started and silence_frames >= silence_threshold and frame_count >= min_frames:
                    logger.debug(f"Recording stopped by silence detection ({silence_frames} silent frames)")
                    break

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
        """Mock录音：等待用户按Enter模拟说话结束"""
        logger.info("[MOCK RECORD] Simulating audio recording...")
        input("[MOCK] 按 Enter 模拟用户说话结束: ")
        return b"\x00" * 1600  # 返回100ms静音作为占位

    def _mock_play(self, audio_data: bytes):
        """Mock播放：保存到日志"""
        logger.info(f"[MOCK PLAY] 播放音频: {len(audio_data)} bytes")
        mock_dir = Path("logs/mock_audio")
        mock_dir.mkdir(exist_ok=True)
        timestamp = int(time.time())
        with open(mock_dir / f"tts_{timestamp}.pcm", "wb") as f:
            f.write(audio_data)

    def save_wav(self, audio_data: bytes, filepath: str):
        """保存PCM数据为WAV文件（调试用）"""
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data)
        logger.debug(f"Saved WAV: {filepath}")

    def __del__(self):
        if self._pa:
            self._pa.terminate()
