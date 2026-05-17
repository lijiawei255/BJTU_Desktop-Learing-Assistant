"""阿里云百炼 LLM 客户端 - 支持对话和函数调用"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Callable
import dashscope
from dashscope import Generation

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("llm")


class LLMClient:
    """大模型对话客户端"""

    def __init__(self):
        self.api_key = config.api_key_alibaba
        if not self.api_key:
            logger.error("Alibaba API key not configured!")
            raise ValueError("ALIBABA_API_KEY required")

        dashscope.api_key = self.api_key
        self.model = config.get("llm.model", "qwen3.6-plus")
        self.max_tokens = config.get("llm.max_tokens", 512)
        self.temperature = config.get("llm.temperature", 0.7)
        self.top_p = config.get("llm.top_p", 0.9)

        self.system_prompt_template = self._load_persona()
        logger.info(f"LLMClient initialized: model={self.model}")

    def _load_persona(self) -> str:
        """加载Amiya人格提示词"""
        persona_path = (
            Path(__file__).parent.parent / "system_prompts" / "amiya_persona.txt"
        )
        if persona_path.exists():
            return persona_path.read_text(encoding="utf-8")
        logger.warning("Persona file not found, using default")
        return "你是阿米娅，用户的贴心学习助手。"

    def build_system_prompt(
        self,
        nickname: str = "博士",
        focus_status: str = "未开启",
        memory_summary: str = "",
    ) -> str:
        """构建完整的系统提示词"""
        from datetime import datetime

        prompt = self.system_prompt_template.format(
            nickname=nickname,
            datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        prompt += f"\n\n[当前状态] 专注模式：{focus_status}"
        if memory_summary:
            prompt += f"\n[记忆摘要] {memory_summary}"

        return prompt

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict:
        """
        发送对话请求
        messages: OpenAI格式消息列表 [{"role": "user", "content": "..."}]
        tools: 可选的函数调用声明
        返回: 完整的API响应字典
        """
        try:
            logger.debug(f"Sending chat request with {len(messages)} messages")

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "result_format": "message",
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

            response = Generation.call(**kwargs)

            if response.status_code == 200:
                output = response.output
                logger.debug(f"LLM response: choices={len(output.choices) if output.choices else 0}")
                return {"success": True, "data": output, "raw": response}
            else:
                logger.error(f"LLM API error: {response.status_code} - {response.message}")
                return {"success": False, "error": response.message}

        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            return {"success": False, "error": str(e)}

    def simple_chat(self, user_message: str, system_prompt: str = None) -> str:
        """
        简化的单轮对话，直接返回文本回复
        用于测试和快速调用
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        result = self.chat(messages)
        if result["success"]:
            try:
                return result["data"].choices[0].message.content
            except (KeyError, IndexError, AttributeError):
                return "（助手似乎不知道怎么回答）"
        return f"（请求失败: {result.get('error', 'unknown')}）"

    def stream_chat(
        self,
        messages: list,
        on_text_chunk: Callable[[str], None] = None,
        tools: list = None,
        tool_choice: str = None,
    ):
        """
        流式LLM对话，每个token增量通过 on_text_chunk(delta) 回调实时传出。

        Args:
            messages: OpenAI格式消息列表
            on_text_chunk: 文本增量回调
            tools: 可选的函数调用声明列表
            tool_choice: 工具选择策略 ("auto", "none", 或指定工具)

        Returns:
            如果LLM返回tool_calls: {"text": str, "tool_calls": list}
            否则: str (完整响应文本)
        """
        try:
            logger.debug(
                f"Starting stream chat with {len(messages)} msgs"
                + (f", {len(tools)} tools" if tools else "")
            )

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "result_format": "message",
                "stream": True,
                "incremental_output": True,
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

            response = Generation.call(**kwargs)

            full_text = ""
            tool_calls = []

            def _safe(obj, attr, default=None):
                """安全获取属性或键值（流式模式下tc/fn为原生dict）"""
                try:
                    return getattr(obj, attr)
                except (AttributeError, KeyError):
                    pass
                try:
                    return obj[attr]
                except (TypeError, KeyError, IndexError):
                    return default

            for chunk in response:
                if chunk.status_code == 200:
                    output = chunk.output
                    if output and output.choices:
                        choice = output.choices[0]
                        msg = choice.message
                        # 文本增量
                        delta = _safe(msg, "content", "") or ""
                        if delta:
                            full_text += delta
                            if on_text_chunk:
                                on_text_chunk(delta)
                        # 工具调用增量
                        tc_deltas = _safe(msg, "tool_calls")
                        if tc_deltas:
                            for tc in tc_deltas:
                                idx = _safe(tc, "index", len(tool_calls))
                                while len(tool_calls) <= idx:
                                    tool_calls.append(
                                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                    )
                                tc_id = _safe(tc, "id", "")
                                if tc_id:
                                    tool_calls[idx]["id"] = tc_id
                                fn = _safe(tc, "function")
                                if fn:
                                    fn_name = _safe(fn, "name", "")
                                    if fn_name:
                                        tool_calls[idx]["function"]["name"] = fn_name
                                    tool_calls[idx]["function"]["arguments"] += _safe(fn, "arguments", "") or ""
                else:
                    logger.error(
                        f"LLM stream error: code={chunk.status_code} msg={chunk.message}"
                    )

            logger.debug(f"Stream chat done: {len(full_text)} chars"
                         + (f", {len(tool_calls)} tool_calls" if tool_calls else ""))
            if tool_calls:
                return {"text": full_text, "tool_calls": tool_calls}
            return full_text

        except Exception as e:
            logger.error(f"LLM stream_chat failed: {e}")
            if full_text:
                logger.info(f"Returning partial stream: {len(full_text)} chars")
                return full_text
            return ""


# 工具函数声明（供LLM function calling使用）
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_focus_mode",
            "description": "开启专注模式。用户说'我要学习'、'开始专注'、'我要专注25分钟'、'帮我计时30分钟'等意图时调用。如果当前已有专注模式进行中（可从系统提示中的[当前状态]得知），请先提醒用户结束当前专注模式，不要重复调用此函数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {
                        "type": "integer",
                        "description": "专注时长（分钟）。如用户未明确指定则默认25分钟。",
                        "minimum": 5,
                        "maximum": 120,
                    }
                },
                "required": ["duration_minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_focus_mode",
            "description": "结束当前专注模式。用户说'结束专注'、'停止专注'、'退出专注'、'不再学了'、'今天就到这里'、'可以了'等想结束当前学习时段的意图时调用。注意：这与临时拿手机不同（那应该用open_phone_box temporary），这是彻底结束本次专注。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_phone_box",
            "description": "临时暂停专注并打开手机盒。用户说'暂停一下'、'拿一下手机'、'接个电话'、'临时休息一下'等需要短暂中断的意图时调用。注意：如果用户想彻底结束专注请用end_focus_mode。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "打开原因：temporary（临时拿手机/暂停专注）",
                        "enum": ["temporary"],
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_focus_status",
            "description": "查询当前专注模式状态。用户问'还剩多久'、'还有几分钟'、'专注多久了'、'进度怎么样'时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_user_nickname",
            "description": "设置或修改用户称呼。用户说'叫我XX'、'以后叫我XX'、'我是XX'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "nickname": {
                        "type": "string",
                        "description": "用户对Amiya的称呼，如'博士'、'指挥官'、'同学'等",
                    }
                },
                "required": ["nickname"],
            },
        },
    },
]
