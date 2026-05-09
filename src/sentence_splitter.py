"""流式LLM句子分割器 — 积累token流，按句子边界分割并回调"""

from typing import Callable


class SentenceSplitter:
    """积累流式LLM token，检测句子边界时回调。"""

    SENTENCE_ENDINGS = {"。", "！", "？", ".", "!", "?", "\n", "；", ";"}

    def __init__(self, callback: Callable[[str], None], min_sentence_len: int = 2):
        self._buffer = ""
        self._callback = callback
        self._min_len = min_sentence_len

    def feed(self, chunk: str) -> None:
        """喂入增量文本chunk，检测到完整句子时触发回调。"""
        if not chunk:
            return
        self._buffer += chunk
        # 循环处理：从左侧找第一个句子边界，切出并回调
        while True:
            first_idx = -1
            for i, ch in enumerate(self._buffer):
                if ch in self.SENTENCE_ENDINGS:
                    first_idx = i
                    break
            if first_idx >= self._min_len:
                sentence = self._buffer[: first_idx + 1].strip()
                self._buffer = self._buffer[first_idx + 1 :]
                if sentence:
                    self._callback(sentence)
            else:
                break

    def flush(self) -> str:
        """返回buffer中剩余未完成的文本。"""
        remainder = self._buffer.strip()
        self._buffer = ""
        return remainder
