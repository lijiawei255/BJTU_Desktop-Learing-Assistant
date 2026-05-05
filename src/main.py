"""Amiya 桌面学习助手 - 主程序入口"""

import signal
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.utils.logger import setup_logger
from src.audio_handler import AudioHandler
from src.vad_handler import VADHandler
from src.wake_word_detector import WakeWordDetector
from src.llm_client import LLMClient
from src.asr_client import ASRClient
from src.tts_client import TTSClient

logger = setup_logger("main")


class AmiyaSystem:
    """系统主类"""

    def __init__(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("=" * 50)
        logger.info("Amiya Desktop Learning Assistant Starting...")
        logger.info(f"Project root: {PROJECT_ROOT}")
        logger.info(f"Mock mode: {config.is_mock}")
        logger.info("=" * 50)

    def _handle_signal(self, signum, frame):
        """处理 Ctrl+C 信号"""
        logger.info("Received stop signal.")
        self._running = False

    def run_test(self):
        """里程碑2-4综合测试：完整语音对话链路"""
        logger.info("\n[Milestone 2-4 Test] Full Voice Pipeline\n")

        # 初始化所有组件
        try:
            audio_handler = AudioHandler()
            vad = VADHandler()
            wake = WakeWordDetector()
            asr = ASRClient()
            llm = LLMClient()
            tts = TTSClient()
        except ValueError as e:
            logger.error(f"Initialization failed: {e}")
            logger.error("Please check your .env file and API key configuration.")
            return

        print("\n" + "=" * 50)
        print("  阿米娅 (Amiya) 桌面学习助手")
        print("  语音交互测试")
        print("=" * 50)
        print()

        while self._running:
            try:
                # Step 1: 唤醒词检测 (Milestone 2)
                logger.info("Step 1: Waiting for wake word...")
                detected = wake.listen_for_wake_word(audio_handler, vad, asr)
                if not detected or not self._running:
                    continue

                wake.mark_awake()

                # 唤醒确认语音：流式TTS边生成边播放
                print("[阿米娅] 嗯，我在听...")
                tts.speak("嗯，我在听，请说。")

                # Step 2: 录音采集 (Milestone 2)
                logger.info("Step 2: Recording user speech...")
                audio_data = audio_handler.record_until_silence(vad)
                if not audio_data:
                    logger.info("No speech detected.")
                    continue

                # 保存调试录音
                audio_handler.save_wav(audio_data, "logs/test_recording.wav")

                # Step 3: 语音识别 (Milestone 4)
                logger.info("Step 3: ASR recognition...")
                user_text = asr.recognize_once(audio_data)
                if not user_text:
                    logger.info("ASR returned empty, skipping.")
                    continue

                print(f"\n[用户] {user_text}")

                # Step 4: LLM对话 (Milestone 3)
                logger.info("Step 4: LLM processing...")
                system = llm.build_system_prompt(nickname="博士")
                reply = llm.simple_chat(user_text, system_prompt=system)

                print(f"[阿米娅] {reply}")

                # Step 5: 流式TTS边生成边播放 (Milestone 4)
                logger.info("Step 5: Streaming TTS playback...")
                tts.speak(reply)

                print()  # 空行分隔下一轮对话

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in conversation loop: {e}")
                continue

        logger.info("\nTest complete. Exiting.")

    def run(self):
        """主循环"""
        try:
            self.run_test()
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
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
