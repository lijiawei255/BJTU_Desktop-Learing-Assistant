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
from src.text_sanitizer import TextSanitizer
from src.sentence_splitter import SentenceSplitter
from src.dialog_manager import DialogManager

logger = setup_logger("main")


class AmiyaSystem:
    """系统主类"""

    def __init__(self):
        self._running = True
        self._consecutive_errors = 0
        self._degraded_until = 0.0
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
        """多轮语音对话 — 唤醒后支持连续对话+打断"""
        logger.info("\n[Milestone 5] Multi-turn Voice Dialogue\n")

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

        dialog = DialogManager(
            max_rounds=config.get("llm.max_context_rounds", 10)
        )

        CONVERSATION_TIMEOUT = 20.0
        SILENCE_TURNS_LIMIT = 3
        MAX_ERRORS = config.get("error_handling.max_consecutive_errors", 5)
        ERROR_COOLDOWN = config.get("error_handling.error_cooldown_seconds", 5)
        POST_TTS_SETTLE = 0.3  # TTS播放后短暂静置，避免残余语音被误捕获

        FALLBACK_MESSAGES = {
            "asr": "抱歉，我没听清楚，能再说一遍吗？",
            "llm": "网络好像不太稳定，请稍后再试。",
        }

        print("\n" + "=" * 50)
        print("  阿米娅 (Amiya) 桌面学习助手")
        print("  多轮语音交互")
        print("=" * 50)
        print()

        while self._running:
            try:
                # ━━ IDLE: 等待唤醒词 ━━
                logger.info("State: IDLE — Waiting for wake word...")
                detected = wake.listen_for_wake_word(audio_handler, vad, asr)
                if not detected or not self._running:
                    continue

                wake.mark_awake()
                dialog.reset()
                logger.info("State: AWAKE — Wake word detected")

                # 唤醒确认
                print("[阿米娅] 嗯，我在听...")
                tts.speak("嗯，我在听，请说。")

                last_activity = time.time()
                empty_turns = 0

                # ━━ 多轮对话循环（无需重复唤醒） ━━
                while self._running:
                    # 检查降级模式冷却
                    if self._degraded_until > 0:
                        if time.time() < self._degraded_until:
                            time.sleep(0.1)
                            continue
                        else:
                            logger.info("Error cooldown expired, resuming normal mode.")
                            self._degraded_until = 0.0
                            self._consecutive_errors = 0

                    # 检查会话超时
                    if time.time() - last_activity > CONVERSATION_TIMEOUT:
                        logger.info("Conversation timeout, returning to IDLE.")
                        break

                    # 录音采集
                    logger.info("State: LISTENING")
                    audio_data = audio_handler.record_until_silence(vad)
                    if not audio_data:
                        empty_turns += 1
                        if empty_turns >= SILENCE_TURNS_LIMIT:
                            logger.info("Too many silent turns, returning to IDLE.")
                            break
                        continue

                    empty_turns = 0

                    # 保存调试录音
                    audio_handler.save_wav(audio_data, "logs/test_recording.wav")

                    # ASR语音识别
                    logger.info("State: PROCESSING — ASR")
                    user_text = asr.recognize_once(audio_data)
                    if not user_text:
                        self._consecutive_errors += 1
                        logger.info(
                            f"ASR returned empty. Errors: {self._consecutive_errors}/{MAX_ERRORS}"
                        )
                        if self._consecutive_errors >= MAX_ERRORS:
                            tts.speak(FALLBACK_MESSAGES["asr"])
                            self._degraded_until = time.time() + ERROR_COOLDOWN
                            logger.warning("Entering degraded mode due to ASR failures.")
                            break
                        continue

                    # 快速启发式过滤：纯噪音/过短文本
                    stripped = user_text.strip()
                    if len(stripped) < 2:
                        logger.info(f"Filtered (too short): '{stripped}'")
                        continue

                    last_activity = time.time()
                    print(f"\n[用户] {user_text}")

                    # 构建多轮对话上下文
                    dialog.add_user_message(user_text)
                    system = llm.build_system_prompt(nickname="博士")
                    messages = dialog.get_messages(system)

                    # ━━ 流式LLM + 句子级TTS ━━
                    logger.info("State: PROCESSING — Streaming LLM + TTS")
                    t0_stream = time.time()

                    tts.start_playback_worker()

                    # LLM响应中检测 [SKIP] 标记（不打断流式，等完整响应后判断）
                    reply = ""
                    skip_detected = False

                    splitter = SentenceSplitter(
                        callback=lambda s: tts.enqueue_sentence(
                            TextSanitizer.sanitize(s)
                        ),
                        min_sentence_len=config.get("streaming.sentence_min_chars", 4),
                    )

                    def on_chunk(delta: str):
                        nonlocal reply, skip_detected
                        reply += delta
                        # 检测 [SKIP] 标记（累积到足够字符后判断）
                        if not skip_detected and "[SKIP]" in reply:
                            skip_detected = True
                            tts.stop_playback()
                        if not skip_detected:
                            splitter.feed(delta)

                    reply = llm.stream_chat(messages, on_text_chunk=on_chunk)

                    # ━━ [SKIP] / [EXIT] 标记处理 ━━
                    if isinstance(reply, str):
                        if skip_detected or reply.strip().startswith("[SKIP]"):
                            logger.info(f"LLM filtered non-addressed speech: '{user_text[:30]}'")
                            tts.stop_playback()
                            dialog.remove_last_user_message()
                            print("[阿米娅] （过滤非对话内容）")
                            last_activity = time.time()
                            continue

                        if "[EXIT]" in reply:
                            logger.info("LLM detected farewell, ending conversation.")
                            farewell = reply.replace("[EXIT]", "").strip()
                            if farewell:
                                tts.start_playback_worker()
                                for s in farewell.split("。"):
                                    clean = TextSanitizer.sanitize(s.strip())
                                    if clean:
                                        tts.enqueue_sentence(clean)
                                tts.wait_for_queue()
                                tts.stop_playback()
                            print(f"[阿米娅] {farewell}")
                            break  # 退出对话循环，回到 IDLE
                    else:
                        # reply 是 dict（含 tool_calls），当前里程碑记录并跳过
                        logger.info(f"LLM returned tool_calls: {reply.get('tool_calls', [])}")
                        print(f"[阿米娅] (工具调用: {reply.get('tool_calls', [])})")

                    # 正常响应：刷新尾部句子
                    remainder = splitter.flush()
                    if remainder:
                        sanitized = TextSanitizer.sanitize(remainder)
                        if sanitized:
                            tts.enqueue_sentence(sanitized)

                    # 等待队列播放完毕
                    tts.wait_for_queue()
                    tts.stop_playback()

                    t1_stream = time.time()
                    logger.info(
                        f"Pipeline done in {t1_stream - t0_stream:.1f}s"
                    )

                    if isinstance(reply, str):
                        if reply:
                            dialog.add_assistant_message(reply)
                            self._consecutive_errors = 0
                        else:
                            self._consecutive_errors += 1
                            logger.warning(
                                f"LLM returned empty. Errors: {self._consecutive_errors}/{MAX_ERRORS}"
                            )
                            if self._consecutive_errors >= MAX_ERRORS:
                                tts.speak(FALLBACK_MESSAGES["llm"])
                                self._degraded_until = time.time() + ERROR_COOLDOWN
                                logger.warning("Entering degraded mode due to LLM failures.")
                                break
                    else:
                        # dict: tool_calls 响应，暂存文本部分供后续里程碑处理
                        text = reply.get("text", "") if isinstance(reply, dict) else ""
                        if text:
                            dialog.add_assistant_message(text)
                        self._consecutive_errors = 0

                    last_activity = time.time()

                    print(f"[阿米娅] {reply if isinstance(reply, str) else reply.get('text', str(reply))}")
                    logger.info(
                        f"State: WAITING — dialog round {dialog.round_count}, "
                        f"history {len(messages)} msgs, errors={self._consecutive_errors}"
                    )

                    # TTS后短暂静置，避免残余声音被下次录音误捕获
                    time.sleep(POST_TTS_SETTLE)

                    print()  # 空行分隔下一轮

            except KeyboardInterrupt:
                break
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(
                    f"Error in conversation loop ({self._consecutive_errors}/{MAX_ERRORS}): {e}"
                )
                if self._consecutive_errors >= MAX_ERRORS:
                    logger.warning("Too many errors, entering degraded mode.")
                    try:
                        tts.speak(FALLBACK_MESSAGES["llm"])
                    except Exception:
                        pass
                    self._degraded_until = time.time() + ERROR_COOLDOWN
                time.sleep(0.5)
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
