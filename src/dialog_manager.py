"""对话管理器 — 多轮对话历史与上下文窗口管理（集成 MemoryManager）"""

from typing import List, Dict, Optional
from src.utils.logger import setup_logger

logger = setup_logger("dialog")


class DialogManager:
    """维护多轮对话历史，提供带上下文的完整消息列表。

    支持可选的 MemoryManager 集成，用于上下文自动压缩和跨会话记忆。
    """

    def __init__(self, max_rounds: int = 10, memory_manager=None):
        self._history: List[Dict[str, str]] = []
        self._max_rounds = max_rounds
        self._memory = memory_manager  # Optional[MemoryManager]
        self._compression_summary: str = ""  # 压缩后的旧对话摘要

    def add_user_message(self, text: str):
        self._history.append({"role": "user", "content": text})
        self._maybe_compress()

    def add_assistant_message(self, text: str):
        self._history.append({"role": "assistant", "content": text})

    def get_messages(self, system_prompt: str, memory_summary: str = "") -> List[Dict[str, str]]:
        """返回含系统提示词和最近N轮历史的完整消息列表。

        Args:
            system_prompt: 系统提示词
            memory_summary: 跨会话记忆摘要（由 MemoryManager 提供）
        """
        # 如果有 MemoryManager，委托给它做压缩上下文构建
        if self._memory:
            return self._memory.build_compressed_context(
                system_prompt=system_prompt,
                messages=self._history,
                memory_summary=memory_summary,
            )

        # 否则使用简单滑动窗口
        system_content = system_prompt
        if memory_summary:
            system_content += f"\n\n[跨会话记忆] {memory_summary}"
        if self._compression_summary:
            system_content += f"\n\n{self._compression_summary}"

        messages = [{"role": "system", "content": system_content}]
        recent = self._history[-(self._max_rounds * 2):]
        messages.extend(recent)
        return messages

    def get_history(self) -> List[Dict[str, str]]:
        """返回当前完整对话历史（供 MemoryManager 保存会话）"""
        return list(self._history)

    def remove_last_user_message(self):
        """移除最近一条用户消息（用于过滤非对话内容）。"""
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i]["role"] == "user":
                self._history.pop(i)
                return

    def add_tool_interaction(self, assistant_text: str, tool_calls: list, tool_results: list):
        """将LLM工具调用和结果注入对话历史"""
        assistant_msg = {
            "role": "assistant",
            "content": assistant_text,
            "tool_calls": tool_calls,
        }
        self._history.append(assistant_msg)
        for tc, tr in zip(tool_calls, tool_results):
            self._history.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": tr["result"] if isinstance(tr, dict) else str(tr),
            })
        # 修剪以保持在窗口内
        limit = (self._max_rounds * 2) + 4
        while len(self._history) > limit:
            # 压缩被裁剪的消息
            self._compression_summary = self._summarize_messages(self._history[:1])
            self._history.pop(0)

    def reset(self):
        """清空对话历史（保留压缩摘要供下次使用）。"""
        self._history = []
        self._compression_summary = ""

    def last_user_message(self) -> str:
        """返回最近一条用户消息，无则返回空。"""
        for msg in reversed(self._history):
            if msg["role"] == "user":
                return msg["content"]
        return ""

    @property
    def round_count(self) -> int:
        """当前已存储的对话轮数（一问一答为1轮）。"""
        return len(self._history) // 2

    # ── 内部 ──────────────────────────────────────────────────

    def _maybe_compress(self):
        """检查是否需要压缩上下文（当超出最大轮数时）"""
        limit = self._max_rounds * 2
        if len(self._history) > limit:
            excess = len(self._history) - limit + 2  # 多保留2条缓冲
            old = self._history[:excess]
            self._history = self._history[excess:]
            summary = self._summarize_messages(old)
            if summary:
                self._compression_summary = summary
                logger.info(f"Context compressed: {len(old)} msgs → summary")

    @staticmethod
    def _summarize_messages(messages: List[Dict]) -> str:
        """将消息列表压缩为简短摘要文本"""
        if not messages:
            return ""
        parts = []
        for m in messages[:6]:
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                parts.append(f"{m['role']}: {content[:50]}")
        if parts:
            return f"[历史对话摘要] {' | '.join(parts)}"
        return ""
