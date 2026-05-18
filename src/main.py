"""Amiya 桌面学习助手 - 主程序入口 (M8: 多进程架构 + 消息总线)"""

import json
import signal
import sys
import threading
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
from src.message_bus import MessageBus, IPCMessage, MessageType
from src.sentence_splitter import SentenceSplitter
from src.text_sanitizer import TextSanitizer
from src.tool_executor import ToolExecutor
from src.tts_client import TTSClient
from src.utils.logger import setup_logger
from src.vad_handler import VADHandler
from src.wake_word_detector import WakeWordDetector

logger = setup_logger("main")


def _strip_wake_prefix(text: str, wake) -> str:
    """去除文本开头的唤醒词，返回实际指令部分。"""
    text = text.strip()
    text_clean = text.lower().replace(" ", "")
    for word in wake.CORE_WAKE_PREFIXES:
        w = word.lower().replace(" ", "")
        if text_clean.startswith(w):
            result = text[len(word):].strip()
            while result and result[0] in "，。！？,.!?;；:：~～":
                result = result[1:].strip()
            return result if result else text
    return text


class AmiyaSystem:
    """系统主类 (M8: 集成消息总线 + 传感器子进程)"""

    def __init__(self):
        self._running = True
        self._consecutive_errors = 0
        self._degraded_until = 0.0
        self._last_posture_alert = 0.0  # 坐姿提醒冷却
        self._last_phone_state = False  # 最近一次IR传感器手机状态
        self._sensor_checker_thread: threading.Thread | None = None
        signal.signal(signal.SIGINT, self._handle_signal)

        # M8: 消息总线 + 关闭信号
        self.bus = MessageBus()
        self.shutdown_event = threading.Event()
        self._sensor_thread: threading.Thread | None = None

        logger.info("=" * 50)
        logger.info("Amiya Desktop Learning Assistant Starting...")
        logger.info(f"Project root: {PROJECT_ROOT}")
        logger.info(f"Mock mode: {config.is_mock}")
        logger.info("=" * 50)

    def _handle_signal(self, signum, frame):
        """处理 Ctrl+C 信号"""
        logger.info("Received stop signal.")
        self._running = False

    def _start_sensor_process(self):
        """M8: 启动传感器子进程/线程"""
        from src.processes.sensor_process import sensor_process_loop

        if config.is_mock:
            # Mock 模式：线程运行
            self._sensor_thread = threading.Thread(
                target=sensor_process_loop,
                args=(self.bus, self.shutdown_event, 0.2),
                daemon=True,
                name="sensor-proc",
            )
            self._sensor_thread.start()
            logger.info("Sensor thread started (mock mode)")
        else:
            # 真实多进程模式
            import multiprocessing
            self._sensor_process = multiprocessing.Process(
                target=sensor_process_loop,
                args=(self.bus, self.shutdown_event, 0.2),
                name="sensor-proc",
                daemon=True,
            )
            self._sensor_process.start()
            logger.info("Sensor subprocess started (real mode)")

    def _stop_sensor_process(self):
        """M8: 停止传感器子进程"""
        self.shutdown_event.set()
        if self._sensor_thread and self._sensor_thread.is_alive():
            self._sensor_thread.join(timeout=2.0)
            logger.info("Sensor thread stopped")

    def _start_sensor_checker(self, tool_executor: "ToolExecutor"):
        """后台线程：持续处理传感器消息，确保IDLE态也能收到坐姿/手机提醒"""
        def _sensor_check_loop():
            while not self.shutdown_event.is_set():
                try:
                    self._check_sensor_messages(tool_executor)
                except Exception as e:
                    logger.error(f"Sensor checker error: {e}")
                time.sleep(0.5)

        self._sensor_checker_thread = threading.Thread(
            target=_sensor_check_loop, daemon=True, name="sensor-checker"
        )
        self._sensor_checker_thread.start()
        logger.info("Sensor checker thread started")

    def _stop_sensor_checker(self):
        """停止传感器检查线程"""
        if self._sensor_checker_thread and self._sensor_checker_thread.is_alive():
            self._sensor_checker_thread.join(timeout=2.0)
            logger.info("Sensor checker thread stopped")

    def _check_sensor_messages(self, tool_executor: ToolExecutor):
        """M8: 检查传感器消息并分发到状态机"""
        msg = self.bus.receive(timeout=0)
        while msg is not None:
            if msg.type == MessageType.PHONE_DETECTED:
                self._last_phone_state = True
                logger.info(f"[Sensor] Phone detected: {msg.payload}")
                if tool_executor.state_ctrl.state.name == "WAITING_PHONE":
                    # 等待放手机状态 → 触发关盖
                    result = tool_executor.state_ctrl.phone_inserted()
                    logger.info(f"[State] phone_inserted: {result}")
                elif tool_executor.state_ctrl.state.name == "PAUSED":
                    # 暂停中放回手机 → 恢复
                    result = tool_executor.state_ctrl.phone_inserted()
                    logger.info(f"[State] phone_inserted: {result}")

            elif msg.type == MessageType.PHONE_REMOVED:
                self._last_phone_state = False
                logger.info(f"[Sensor] Phone removed: {msg.payload}")
                if tool_executor.state_ctrl.state.name == "FOCUSING":
                    result = tool_executor.state_ctrl.phone_removed()
                    logger.info(f"[State] phone_removed: {result}")

            elif msg.type == MessageType.DISTANCE_TOF:
                distance = msg.payload.get("distance_mm", 0)
                logger.debug(f"[Sensor] TOF distance: {distance}mm")

            elif msg.type == MessageType.POSTURE_WARNING:
                recovered = msg.payload.get("recovered", False)
                if not recovered and time.time() - self._last_posture_alert > 30:
                    logger.info(f"[Sensor] 坐姿警告: {msg.payload.get('distance_mm')}mm")
                    self._last_posture_alert = time.time()
                    import threading
                    threading.Thread(
                        target=lambda: tool_executor._speak_alert("博士，离桌面太近了哦！"),
                        daemon=True
                    ).start()

            elif msg.type == MessageType.HEARTBEAT:
                logger.debug(f"[Sensor] Heartbeat from {msg.source}")

            msg = self.bus.receive(timeout=0)

        # 兜底：传感器仅在状态变化时发送消息，若启动时已检测到手机但
        # PHONE_DETECTED 在IDLE期间被丢弃，WAITING_PHONE会永远卡住。
        # 此处根据最近一次已知状态主动触发。
        if (self._last_phone_state
                and tool_executor.state_ctrl.state.name == "WAITING_PHONE"):
            result = tool_executor.state_ctrl.phone_inserted()
            logger.info(f"[State] phone_inserted (fallback): {result}")

    def _run_voice_loop(self):
        """多轮语音对话 — 唤醒后支持连续对话+打断 (M8: 传感器消息处理)"""
        logger.info("\n[Milestone 7+8] Multi-turn Voice Dialogue with State Machine + Sensor Bus\n")

        # 初始化所有组件
        try:
            audio_handler = AudioHandler()
            vad = VADHandler()
            wake = WakeWordDetector()
            asr = ASRClient()
            llm = LLMClient()
            tts = TTSClient()
            tts.set_shared_pa(audio_handler._pa)
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
        tool_executor.tts = tts  # 注入TTS供走神/坐姿提醒使用
        tool_executor.state.on_tts_speak = tts.speak  # 状态机TTS播报回调

        # M8: 启动传感器进程 + 后台传感器检查线程
        self._start_sensor_process()
        self._start_sensor_checker(tool_executor)

        CONVERSATION_TIMEOUT = config.get("audio.conversation_timeout_seconds", 6)
        SILENCE_TURNS_LIMIT = 2
        MAX_ERRORS = config.get("error_handling.max_consecutive_errors", 5)
        ERROR_COOLDOWN = config.get("error_handling.error_cooldown_seconds", 5)
        POST_TTS_SETTLE = 0.3

        FALLBACK_MESSAGES = {
            "asr": "好像没有听清你说什么呢。有需要的时候，再呼唤阿米娅，我就会醒来。",
            "llm": "网络好像不太稳定，请稍后再呼唤阿米娅试试哦。",
        }

        print("\n" + "=" * 50)
        print("  阿米娅 (Amiya) 桌面学习助手")
        print("  多轮语音交互 (M8: 状态机 + 传感器总线)")
        print("=" * 50)
        print()

        # 启动欢迎语音提示
        logger.info("Playing welcome greeting...")
        tts.speak("欢迎使用阿米娅桌面学习助手。请说阿米娅唤醒我，开始交互。")
        time.sleep(0.3)  # 等待ALSA释放音频设备

        while self._running:
            try:
                # ━━ IDLE: 等待唤醒词 ━━
                logger.info("State: IDLE — Waiting for wake word...")
                detected = wake.listen_for_wake_word(audio_handler, vad, asr, pa_instance=audio_handler._pa)
                if not detected or not self._running:
                    # M8: 空闲时也检查传感器消息
                    self._check_sensor_messages(tool_executor)
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
                    # M8: 检查传感器消息
                    self._check_sensor_messages(tool_executor)

                    # 检查降级模式冷却
                    if self._degraded_until > 0:
                        if time.time() < self._degraded_until:
                            time.sleep(0.1)
                            continue
                        else:
                            logger.info("Error cooldown expired, resuming normal mode.")
                            self._degraded_until = 0.0
                            self._consecutive_errors = 0

                    # M7: 检查专注计时器是否到期（StateController）
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
                    audio_data = audio_handler.record_until_silence(vad, max_seconds=8)
                    if not audio_data:
                        empty_turns += 1
                        last_activity = time.time()
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
                        last_activity = time.time()
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
                        last_activity = time.time()
                        logger.info(f"Filtered (too short): '{stripped}'")
                        continue

                    last_activity = time.time()
                    print(f"\n[用户] {user_text}")

                    # 构建多轮对话上下文
                    dialog.add_user_message(user_text)
                    system = llm.build_system_prompt(
                        nickname=memory.get_nickname(),
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
                        if not skip_detected and "[SKIP]" in reply:
                            skip_detected = True
                            tts.stop_playback()
                        if not skip_detected:
                            splitter.feed(delta)

                    reply = llm.stream_chat(
                        messages, on_text_chunk=on_chunk,
                        tools=AVAILABLE_TOOLS, tool_choice="auto",
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
                            break

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
                        skip_detected = False
                        reply = ""
                        system = llm.build_system_prompt(
                            nickname=memory.get_nickname(),
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
                    while tts.is_playing and self._running:
                        time.sleep(0.1)

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

                    time.sleep(POST_TTS_SETTLE)
                    print()

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
        """M8: 优雅关闭 — 停止子进程 + 清理资源"""
        logger.info("Shutting down...")
        self._stop_sensor_checker()
        self._stop_sensor_process()
        self.bus.drain()
        logger.info("Goodbye!")


def main():
    app = AmiyaSystem()
    app.run()


if __name__ == "__main__":
    main()
