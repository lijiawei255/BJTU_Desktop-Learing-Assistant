"""对话管理器 — 多轮对话历史与上下文窗口管理"""

from typing import List, Dict


class DialogManager:
    """维护多轮对话历史，提供带上下文的完整消息列表。"""

    def __init__(self, max_rounds: int = 10):
        self._history: List[Dict[str, str]] = []
        self._max_rounds = max_rounds

    def add_user_message(self, text: str):
        self._history.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        self._history.append({"role": "assistant", "content": text})

    def get_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        """返回含系统提示词和最近N轮历史的完整消息列表。"""
        messages = [{"role": "system", "content": system_prompt}]
        recent = self._history[-(self._max_rounds * 2):]
        messages.extend(recent)
        return messages

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
            self._history.pop(0)

    def reset(self):
        """清空对话历史。"""
        self._history = []

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
