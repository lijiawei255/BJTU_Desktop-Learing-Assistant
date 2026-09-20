"""无头Mock模式集成测试 — 全自动化，无需硬件，无需人工。

用法：
  # 运行所有非API测试
  python -m pytest tests/test_headless_integration.py -v

  # 云API测试位于 test_m2_m4_pipeline.py，需显式 --run-api

所有测试在 mock.enabled=true + mock.headless=true 下运行。
"""

import threading
import time
import pytest
from src.config import config
from src.headless_input import headless_input


# ═══════════════════════════════════════════════════════════════
# TestHeadlessInput — 无头输入系统基础测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestHeadlessInput:
    """HeadlessInput 单例和队列行为测试。"""

    def test_singleton_returns_same_instance(self):
        from src.headless_input import HeadlessInput
        a = HeadlessInput()
        b = HeadlessInput()
        assert a is b

    def test_feed_and_get_input(self):
        headless_input.clear()
        headless_input.feed("test_value")
        result = headless_input.get_input()
        assert result == "test_value"

    def test_feed_sequence_preserves_order(self):
        headless_input.clear()
        headless_input.feed_sequence(["first", "second", "third"])
        assert headless_input.get_input() == "first"
        assert headless_input.get_input() == "second"
        assert headless_input.get_input() == "third"

    def test_empty_queue_timeout_returns_empty(self):
        headless_input.clear()
        from src.headless_input import HeadlessInput
        hi = HeadlessInput()
        saved = hi._default_timeout
        hi._default_timeout = 0.1
        result = hi.get_input()
        assert result == ""
        hi._default_timeout = saved

    def test_clear_empties_queue(self):
        headless_input.feed("value1")
        headless_input.feed("value2")
        headless_input.clear()
        result = headless_input.get_input()
        assert result == ""

    def test_enabled_in_test_environment(self):
        assert headless_input.enabled is True


# ═══════════════════════════════════════════════════════════════
# TestTTSMockPlaybackWorker — Mock模式TTS不创建PyAudio（无需API）
# ═══════════════════════════════════════════════════════════════

class TestTTSMockPlaybackWorker:
    """验证Mock模式下TTS播放不创建PyAudio实例 — 这是树莓派声卡冲突的根源。"""

    def test_mock_playback_worker_no_pyaudio(self, monkeypatch):
        from unittest.mock import Mock
        from src.tts_client import TTSClient
        tts = TTSClient()
        synthesize = Mock(wraps=tts.synthesize)
        monkeypatch.setattr(tts, "synthesize", synthesize)
        tts.start_playback_worker()
        tts.enqueue_sentence("测试播放。")

        time.sleep(0.5)
        tts.wait_for_queue(timeout=2.0)
        synthesize.assert_called_once_with("测试播放。")
        assert not tts.is_playing, "Playback did not finish before timeout"
        assert tts._pyaudio_instance is None
        tts.stop_playback()

    def test_mock_playback_multiple_sentences(self, monkeypatch):
        from unittest.mock import Mock, call
        from src.tts_client import TTSClient
        tts = TTSClient()
        synthesize = Mock(wraps=tts.synthesize)
        monkeypatch.setattr(tts, "synthesize", synthesize)
        tts.start_playback_worker()
        tts.enqueue_sentence("第一句。")
        tts.enqueue_sentence("第二句。")
        tts.enqueue_sentence("第三句。")

        tts.wait_for_queue(timeout=5.0)
        assert synthesize.call_args_list == [call("第一句。"), call("第二句。"), call("第三句。")]
        assert not tts.is_playing, "Playback did not finish before timeout"
        assert tts._pyaudio_instance is None
        assert tts._sentence_queue.empty()
        tts.stop_playback()

    def test_mock_speak_does_not_crash(self):
        from src.tts_client import TTSClient
        tts = TTSClient()
        result = tts.speak("测试直接播放。")
        assert result is True


# ═══════════════════════════════════════════════════════════════
# TestFocusModeLifecycle — 专注模式状态机完整生命周期（无需API）
# ═══════════════════════════════════════════════════════════════

class TestFocusModeLifecycle:
    """专注模式完整生命周期测试。"""

    def test_full_focus_lifecycle(self):
        from src.tool_executor import ToolExecutor
        from src.state_controller import FocusState

        te = ToolExecutor()
        sc = te.state_ctrl

        # Step 1: 开启专注
        result = sc.start_focus(25)
        assert result["success"]
        assert sc.state == FocusState.WAITING_PHONE

        # Step 2: 放入手机 → 关盖 → 开始计时（传感器子进程→MessageBus→主循环分发）
        result = sc.phone_inserted()
        assert result["success"]
        assert sc.state == FocusState.FOCUSING

        # Step 3: 暂时取出手机 → 暂停
        result = sc.phone_removed()
        assert result["success"]
        assert sc.state == FocusState.PAUSED

        # Step 4: 放回手机 → 恢复
        result = sc.phone_inserted()
        assert result["success"]
        assert sc.state == FocusState.FOCUSING

        # Step 5: 完成专注
        result = sc.complete_focus(auto_expired=True)
        assert result["success"]
        assert sc.state == FocusState.IDLE

    def test_cancel_focus_from_waiting_phone(self):
        from src.tool_executor import ToolExecutor
        from src.state_controller import FocusState

        te = ToolExecutor()
        te.state_ctrl.start_focus(25)
        assert te.state_ctrl.state == FocusState.WAITING_PHONE

        te.state_ctrl.cancel_focus()
        assert te.state_ctrl.state == FocusState.IDLE

    def test_cancel_focus_from_paused(self):
        from src.tool_executor import ToolExecutor
        from src.state_controller import FocusState

        te = ToolExecutor()
        te.state_ctrl.start_focus(25)
        te.state_ctrl.phone_inserted()
        te.state_ctrl.phone_removed()
        assert te.state_ctrl.state == FocusState.PAUSED

        te.state_ctrl.cancel_focus()
        assert te.state_ctrl.state == FocusState.IDLE


# ═══════════════════════════════════════════════════════════════
# TestToolExecution — 工具执行器集成测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestToolExecution:
    """ToolExecutor 工具执行集成测试。"""

    def test_set_nickname_and_query_status(self):
        from src.tool_executor import ToolExecutor

        te = ToolExecutor()

        r1 = te.execute("set_user_nickname", {"nickname": "指挥官"})
        assert r1["success"]
        assert te.user_nickname == "指挥官"

        r2 = te.execute("get_focus_status", {})
        assert r2["success"]
        assert "未开启" in r2["result"] or "专注" in r2["result"]

        config.set("system.nickname", "博士")

    def test_focus_mode_conflict_detection(self):
        from src.tool_executor import ToolExecutor

        te = ToolExecutor()
        r1 = te.execute("set_focus_mode", {"duration_minutes": 30})
        assert r1["success"]

        r2 = te.execute("set_focus_mode", {"duration_minutes": 10})
        assert not r2["success"]
        assert "无法" in r2["result"] or "WAITING" in r2["result"] or "进行中" in r2["result"]

        te.state_ctrl.cancel_focus()

    def test_end_focus_when_no_active(self):
        from src.tool_executor import ToolExecutor

        te = ToolExecutor()
        r = te.execute("end_focus_mode", {})
        assert not r["success"]


# ═══════════════════════════════════════════════════════════════
# TestSensorMessageHandling — 传感器消息处理（无需API）
# ═══════════════════════════════════════════════════════════════

class TestSensorMessageHandling:
    """传感器消息通过MessageBus分发到状态机。"""

    def test_phone_detected_message_routes_to_state_machine(self):
        from src.message_bus import MessageBus, IPCMessage, MessageType
        from src.tool_executor import ToolExecutor

        from src.main import AmiyaSystem
        app = AmiyaSystem()
        bus = app.bus
        te = ToolExecutor()

        te.state_ctrl.start_focus(25)
        assert te.state_ctrl.state.name == "WAITING_PHONE"

        # 模拟传感器检测到手机：直接放入to_main队列（传感器→主进程方向）
        msg = IPCMessage(
            type=MessageType.PHONE_DETECTED,
            source="sensor",
        )
        bus.to_main.put(msg)

        app._check_sensor_messages(te)
        assert app._last_phone_state is True
        assert te.state_ctrl.state.name == "FOCUSING"

        te.state_ctrl.cancel_focus()

    def test_phone_removed_triggers_pause(self):
        from src.tool_executor import ToolExecutor

        te = ToolExecutor()
        te.state_ctrl.start_focus(25)
        te.state_ctrl.phone_inserted()
        assert te.state_ctrl.state.name == "FOCUSING"

        result = te.state_ctrl.phone_removed()
        assert result["success"]
        assert te.state_ctrl.state.name == "PAUSED"

        te.state_ctrl.cancel_focus()

    def test_heartbeat_message_routing(self):
        from src.message_bus import MessageBus, IPCMessage, MessageType

        bus = MessageBus()
        msg = IPCMessage(
            type=MessageType.HEARTBEAT,
            source="sensor-proc",
        )
        bus.to_main.put(msg)

        received = bus.receive(timeout=0.1)
        assert received is not None
        assert received.type == MessageType.HEARTBEAT
        assert received.source == "sensor-proc"


# ═══════════════════════════════════════════════════════════════
# TestErrorRecovery — 错误恢复和降级模式（无需API）
# ═══════════════════════════════════════════════════════════════

class TestSystemLifecycle:
    """Exercise actual signal and sensor-thread shutdown behavior."""

    def test_stop_signal_stops_main_loop(self):
        import signal
        from src.main import AmiyaSystem
        app = AmiyaSystem()
        app._handle_signal(signal.SIGINT, None)
        assert app._running is False

    def test_shutdown_stops_sensor_thread(self):
        from src.main import AmiyaSystem
        app = AmiyaSystem()
        app._start_sensor_process()
        try:
            assert app.bus.receive(timeout=2) is not None
        finally:
            app.shutdown()
        assert app.shutdown_event.is_set()
        assert not app._sensor_thread.is_alive()


# ═══════════════════════════════════════════════════════════════
# TestConversationTimeout — 会话超时（无需API）
# ═══════════════════════════════════════════════════════════════

class TestConversationConfig:
    """Configuration persistence is tested in the per-test temporary directory."""

    def test_timeout_configuration_is_saved(self, isolated_runtime):
        import json
        config.set("audio.conversation_timeout_seconds", 5)
        saved = json.loads((isolated_runtime / "data/config.json").read_text(encoding="utf-8"))
        assert saved["audio"]["conversation_timeout_seconds"] == 5
        assert "api_keys" not in saved


# ═══════════════════════════════════════════════════════════════
# TestWakeWordMockHeadless — 无头模式唤醒词测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestWakeWordMockHeadless:
    """无头模式下唤醒词检测测试。"""

    def test_empty_input_triggers_wake(self):
        from src.wake_word_detector import WakeWordDetector

        headless_input.clear()
        headless_input.feed("")  # 空输入

        wake = WakeWordDetector()
        result = wake._mock_listen()
        assert result is True

    def test_valid_wake_word_triggers_wake(self):
        from src.wake_word_detector import WakeWordDetector

        headless_input.clear()
        headless_input.feed("阿米娅")

        wake = WakeWordDetector()
        result = wake._mock_listen()
        assert result is True

    def test_random_text_does_not_trigger_wake(self):
        from src.wake_word_detector import WakeWordDetector

        headless_input.clear()
        headless_input.feed("今天天气不错")

        wake = WakeWordDetector()
        result = wake._mock_listen()
        assert result is False


# ═══════════════════════════════════════════════════════════════
# TestASRMockHeadless — 无头模式ASR测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestASRMockHeadless:
    """无头模式下ASR Mock识别测试。"""

    def test_asr_returns_fed_text(self):
        from src.asr_client import ASRClient

        headless_input.clear()
        headless_input.feed("阿米娅，帮我设置25分钟专注。")

        asr = ASRClient()
        result = asr._mock_recognize()
        assert result == "阿米娅，帮我设置25分钟专注。"

    def test_asr_empty_input_returns_none(self):
        from src.asr_client import ASRClient

        headless_input.clear()
        headless_input.feed("")

        asr = ASRClient()
        result = asr._mock_recognize()
        assert result is None


# ═══════════════════════════════════════════════════════════════
# TestAudioMockHeadless — 无头模式录音测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestAudioMockHeadless:
    """无头模式下Mock录音测试。"""

    def test_mock_record_returns_silence_in_headless(self):
        from src.audio_handler import AudioHandler

        ah = AudioHandler()
        result = ah._mock_record()
        assert result is not None
        assert len(result) == 1600  # 100ms at 16kHz×16bit


# ═══════════════════════════════════════════════════════════════
# TestHeadlessVoiceLoop — 使用脚本化响应的离线主循环测试
# ═══════════════════════════════════════════════════════════════

class TestHeadlessVoiceLoop:
    """Run the real main loop with scripted LLM/ASR responses and a TTS recorder."""

    @pytest.mark.parametrize("with_tool", [False, True])
    def test_scripted_conversation_exits_and_saves(self, monkeypatch, isolated_runtime, with_tool):
        import copy
        import json
        from src import main

        app = main.AmiyaSystem()
        requests = []
        spoken = []
        transcripts = iter(["查询专注状态", "再见"] if with_tool else ["再见"])
        turns = iter([
            {"text": "", "tool_calls": [{"id": "call-1", "type": "function",
                "function": {"name": "get_focus_status", "arguments": "{}"}}]},
            "当前没有进行专注模式。", "[EXIT] 再见。",
        ] if with_tool else ["[EXIT] 再见。"])
        wake_count = 0

        def wake(*args, **kwargs):
            nonlocal wake_count
            wake_count += 1
            if wake_count > 1:
                app._running = False
                return False
            return True

        def stream(self, messages, on_text_chunk=None, **kwargs):
            requests.append(copy.deepcopy(messages))
            reply = next(turns)
            if isinstance(reply, str) and on_text_chunk:
                on_text_chunk(reply)
            return reply

        class RecordingTTS:
            is_playing = False
            def set_shared_pa(self, pa):
                assert pa is None
            def speak(self, text):
                spoken.append(text)
                return True
            def enqueue_sentence(self, text):
                spoken.append(text)
            def start_playback_worker(self):
                pass
            def stop_playback(self):
                pass
            def wait_for_queue(self):
                pass

        monkeypatch.setattr(main, "TTSClient", RecordingTTS)
        monkeypatch.setattr(main.WakeWordDetector, "listen_for_wake_word", wake)
        monkeypatch.setattr(main.ASRClient, "recognize_once", lambda self, audio: next(transcripts))
        monkeypatch.setattr(main.LLMClient, "stream_chat", stream)
        app.run()
        assert len(requests) == (3 if with_tool else 1)
        if with_tool:
            assert any(m.get("role") == "tool" and m["content"] == "当前没有进行专注模式。"
                       for m in requests[1])
            assert "当前没有进行专注模式。" in spoken
        assert any("再见" in text for text in spoken)
        saved = json.loads((isolated_runtime / "data/memory_today.json").read_text(encoding="utf-8"))
        assert saved["session_count"] == 1
        assert "再见" in saved["recent_sessions"][0]["summary"]
        assert app.shutdown_event.is_set()
        assert not app._sensor_thread.is_alive()
        # The unchanged shutdown requests checker exit after its initial join.
        # Wait for that request to take effect; do not change production ordering.
        app._sensor_checker_thread.join(timeout=2)
        assert not app._sensor_checker_thread.is_alive()


# ═══════════════════════════════════════════════════════════════
# TestAudioMockRecordHeadless — AudioHandler无头录音（无需API）
# ═══════════════════════════════════════════════════════════════

class TestAudioMockRecordHeadless:
    """AudioHandler在无头Mock模式下的行为测试。"""

    def test_record_until_silence_headless(self):
        from src.audio_handler import AudioHandler
        from src.vad_handler import VADHandler

        ah = AudioHandler()
        vad = VADHandler()

        # 无头模式下 record_until_silence 应直接返回静音数据
        result = ah.record_until_silence(vad)
        assert result is not None
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════
# TestTTSMockSafety — TTS Mock模式安全性回归测试（无需API）
# ═══════════════════════════════════════════════════════════════

class TestTTSMockSafety:
    """确保TTS在Mock音频模式下绝不创建PyAudio实例。"""

    def test_synthesize_mock_no_pyaudio(self):
        import sys
        # 确保pyaudio未被导入
        if "pyaudio" in sys.modules:
            del sys.modules["pyaudio"]

        from src.tts_client import TTSClient
        tts = TTSClient()
        result = tts.synthesize("测试合成。")
        assert result is not None
        assert len(result) > 0
        # pyaudio不应被导入
        assert "pyaudio" not in sys.modules

    def test_start_playback_worker_no_pyaudio(self):
        import sys
        if "pyaudio" in sys.modules:
            del sys.modules["pyaudio"]

        from src.tts_client import TTSClient
        tts = TTSClient()
        tts.start_playback_worker()
        tts.enqueue_sentence("安全测试。")
        tts.wait_for_queue(timeout=3.0)
        tts.stop_playback()

        assert "pyaudio" not in sys.modules
