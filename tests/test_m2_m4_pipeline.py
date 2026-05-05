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
