"""PC pipeline checks; cloud calls require --run-api. No device access."""

import pytest

from src.audio_handler import AudioHandler
from src.asr_client import ASRClient
from src.dialog_manager import DialogManager
from src.headless_input import headless_input
from src.llm_client import AVAILABLE_TOOLS, LLMClient
from src.sentence_splitter import SentenceSplitter
from src.text_sanitizer import TextSanitizer
from src.tts_client import TTSClient
from src.vad_handler import VADHandler
from src.wake_word_detector import WakeWordDetector


def test_component_initialization():
    audio = AudioHandler()
    assert audio._pa is None
    assert VADHandler().vad is not None
    assert WakeWordDetector().is_in_cooldown() is False
    assert ASRClient().sample_rate == 16000
    assert LLMClient().system_prompt_template
    assert TTSClient().sample_rate == 24000


def test_vad_silent_frame():
    frame = bytes(960)
    assert VADHandler().is_speech(frame, 16000) is False
    assert VADHandler.frame_duration_ms(frame) == 30


def test_mock_record_and_asr():
    audio = AudioHandler().record_until_silence(VADHandler())
    assert audio == bytes(1600)
    headless_input.feed("你好阿米娅")
    assert ASRClient().recognize_once(audio) == "你好阿米娅"


def test_mock_tts_and_resampling():
    assert isinstance(TTSClient().synthesize("测试语音"), bytes)
    import struct
    pcm = struct.pack("h" * 240, *([1000] * 240))
    converted = TTSClient.resample_24k_to_16k(pcm)
    assert struct.unpack("h" * 160, converted) == (1000,) * 160


@pytest.mark.parametrize("text, expected", [
    ("*微笑*你好", "你好"), ("[思考中]好的", "好的"),
    ("（轻轻点头）明白了", "明白了"), ("博士你好。", "博士你好。"),
    ("", ""), ("*笑*[嗯]（点头）好的", "好的"),
])
def test_text_sanitizer(text, expected):
    assert TextSanitizer.sanitize(text) == expected


def test_remove_last_user_message_preserves_other_messages():
    dialog = DialogManager()
    dialog.add_user_message("消息1")
    dialog.add_assistant_message("回复1")
    dialog.add_user_message("消息2")
    dialog.remove_last_user_message()
    assert dialog.get_history() == [
        {"role": "user", "content": "消息1"},
        {"role": "assistant", "content": "回复1"},
    ]
    assert dialog.last_user_message() == "消息1"


def test_sentence_splitter_flush():
    collected = []
    splitter = SentenceSplitter(collected.append)
    splitter.feed("没有标点符号的文本")
    assert collected == []
    assert splitter.flush() == "没有标点符号的文本"
    assert splitter.flush() == ""


def test_sentence_splitter_multiple_sentences():
    collected = []
    splitter = SentenceSplitter(collected.append)
    splitter.feed("第一句。第二句！第三句？")
    assert collected == ["第一句。", "第二句！", "第三句？"]


@pytest.mark.api
def test_llm_chat_with_context():
    llm = LLMClient()
    result = llm.chat([
        {"role": "system", "content": llm.build_system_prompt()},
        {"role": "user", "content": "我正在复习牛顿第二定律。"},
        {"role": "assistant", "content": "我们一起复习。"},
        {"role": "user", "content": "用一句话解释它。"},
    ])
    assert result["success"], result.get("error")
    assert result["data"].choices[0].message.content.strip()


@pytest.mark.api
def test_llm_stream_text_matches_chunks():
    llm = LLMClient()
    chunks = []
    reply = llm.stream_chat([
        {"role": "system", "content": llm.build_system_prompt()},
        {"role": "user", "content": "请用一句话介绍你自己。"},
    ], on_text_chunk=chunks.append)
    assert isinstance(reply, str) and reply.strip()
    assert "".join(chunks) == reply


@pytest.mark.api
def test_llm_returns_focus_tool_call():
    llm = LLMClient()
    reply = llm.stream_chat([
        {"role": "system", "content": llm.build_system_prompt()},
        {"role": "user", "content": "帮我开启25分钟的专注模式。"},
    ], tools=AVAILABLE_TOOLS, tool_choice="auto")
    assert isinstance(reply, dict), "Expected a tool call, not only an acknowledgement"
    import json
    calls = reply["tool_calls"]
    focus = [c for c in calls if c["function"]["name"] == "set_focus_mode"]
    assert len(focus) == 1
    assert json.loads(focus[0]["function"]["arguments"])["duration_minutes"] == 25


@pytest.mark.api
@pytest.mark.parametrize("message, marker", [
    ("老王，今天晚上吃什么？", "[SKIP]"),
    ("好了阿米娅，我要走了，再见。", "[EXIT]"),
])
def test_llm_control_markers(message, marker):
    llm = LLMClient()
    reply = llm.stream_chat([
        {"role": "system", "content": llm.build_system_prompt()},
        {"role": "user", "content": message},
    ])
    assert isinstance(reply, str) and marker in reply
