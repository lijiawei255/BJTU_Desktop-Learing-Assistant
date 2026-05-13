"""Milestone 6 记忆系统与上下文管理测试"""

import json
from pathlib import Path
from unittest.mock import patch

from src.memory_manager import MemoryManager
from src.config import config, PROJECT_ROOT


class TestMemoryManagerInit:
    def test_init_creates_data_dir(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert (tmp_path / "data").exists()
                assert mm.max_today_sessions == 5
                assert mm.max_context_rounds == 10

    def test_init_loads_empty_state(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert mm.longterm["version"] == "1.0"
                assert mm.today_memory["session_count"] == 0
                assert mm.today_memory["recent_sessions"] == []


class TestContextCompression:
    def test_should_compress_below_limit(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                # 10 rounds = 20 messages, so 10 user+assistant pairs
                assert mm.should_compress(10) is False  # 5 rounds
                assert mm.should_compress(20) is False  # 10 rounds = limit
                assert mm.should_compress(22) is True   # 11 rounds > limit

    def test_compress_context_produces_summary(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                messages = [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好博士！"},
                    {"role": "user", "content": "今天天气怎么样"},
                    {"role": "assistant", "content": "抱歉我无法查询天气"},
                ]
                summary = mm.compress_context(messages)
                assert "[历史对话摘要]" in summary
                assert "user:" in summary
                assert "assistant:" in summary

    def test_compress_context_empty(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert mm.compress_context([]) == ""

    def test_build_compressed_context_within_window(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                sp = "你是阿米娅"
                msgs = [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好博士！"},
                ]
                result = mm.build_compressed_context(sp, msgs)
                assert result[0]["role"] == "system"
                assert "你是阿米娅" in result[0]["content"]
                assert len(result) == 3  # system + 2 messages

    def test_build_compressed_context_exceeds_window(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                sp = "你是阿米娅"
                # Create more messages than max_msgs (10 rounds * 2 = 20)
                msgs = []
                for i in range(15):
                    msgs.append({"role": "user", "content": f"问题{i}"})
                    msgs.append({"role": "assistant", "content": f"答案{i}"})
                result = mm.build_compressed_context(sp, msgs)
                assert result[0]["role"] == "system"
                # System content should include compressed summary
                assert "[历史对话摘要]" in result[0]["content"]

    def test_build_compressed_context_with_memory_summary(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                sp = "你是阿米娅"
                msgs = [{"role": "user", "content": "你好"}]
                result = mm.build_compressed_context(
                    sp, msgs, memory_summary="上次对话: 讨论了学习计划"
                )
                assert "[跨会话记忆] 上次对话: 讨论了学习计划" in result[0]["content"]


class TestSessionPersistence:
    def test_save_session_creates_file(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                messages = [
                    {"role": "user", "content": "你好阿米娅"},
                    {"role": "assistant", "content": "博士你好！"},
                ]
                mm.save_session(messages, nickname="博士")
                today_file = tmp_path / "data" / "memory_today.json"
                assert today_file.exists()
                data = json.loads(today_file.read_text(encoding="utf-8"))
                assert data["session_count"] == 1
                assert len(data["recent_sessions"]) == 1
                assert data["recent_sessions"][0]["nickname"] == "博士"

    def test_save_session_empty_messages(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                mm.save_session([], nickname="博士")
                today_file = tmp_path / "data" / "memory_today.json"
                # Should not create file for empty session
                assert not today_file.exists() or mm.today_memory["session_count"] == 0

    def test_save_multiple_sessions_respects_limit(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                for i in range(7):
                    messages = [
                        {"role": "user", "content": f"对话{i}"},
                        {"role": "assistant", "content": f"回复{i}"},
                    ]
                    mm.save_session(messages, nickname="博士")
                assert len(mm.today_memory["recent_sessions"]) <= mm.max_today_sessions
                # Archived to longterm
                assert len(mm.longterm.get("conversation_summaries", [])) >= 1

    def test_session_summary_generation(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                messages = [
                    {"role": "user", "content": "我想学习Python"},
                    {"role": "assistant", "content": "好的博士！"},
                ]
                mm.save_session(messages, nickname="博士")
                summary = mm.today_memory["recent_sessions"][-1]["summary"]
                assert "我想学习Python" in summary


class TestMemorySummary:
    def test_summary_empty_with_no_data(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert mm.get_memory_summary() == ""

    def test_summary_includes_recent_session(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                messages = [
                    {"role": "user", "content": "帮我复习数学"},
                    {"role": "assistant", "content": "好的！"},
                ]
                mm.save_session(messages, nickname="博士")
                summary = mm.get_memory_summary()
                assert "上次对话" in summary
                assert "复习数学" in summary


class TestNicknameManagement:
    def test_get_nickname_default(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert mm.get_nickname() == "博士"

    def test_set_and_get_nickname(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                mm.set_nickname("指挥官")
                assert mm.get_nickname() == "指挥官"
                assert mm.longterm["user_profile"]["nickname"] == "指挥官"

    def test_set_nickname_persists(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                mm.set_nickname("同学")
                # Reload
                mm2 = MemoryManager()
                assert mm2.get_nickname() == "同学"


class TestUserPreferences:
    def test_set_and_get_preference(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                mm.set_preference("favorite_subject", "数学")
                assert mm.get_preference("favorite_subject") == "数学"

    def test_get_preference_default(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                assert mm.get_preference("unknown_key", "默认值") == "默认值"

    def test_preferences_appear_in_summary(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                mm.set_preference("学习风格", "视觉型")
                summary = mm.get_memory_summary()
                assert "用户偏好" in summary
                assert "视觉型" in summary


class TestLongtermMemory:
    def test_longterm_file_created(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                messages = [{"role": "user", "content": "测试"}]
                mm.save_session(messages, nickname="博士")
                # Archive by exceeding limit
                for i in range(6):
                    mm.save_session(
                        [{"role": "user", "content": f"对话{i}"}],
                        nickname="博士"
                    )
                longterm_file = tmp_path / "data" / "longterm_memory.json"
                assert longterm_file.exists()
                data = json.loads(longterm_file.read_text(encoding="utf-8"))
                assert "conversation_summaries" in data

    def test_longterm_summary_limit(self, tmp_path):
        with patch.object(config, "get", side_effect=_fake_config_get):
            with patch("src.memory_manager.PROJECT_ROOT", tmp_path):
                mm = MemoryManager()
                # Add many summaries directly
                for i in range(60):
                    mm._archive_to_longterm({
                        "start_time": f"2026-01-{min(i+1, 28):02d}T10:00:00",
                        "summary": f"摘要{i}",
                    })
                assert len(mm.longterm["conversation_summaries"]) <= 50


def _fake_config_get(key, default=None):
    """模拟配置读取，返回合理的默认值"""
    defaults = {
        "memory.data_dir": "data",
        "memory.max_today_sessions": 5,
        "llm.max_context_rounds": 10,
        "llm.context_token_limit": 3000,
        "system.nickname": "",
    }
    return defaults.get(key, default)
