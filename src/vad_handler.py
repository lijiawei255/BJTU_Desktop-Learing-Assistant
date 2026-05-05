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
        num_samples = len(frame_bytes) // 2
        return int(num_samples * 1000 / sample_rate)
