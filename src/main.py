"""Amiya 桌面学习助手 - 主程序入口"""

import json
import signal
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from src.asr_client import ASRClient
from src.audio_handler import AudioHandler
from src.config import config
from src.dialog_manager import DialogManager
from src.llm_client import AVAILABLE_TOOLS, LLMClient
from src.memory_manager import MemoryManager
from src.sentence_splitter import SentenceSplitter
from src.text_sanitizer import TextSanitizer
from src.tool_executor import ToolExecutor
from src.tts_client import TTSClient
from src.utils.logger import setup_logger
from src.vad_handler import VADHandler
from src.wake_word_detector import WakeWordDetector

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

    def _run_voice_loop(self):
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
            max_rounds=config.get("llm.max_context_rounds", 10),
        )
        memory = MemoryManager()
        dialog._memory = memory
        tool_executor = ToolExecutor()

        CONVERSATION_TIMEOUT = 20.0
        SILENCE_TURNS_LIMIT = 3
        MAX_ERRORS = config.get("error_handling.max_consecutive_errors", 5)
        ERROR_COOLDOWN = config.get("error_handling.error_cooldown_seconds", 5)
        POST_TTS_SETTLE = 0.3  # TTS播放后短暂静置，避免残余语音被误捕获

        FALLBACK_MESSAGES = {
            "asr": "好像没有听清你说什么呢。有需要的时候，再呼唤阿米娅，我就会醒来。",
            "llm": "网络好像不太稳定，请稍后再呼唤阿米娅试试哦。",
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

                    # 检查专注计时器是否到期
                    if tool_executor.timer_expired:
                        logger.info("Focus timer expired — auto-ending focus mode")
                        exec_result = tool_executor.execute(
                            "end_focus_mode", {"_auto_expired": True}
                        )
                        tts.enqueue_sentence(exec_result["result"])
                        tool_executor.timer_expired = False
                        print(f"[阿米娅] {exec_result['result']}")

                    # 检查会话超时
                    if time.time() - last_activity > CONVERSATION_TIMEOUT:
                        logger.info("Conversation timeout, returning to IDLE.")
                        tts.speak("有需要的时候，再呼唤阿米娅，我就会醒来哦。")
                        break

                    # 录音采集
                    logger.info("State: LISTENING")
                    audio_data = audio_handler.record_until_silence(vad)
                    if not audio_data:
                        empty_turns += 1
                        if empty_turns >= SILENCE_TURNS_LIMIT:
                            logger.info("Too many silent turns, returning to IDLE.")
                            tts.speak(
                                "好像没有听到你说什么哦。有需要的时候，再呼唤阿米娅，我就会醒来。"
                            )
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
                            logger.warning(
                                "Entering degraded mode due to ASR failures."
                            )
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
                    system = llm.build_system_prompt(
                        nickname=tool_executor.user_nickname,
                        focus_status=tool_executor.get_status_for_llm(),
                        memory_summary=memory.get_memory_summary(),
                    )
                    messages = dialog.get_messages(
                        system, memory_summary=memory.get_memory_summary()
                    )

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

                    reply = llm.stream_chat(
                        messages, on_text_chunk=on_chunk, tools=AVAILABLE_TOOLS
                    )

                    # ━━ [SKIP] / [EXIT] 标记处理 ━━
                    if isinstance(reply, str):
                        if skip_detected or reply.strip().startswith("[SKIP]"):
                            logger.info(
                                f"LLM filtered non-addressed speech: '{user_text[:30]}'"
                            )
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
                        # reply 是 dict（含 tool_calls），执行工具并反馈给LLM
                        tool_calls = reply.get("tool_calls", [])
                        if not tool_calls:
                            logger.warning("LLM returned dict without tool_calls")
                            continue

                        logger.info(
                            f"LLM returned {len(tool_calls)} tool_calls: {tool_calls}"
                        )

                        # 执行每个工具调用，并立即播放语音反馈
                        tool_results = []
                        for tc in tool_calls:
                            fn_name = tc["function"]["name"]
                            try:
                                fn_args = json.loads(tc["function"]["arguments"])
                            except (json.JSONDecodeError, KeyError):
                                fn_args = {}
                            exec_result = tool_executor.execute(fn_name, fn_args)
                            logger.info(f"Tool {fn_name}({fn_args}) -> {exec_result}")
                            tool_results.append(exec_result)
                            print(f"[阿米娅] (执行操作: {exec_result['result']})")
                            # 工具执行后立即播放语音反馈
                            if exec_result.get("success"):
                                tts.enqueue_sentence(exec_result["result"])
                            # 昵称变更同步到长期记忆
                            if fn_name == "set_user_nickname" and exec_result.get("success"):
                                nickname = fn_args.get("nickname", "")
                                if nickname:
                                    memory.set_nickname(nickname)

                        # 将工具调用和结果注入对话历史
                        dialog.add_tool_interaction(
                            reply.get("text", ""), tool_calls, tool_results
                        )

                        # 再次请求LLM，基于工具结果生成自然语言回复
                        # 重置流式状态（reply 此时是 dict，on_chunk 需要 str）
                        skip_detected = False
                        reply = ""
                        system = llm.build_system_prompt(
                            nickname=tool_executor.user_nickname,
                            focus_status=tool_executor.get_status_for_llm(),
                            memory_summary=memory.get_memory_summary(),
                        )
                        followup_messages = dialog.get_messages(
                            system, memory_summary=memory.get_memory_summary()
                        )
                        reply = llm.stream_chat(
                            followup_messages, on_text_chunk=on_chunk
                        )

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
                    logger.info(f"Pipeline done in {t1_stream - t0_stream:.1f}s")

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
                                logger.warning(
                                    "Entering degraded mode due to LLM failures."
                                )
                                break
                    else:
                        # dict: tool_calls 响应，暂存文本部分供后续里程碑处理
                        text = reply.get("text", "") if isinstance(reply, dict) else ""
                        if text:
                            dialog.add_assistant_message(text)
                        self._consecutive_errors = 0

                    last_activity = time.time()

                    print(
                        f"[阿米娅] {reply if isinstance(reply, str) else reply.get('text', str(reply))}"
                    )
                    logger.info(
                        f"State: WAITING — dialog round {dialog.round_count}, "
                        f"history {len(messages)} msgs, errors={self._consecutive_errors}"
                    )

                    # TTS后短暂静置，避免残余声音被下次录音误捕获
                    time.sleep(POST_TTS_SETTLE)

                    print()  # 空行分隔下一轮

                # ━━ 会话结束：保存到记忆 ━━
                history = dialog.get_history()
                if history:
                    memory.save_session(history, tool_executor.user_nickname)
                    logger.info("Conversation session saved to memory.")

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

        logger.info("\nVoice loop ended.")

    def run(self):
        """主循环"""
        try:
            self._run_voice_loop()
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
