"""CosyVoice-v3-Flash TTS 客户端 - HTTP流式下载边下边播 + 后台句子队列"""

import os
import queue
import threading
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

        # 后台队列播放相关
        self._sentence_queue: queue.Queue = queue.Queue()
        self._playback_active = False
        self._worker_thread: Optional[threading.Thread] = None
        self._pyaudio_instance = None
        self._idle_event = threading.Event()
        self._idle_event.set()  # 初始状态：空闲

        # 打断检测相关
        self._barge_audio_handler = None
        self._barge_vad = None
        self._barge_triggered = False

        # 共享 PyAudio 实例（避免树莓派上多实例竞争USB声卡）
        self._shared_pa = None

    def set_shared_pa(self, pa):
        """设置共享 PyAudio 实例，所有 speak() 调用将复用此实例。"""
        self._shared_pa = pa

    # ── 打断检测配置 ──────────────────────────────────────────────

    def set_barge_in_handler(self, audio_handler, vad, wake_detector=None, asr_client=None) -> None:
        """启用打断检测：传入 AudioHandler、VADHandler、WakeWordDetector 和 ASRClient。
        设置后，TTS播放期间后台监听麦克风，检测到语音后采集完整语句，
        通过ASR验证是否以唤醒词开头，确认后才触发打断。
        """
        self._barge_audio_handler = audio_handler
        self._barge_vad = vad
        self._barge_wake = wake_detector
        self._barge_asr = asr_client
        logger.debug("Barge-in detection enabled (wake-word verified)")

    @property
    def was_barge_in(self) -> bool:
        """最近一次播放是否被用户语音打断。"""
        return self._barge_triggered

    @property
    def is_playing(self) -> bool:
        """是否正在播放（队列非空或worker活跃）。"""
        return self._playback_active and (
            not self._sentence_queue.empty() or not self._idle_event.is_set()
        )

    # ── 后台队列播放 API ──────────────────────────────────────────

    def start_playback_worker(self):
        """启动后台线程，持续从队列取句子→合成→播放。"""
        if self._playback_active:
            return
        self._playback_active = True
        self._idle_event.clear()
        self._worker_thread = threading.Thread(
            target=self._playback_loop, daemon=True
        )
        self._worker_thread.start()
        logger.debug("TTS playback worker started")

    def stop_playback(self):
        """立即停止播放，清空未播放的句子队列。"""
        self._playback_active = False
        while not self._sentence_queue.empty():
            try:
                self._sentence_queue.get_nowait()
            except queue.Empty:
                break
        self._idle_event.set()
        logger.debug("TTS playback stopped, queue cleared")

    def enqueue_sentence(self, text: str):
        """将一句文本加入合成播放队列（线程安全）。"""
        if text and text.strip():
            self._idle_event.clear()
            self._sentence_queue.put(text.strip())

    def wait_for_queue(self, timeout: float = None):
        """阻塞直到队列中所有句子播放完毕。"""
        try:
            self._idle_event.wait(timeout=timeout)
        except Exception:
            pass

    def _playback_loop(self):
        """后台worker：从队列取句子→合成→播放，循环。若启用打断检测，被打断后停止。"""
        import pyaudio

        self._pyaudio_instance = pyaudio.PyAudio()
        self._barge_triggered = False

        while self._playback_active:
            try:
                sentence = self._sentence_queue.get(timeout=0.3)
            except queue.Empty:
                if self._sentence_queue.empty():
                    self._idle_event.set()
                continue

            if not self._playback_active:
                break

            if not sentence or not sentence.strip():
                if self._sentence_queue.empty():
                    self._idle_event.set()
                continue

            # 合成（阻塞HTTP调用）
            pcm_data = self.synthesize(sentence)
            if not pcm_data or not self._playback_active:
                if self._sentence_queue.empty():
                    self._idle_event.set()
                continue

            # 播放（chunk级可中断，支持打断检测）
            interrupted = self._play_pcm(pcm_data)
            if interrupted:
                self._barge_triggered = True
                while not self._sentence_queue.empty():
                    try:
                        self._sentence_queue.get_nowait()
                    except queue.Empty:
                        break
                self._idle_event.set()
                logger.info("TTS barge-in detected, stopping playback.")
                break

            if self._sentence_queue.empty():
                self._idle_event.set()

        if self._pyaudio_instance:
            self._pyaudio_instance.terminate()
            self._pyaudio_instance = None
        self._idle_event.set()
        logger.debug("TTS playback worker stopped")

    def _play_pcm(self, pcm_data: bytes) -> bool:
        """播放PCM数据，每chunk检查中断标志。
        若已启用打断检测，播放同时监听麦克风：连续6帧(180ms)语音活动即打断。

        Returns:
            True 如果被打断，False 如果正常播放完毕。
        """
        import pyaudio

        if not self._pyaudio_instance or not self._playback_active:
            return False

        # 重采样 24kHz → 16kHz
        if self.sample_rate != self.output_sample_rate:
            pcm_data = TTSClient.resample_24k_to_16k(pcm_data)

        # 打断检测：启动麦克风监听线程（唤醒词验证后触发）
        barge_event = threading.Event()

        if self._barge_audio_handler and self._barge_vad:
            ah = self._barge_audio_handler
            vad = self._barge_vad
            sample_rate = ah.sample_rate
            chunk_size_frames = ah.chunk_size

            def _monitor_mic():
                try:
                    mic_stream = self._pyaudio_instance.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=sample_rate,
                        input=True,
                        frames_per_buffer=chunk_size_frames,
                    )
                except Exception:
                    return

                speech_frames = 0
                required_frames = 5  # ~150ms 语音触发阈值
                audio_buffer = []
                collecting = False
                silence_frames = 0
                silence_to_end = 25  # ~750ms 静音判定结束
                min_speech_frames = 10  # 至少300ms语音

                while not barge_event.is_set():
                    try:
                        frame_data = mic_stream.read(
                            chunk_size_frames, exception_on_overflow=False
                        )
                    except Exception:
                        break

                    is_speech = vad.is_speech(frame_data, sample_rate)

                    if is_speech:
                        if not collecting:
                            collecting = True
                            audio_buffer = [frame_data]
                            speech_frames = 1
                            silence_frames = 0
                        else:
                            audio_buffer.append(frame_data)
                            speech_frames += 1
                            silence_frames = 0
                    else:
                        if collecting:
                            audio_buffer.append(frame_data)
                            silence_frames += 1

                    # 语音段结束（静音判定）
                    if collecting and speech_frames >= min_speech_frames and silence_frames >= silence_to_end:
                        # 去除末尾静音帧
                        trim_count = min(silence_frames, 10)
                        effective = audio_buffer[:-trim_count] if trim_count > 0 else audio_buffer
                        audio_data = b"".join(effective)

                        # ASR → 唤醒词验证
                        if self._barge_asr and self._barge_wake and len(effective) >= min_speech_frames:
                            try:
                                result = self._barge_asr.recognize_once(audio_data)
                                if result and self._barge_wake.starts_with_wake_word(result):
                                    logger.info(f"Barge-in CONFIRMED: wake word in '{result[:40]}'")
                                    barge_event.set()
                                    break
                                else:
                                    logger.debug(f"Barge-in rejected (no wake word): '{result[:30] if result else 'empty'}'")
                            except Exception as e:
                                logger.debug(f"Barge-in ASR error: {e}")
                        else:
                            # 无 ASR/唤醒检测器，回退到纯语音检测
                            if speech_frames >= required_frames:
                                logger.debug("Barge-in: speech detected (no wake-verify available)")
                                barge_event.set()
                                break

                        collecting = False
                        audio_buffer = []
                        speech_frames = 0
                        silence_frames = 0

                mic_stream.stop_stream()
                mic_stream.close()

            monitor_thread = threading.Thread(target=_monitor_mic, daemon=True)
            monitor_thread.start()

        # 播放循环
        stream = self._pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.output_sample_rate,
            output=True,
        )

        chunk_size = 4096
        interrupted = False
        for i in range(0, len(pcm_data), chunk_size):
            if not self._playback_active or barge_event.is_set():
                interrupted = True
                break
            chunk = pcm_data[i : i + chunk_size]
            stream.write(chunk)

        stream.stop_stream()
        stream.close()

        barge_event.set()  # 信号监听线程退出
        return interrupted

    # ── 原有的直接合成/播放 API ──────────────────────────────────

    def speak(self, text: str, pa_instance=None) -> bool:
        """
        流式下载并播放：边从OSS下载音频边通过音箱播放。
        若提供 pa_instance（共享PyAudio），则复用该实例避免树莓派USB声卡竞争。
        """
        if config.is_mock and config.mock_devices.get("audio"):
            audio = self._mock_synthesize(text)
            from src.audio_handler import AudioHandler
            AudioHandler().play_audio(audio)
            return True

        if pa_instance is None:
            pa_instance = self._shared_pa
        pa_shared = pa_instance is not None

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
            pa = pa_instance if pa_shared else pyaudio.PyAudio()
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
                    if not pa_shared:
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
            if not pa_shared:
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
