"""LLM输出文本清洗 — 移除动作描述、emoji等非语音内容，确保TTS输入纯净"""

import re


class TextSanitizer:
    """清洗LLM输出，确保只保留适合TTS朗读的纯口语文本。"""

    PATTERNS = [
        (r"\*[^*]+\*", ""),  # *动作描述*
        (r"\[[^\]]+\]", ""),  # [心理活动/状态标记]
        (r"（[^）]*[动作表情说明走神微笑点头摇头叹气眨眼][^）]*）", ""),  # （动作/表情描述）
        (r"【[^】]+】", ""),  # 【状态标记】
        (r"\([^)]*(?:action|gesture|sigh|laugh|nod|smile|shake)[^)]*\)", "", re.IGNORECASE),  # (英文动作)
        (r"～+", "~"),  # 波浪线归一化（TTS可读）
        (r"…+", "。"),  # 中文省略号U+2026 → 句号
        (r"\.{3,}", "。"),  # 英文省略号 → 句号
        (r"—+", "，"),  # 破折号U+2014 → 逗号（避免TTS读出符号名）
        (r"#\w+", ""),  # 话题标签
        (r"[\U0001F300-\U0001F9FF]", ""),  # emoji
        (r"\n{2,}", "\n"),  # 多余空行压缩
        (r"^\s*[-–—•·]\s*", "", re.MULTILINE),  # 列表标记
    ]

    @classmethod
    def sanitize(cls, text: str) -> str:
        """清洗文本，返回只适合TTS朗读的纯口语文本。"""
        for pattern, replacement, *flags in cls.PATTERNS:
            flag = flags[0] if flags else 0
            text = re.sub(pattern, replacement, text, flags=flag)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return text.strip()
