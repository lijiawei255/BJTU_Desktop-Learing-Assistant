"""记忆管理 — 跨会话持久化、上下文压缩摘要、短期/长期记忆存储"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from src.config import config, PROJECT_ROOT
from src.utils.logger import setup_logger

logger = setup_logger("memory")


class MemoryManager:
    """跨会话记忆管理器 — 持久化 + 上下文压缩 + 记忆摘要"""

    def __init__(self):
        self.data_dir = PROJECT_ROOT / config.get("memory.data_dir", "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.max_today_sessions = config.get("memory.max_today_sessions", 5)
        self.max_context_rounds = config.get("llm.max_context_rounds", 10)
        self.context_token_limit = config.get("llm.context_token_limit", 3000)

        # 加载已有记忆
        self.longterm = self._load_longterm()
        self.today_memory = self._load_today_memory()

        logger.info("MemoryManager initialized")

    # ═══════════════════════════════════════════════════════════
    # 上下文压缩
    # ═══════════════════════════════════════════════════════════

    def should_compress(self, message_count: int) -> bool:
        """检查是否需要压缩上下文（超过最大轮数）"""
        return message_count // 2 > self.max_context_rounds

    def compress_context(self, messages: List[Dict]) -> str:
        """
        压缩上下文：对旧消息生成简短摘要文本。

        Args:
            messages: 需要压缩的旧消息列表（完整消息含 role/content）

        Returns:
            摘要字符串，可注入到 system prompt 中
        """
        if not messages:
            return ""

        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        parts = []
        for m in messages[:6]:
            content = m.get("content", "")
            if isinstance(content, str) and content:
                parts.append(f"{m['role']}: {content[:60]}")
        summary = " | ".join(parts)
        logger.info(f"Context compressed: {len(messages)} msgs → {len(summary)} char summary")
        return f"[历史对话摘要] {summary}"

    def build_compressed_context(
        self, system_prompt: str, messages: List[Dict], memory_summary: str = ""
    ) -> List[Dict]:
        """
        构建带压缩的完整上下文消息列表。

        策略：system prompt + 记忆摘要 + 最近 max_context_rounds 轮对话。
        如果历史消息超出窗口，将旧消息压缩为摘要注入 system prompt。

        Args:
            system_prompt: 系统提示词
            messages: 当前会话的所有消息（role + content）
            memory_summary: 来自长期记忆的摘要（跨会话）

        Returns:
            适合传给 LLM 的消息列表
        """
        max_msgs = self.max_context_rounds * 2  # user + assistant 各算一条

        system_content = system_prompt
        if memory_summary:
            system_content += f"\n\n[跨会话记忆] {memory_summary}"

        # 如果消息在窗口内，直接返回
        if len(messages) <= max_msgs:
            return [{"role": "system", "content": system_content}] + [
                {"role": m["role"], "content": m.get("content", "")}
                for m in messages
            ]

        # 压缩旧消息
        old_messages = messages[:-max_msgs]
        recent_messages = messages[-max_msgs:]
        compressed = self.compress_context(old_messages)
        if compressed:
            system_content += f"\n\n{compressed}"

        result = [{"role": "system", "content": system_content}]
        result.extend([
            {"role": m["role"], "content": m.get("content", "")}
            for m in recent_messages
        ])
        return result

    # ═══════════════════════════════════════════════════════════
    # 会话持久化
    # ═══════════════════════════════════════════════════════════

    def save_session(self, messages: List[Dict], nickname: str = "博士"):
        """
        保存本次会话到今日记忆

        Args:
            messages: 当前会话的完整消息列表
            nickname: 用户称呼
        """
        if not messages:
            return

        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return

        summary = self._generate_session_summary(messages)
        session_record = {
            "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "summary": summary,
            "message_count": len(messages),
            "nickname": nickname,
        }

        self.today_memory.setdefault("recent_sessions", [])
        self.today_memory["recent_sessions"].append(session_record)
        self.today_memory["session_count"] = len(self.today_memory["recent_sessions"])
        self.today_memory["date"] = datetime.now().strftime("%Y-%m-%d")

        # 超过限制时归档最早的一条
        while len(self.today_memory["recent_sessions"]) > self.max_today_sessions:
            oldest = self.today_memory["recent_sessions"].pop(0)
            self._archive_to_longterm(oldest)

        self._save_today_memory()
        logger.info(f"Session saved: {session_record['session_id']} ({len(messages)} msgs)")

    def _generate_session_summary(self, messages: List[Dict]) -> str:
        """生成本次会话的简单摘要（基于用户消息主题）"""
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return "无对话内容"
        topics = " | ".join([m[:40] for m in user_msgs[:3]])
        return f"用户说了: {topics}"

    # ═══════════════════════════════════════════════════════════
    # 记忆摘要（注入 System Prompt）
    # ═══════════════════════════════════════════════════════════

    def get_memory_summary(self) -> str:
        """获取跨会话记忆摘要，用于注入 System Prompt"""
        parts = []

        # 今日会话摘要
        recent = self.today_memory.get("recent_sessions", [])
        if recent:
            last = recent[-1]
            parts.append(f"上次对话: {last.get('summary', '')}")

        # 长期记忆摘要（最近3条）
        summaries = self.longterm.get("conversation_summaries", [])
        if summaries:
            recent_summaries = summaries[-3:]
            for s in recent_summaries:
                parts.append(f"{s.get('date', '')}: {s.get('summary', '')}")

        # 用户偏好
        preferences = self.longterm.get("user_profile", {}).get("preferences", {})
        if preferences:
            pref_str = "; ".join([f"{k}: {v}" for k, v in preferences.items()])
            parts.append(f"用户偏好: {pref_str}")

        return "; ".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════════════
    # 用户称呼
    # ═══════════════════════════════════════════════════════════

    def get_nickname(self) -> str:
        """获取用户称呼（优先 config，回退到长期记忆）"""
        nickname = config.get("system.nickname", "")
        if nickname and nickname != "博士":
            return nickname
        mem_nickname = self.longterm.get("user_profile", {}).get("nickname", "")
        return mem_nickname or "博士"

    def set_nickname(self, nickname: str):
        """设置用户称呼（同时写入 config 和长期记忆）"""
        self.longterm.setdefault("user_profile", {})
        self.longterm["user_profile"]["nickname"] = nickname
        self._save_longterm()

    # ═══════════════════════════════════════════════════════════
    # 用户偏好
    # ═══════════════════════════════════════════════════════════

    def set_preference(self, key: str, value: str):
        """记录用户偏好"""
        self.longterm.setdefault("user_profile", {})
        self.longterm["user_profile"].setdefault("preferences", {})
        self.longterm["user_profile"]["preferences"][key] = value
        self._save_longterm()
        logger.info(f"Preference saved: {key}={value}")

    def get_preference(self, key: str, default=None) -> str:
        """获取用户偏好"""
        return self.longterm.get("user_profile", {}).get("preferences", {}).get(key, default)

    # ═══════════════════════════════════════════════════════════
    # 长期记忆持久化
    # ═══════════════════════════════════════════════════════════

    def _archive_to_longterm(self, session: Dict):
        """归档一条会话到长期记忆"""
        self.longterm.setdefault("conversation_summaries", [])
        self.longterm["conversation_summaries"].append({
            "date": session.get("start_time", "")[:10],
            "summary": session.get("summary", ""),
        })
        # 限制长期摘要数量
        max_summaries = 50
        if len(self.longterm["conversation_summaries"]) > max_summaries:
            self.longterm["conversation_summaries"] = \
                self.longterm["conversation_summaries"][-max_summaries:]
        self._save_longterm()

    def _load_longterm(self) -> Dict:
        """加载长期记忆"""
        path = self.data_dir / "longterm_memory.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load longterm memory: {e}")
        return {
            "version": "1.0",
            "user_profile": {},
            "interaction_memory": {},
            "conversation_summaries": [],
        }

    def _save_longterm(self):
        """保存长期记忆"""
        path = self.data_dir / "longterm_memory.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.longterm, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"Failed to save longterm memory: {e}")

    def _load_today_memory(self) -> Dict:
        """加载今日记忆"""
        path = self.data_dir / "memory_today.json"
        today = datetime.now().strftime("%Y-%m-%d")
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("date") == today:
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load today memory: {e}")
        return {"date": today, "session_count": 0, "recent_sessions": []}

    def _save_today_memory(self):
        """保存今日记忆"""
        path = self.data_dir / "memory_today.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.today_memory, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"Failed to save today memory: {e}")
