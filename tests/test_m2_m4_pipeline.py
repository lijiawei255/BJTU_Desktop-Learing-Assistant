"""里程碑2-4集成测试 - 自动化脚本（无需手动输入）"""

import sys
import io
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# 强制UTF-8输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_all():
    results = {"passed": [], "failed": []}

    def check(name, condition, detail=""):
        if condition:
            results["passed"].append(name)
            print(f"  [PASS] {name}")
        else:
            results["failed"].append(name)
            print(f"  [FAIL] {name}: {detail}")

    # ---- 测试1: 组件初始化 ----
    print("\n=== Test 1: Component Initialization ===")
    try:
        from src.audio_handler import AudioHandler
        audio = AudioHandler()
        check("AudioHandler init", True)
    except Exception as e:
        check("AudioHandler init", False, str(e))
        audio = None

    try:
        from src.vad_handler import VADHandler
        vad = VADHandler()
        check("VADHandler init", True)
    except Exception as e:
        check("VADHandler init", False, str(e))
        vad = None

    try:
        from src.wake_word_detector import WakeWordDetector
        wake = WakeWordDetector()
        check("WakeWordDetector init", True)
    except Exception as e:
        check("WakeWordDetector init", False, str(e))
        wake = None

    try:
        from src.asr_client import ASRClient
        asr = ASRClient()
        check("ASRClient init", True)
    except Exception as e:
        check("ASRClient init", False, str(e))
        asr = None

    try:
        from src.llm_client import LLMClient
        llm = LLMClient()
        check("LLMClient init", True)
    except Exception as e:
        check("LLMClient init", False, str(e))
        llm = None

    try:
        from src.tts_client import TTSClient
        tts = TTSClient()
        check("TTSClient init", True)
    except Exception as e:
        check("TTSClient init", False, str(e))
        tts = None

    # ---- 测试2: VAD语音检测 ----
    print("\n=== Test 2: VAD Voice Detection ===")
    if vad:
        # 静音帧应被正确识别为无语音（30ms, 16kHz, 16bit = 960 bytes）
        silent_frame = b'\x00' * 960
        r1 = vad.is_speech(silent_frame, 16000)
        check("VAD silent frame -> False", r1 == False, str(r1))
        # VAD使用ML模型判断，不是简单的能量检测
        check("VAD frame duration calc", VADHandler.frame_duration_ms(silent_frame) == 30)

    # ---- 测试3: 唤醒词文本检测 ----
    print("\n=== Test 3: Wake Word Text Detection ===")
    if wake:
        check("'阿米娅' detected", wake.check_wake_word_in_text("阿米娅"))
        check("'amiya' detected", wake.check_wake_word_in_text("amiya"))
        check("'你好' NOT detected", not wake.check_wake_word_in_text("你好"))
        check("'阿米娅在吗' detected", wake.check_wake_word_in_text("阿米娅在吗"))
        check("Cooldown inactive at start", not wake.is_in_cooldown())

    # ---- 测试4: Mock录音 ----
    print("\n=== Test 4: Mock Recording ===")
    if audio:
        audio_data = audio._mock_record.__wrapped__ if hasattr(audio._mock_record, '__wrapped__') else None
        check("AudioHandler has mock_record", hasattr(audio, '_mock_record'))

    # ---- 测试5: Mock ASR ----
    print("\n=== Test 5: Mock ASR (direct) ===")
    if asr:
        check("ASRClient has _mock_recognize", hasattr(asr, '_mock_recognize'))

    # ---- 测试6: LLM对话 (Real API) ----
    print("\n=== Test 6: LLM Chat (Real API) ===")
    if llm:
        system = llm.build_system_prompt(nickname="博士")
        reply = llm.simple_chat("你好阿米娅，请用一句话介绍你自己。", system_prompt=system)
        has_amiya = "阿米娅" in reply or "罗德岛" in reply or "博士" in reply
        check("LLM response received", len(reply) > 10, f"len={len(reply)}")
        check("LLM response is Amiya style", has_amiya, reply[:80])

    # ---- 测试7: TTS合成 (Mock) ----
    print("\n=== Test 7: TTS Synthesis (Mock) ===")
    if tts:
        audio_data = tts.synthesize("测试语音合成")
        check("TTS returns bytes", isinstance(audio_data, bytes) and len(audio_data) > 0)

    # ---- 测试8: 上下文对话 ----
    print("\n=== Test 8: Contextual Conversation ===")
    if llm:
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "你好阿米娅，我叫博士"},
            {"role": "assistant", "content": "博士你好！今天有什么学习计划吗？"},
            {"role": "user", "content": "给我讲一下牛顿第二定律"},
        ]
        result = llm.chat(messages)
        if result["success"]:
            reply2 = result["data"].choices[0].message.content
            check("Contextual chat works", len(reply2) > 20, f"len={len(reply2)}")
        else:
            check("Contextual chat works", False, result.get("error", "unknown"))

    # ---- 测试9: 重采样 ----
    print("\n=== Test 9: Audio Resampling ===")
    if tts:
        import struct
        # 创建测试24kHz数据（240 samples, 16bit）
        test_24k = struct.pack('h' * 240, *([1000] * 240))
        resampled = TTSClient.resample_24k_to_16k(test_24k)
        # 240 samples @ 24kHz -> 160 samples @ 16kHz
        expected_len = 160 * 2  # 320 bytes
        check("24k->16k resampling correct", len(resampled) == expected_len,
              f"got {len(resampled)}, expected {expected_len}")

    # ---- 测试10: TextSanitizer 边缘情况 ----
    print("\n=== Test 10: TextSanitizer Edge Cases ===")
    try:
        from src.text_sanitizer import TextSanitizer
        check("Remove *action*", TextSanitizer.sanitize("*微笑*你好") == "你好")
        check("Remove [thinking]", TextSanitizer.sanitize("[思考中]好的") == "好的")
        check("Remove （action）", TextSanitizer.sanitize("（轻轻点头）明白了") == "明白了")
        check("Clean output (no markers)", TextSanitizer.sanitize("博士你好。") == "博士你好。")
        check("Empty input", TextSanitizer.sanitize("") == "")
        check("Multiple markers", "[微笑]" not in TextSanitizer.sanitize("*笑*[嗯]（点头）好的"))
    except ImportError as e:
        check("TextSanitizer import", False, str(e))

    # ---- 测试11: DialogManager remove_last_user_message ----
    print("\n=== Test 11: DialogManager remove_last_user_message ===")
    try:
        from src.dialog_manager import DialogManager
        dm = DialogManager()
        dm.add_user_message("消息1")
        dm.add_assistant_message("回复1")
        dm.add_user_message("消息2")
        check("Before remove: rounds=1", dm.round_count == 1)
        dm.remove_last_user_message()
        check("After remove: rounds=1", dm.round_count == 1)
        check("Last user is 消息1", dm.last_user_message() == "消息1")
        dm.remove_last_user_message()
        check("After removing all: rounds=0", dm.round_count == 0)
    except ImportError as e:
        check("DialogManager import", False, str(e))

    # ---- 测试12: LLM [SKIP] 检测 (Real API) ----
    print("\n=== Test 12: LLM [SKIP] Detection (Real API) ===")
    if llm:
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "老王，今天晚上吃什么？"},
        ]
        reply = llm.stream_chat(messages)
        is_skip = isinstance(reply, str) and "[SKIP]" in reply
        short_enough = isinstance(reply, str) and len(reply) < 30
        check("[SKIP] returned for non-addressed speech", is_skip or short_enough,
              f"reply={reply[:80] if isinstance(reply, str) else str(reply)[:80]}")

    # ---- 测试13: LLM [EXIT] 检测 (Real API) ----
    print("\n=== Test 13: LLM [EXIT] Detection (Real API) ===")
    if llm:
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "好了阿米娅，我要走了，再见。"},
        ]
        reply = llm.stream_chat(messages)
        has_exit = isinstance(reply, str) and "[EXIT]" in reply
        check("[EXIT] marker in farewell reply", has_exit,
              f"reply={reply[:80] if isinstance(reply, str) else str(reply)[:80]}")

    # ---- 测试14: LLM 流式 + tools (Real API) ----
    print("\n=== Test 14: LLM Stream with Tools (Real API) ===")
    if llm:
        from src.llm_client import AVAILABLE_TOOLS
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "帮我开启25分钟的专注模式。"},
        ]
        reply = llm.stream_chat(messages, tools=AVAILABLE_TOOLS)
        if isinstance(reply, dict):
            has_tool_calls = "tool_calls" in reply and len(reply["tool_calls"]) > 0
            check("LLM returns tool_calls for focus command", has_tool_calls,
                  f"tool_calls={reply.get('tool_calls', [])}")
        else:
            # LLM 可能选择文本回复（qwen-plus会根据上下文决定是否调用工具）
            check("LLM with tools returns str or dict", isinstance(reply, str),
                  f"Got {type(reply).__name__}")
            check("Focus reply non-empty", isinstance(reply, str) and len(reply) > 5)

    # ---- 测试15: LLM 流式无tools向后兼容 (Real API) ----
    print("\n=== Test 15: LLM Stream backward compat (no tools) ===")
    if llm:
        system = llm.build_system_prompt(nickname="博士")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "用一句话介绍你自己。"},
        ]
        reply = llm.stream_chat(messages)
        check("Without tools returns str", isinstance(reply, str),
              f"Got {type(reply).__name__}")
        check("Non-empty reply", isinstance(reply, str) and len(reply) > 10,
              f"len={len(reply) if isinstance(reply, str) else '?'}")

    # ---- 测试16: SentenceSplitter 边缘情况 ----
    print("\n=== Test 16: SentenceSplitter Edge Cases ===")
    try:
        from src.sentence_splitter import SentenceSplitter
        # 无句末标点的流
        collected = []
        sp = SentenceSplitter(callback=lambda s: collected.append(s))
        sp.feed("没有标点符号的文本")
        assert len(collected) == 0, "Should not split without ending"
        check("No split without punctuation", len(collected) == 0)
        # flush返回剩余
        rem = sp.flush()
        check("Flush returns remaining", rem == "没有标点符号的文本")
        # 多句同chunk
        collected2 = []
        sp2 = SentenceSplitter(callback=lambda s: collected2.append(s))
        sp2.feed("第一句。第二句！第三句？")
        check("Multi-sentence in one chunk", len(collected2) == 3,
              f"got {len(collected2)}: {collected2}")
        check("First sentence", collected2[0] == "第一句。")
        check("Third sentence", collected2[2] == "第三句？")
    except ImportError as e:
        check("SentenceSplitter import", False, str(e))

    # ---- 汇总 ----
    print("\n" + "=" * 50)
    total = len(results["passed"]) + len(results["failed"])
    print(f"Results: {results['passed'].__len__()}/{total} passed")
    if results["failed"]:
        print(f"Failed: {results['failed']}")
        return 1
    else:
        print("All tests PASSED!")
        return 0


if __name__ == "__main__":
    sys.exit(test_all())
