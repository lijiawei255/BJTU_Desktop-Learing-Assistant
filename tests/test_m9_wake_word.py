"""M9 测试套件：唤醒词模糊匹配 + 打断检测门控"""

import pytest
from src.wake_word_detector import WakeWordDetector


class TestFuzzyWakeWord:
    """模糊唤醒词匹配测试"""

    def setup_method(self):
        self.wake = WakeWordDetector()

    # ── 精确匹配（回归） ──

    def test_exact_match_amiya(self):
        assert self.wake.check_wake_word_in_text("阿米娅")

    def test_exact_match_amiya_in_sentence(self):
        assert self.wake.check_wake_word_in_text("阿米娅帮我查一下天气")

    def test_exact_match_english(self):
        assert self.wake.check_wake_word_in_text("amiya")

    def test_exact_match_amia(self):
        assert self.wake.check_wake_word_in_text("amia")

    def test_exact_no_match(self):
        assert not self.wake.check_wake_word_in_text("你好世界")

    def test_exact_empty(self):
        assert not self.wake.check_wake_word_in_text("")

    # ── 字符相似度 ──

    def test_char_similarity_same(self):
        assert WakeWordDetector._char_similarity("娅", "娅")

    def test_char_similarity_group_ya(self):
        # 娅/亚/呀/雅/丫/压/鸭 在同一相似组
        assert WakeWordDetector._char_similarity("娅", "亚")
        assert WakeWordDetector._char_similarity("娅", "呀")
        assert WakeWordDetector._char_similarity("亚", "雅")
        assert WakeWordDetector._char_similarity("丫", "鸭")

    def test_char_similarity_group_a(self):
        assert WakeWordDetector._char_similarity("阿", "啊")

    def test_char_similarity_group_mi(self):
        assert WakeWordDetector._char_similarity("米", "咪")
        assert WakeWordDetector._char_similarity("米", "蜜")

    def test_char_similarity_different(self):
        assert not WakeWordDetector._char_similarity("阿", "米")
        assert not WakeWordDetector._char_similarity("娅", "博")

    # ── 模糊序列匹配 ──

    def test_fuzzy_sequence_exact(self):
        score = WakeWordDetector._fuzzy_sequence_match("阿米娅", "阿米娅")
        assert score == 1.0

    def test_fuzzy_sequence_similar_chars(self):
        # "阿米亚" vs "阿米娅" — 仅最后一个字不同但在同一相似组
        score = WakeWordDetector._fuzzy_sequence_match("阿米亚", "阿米娅")
        assert score == 1.0

    def test_fuzzy_sequence_partial_similarity(self):
        # "啊咪娅" vs "阿米娅" — 两个字不同但在相似组
        score = WakeWordDetector._fuzzy_sequence_match("啊咪娅", "阿米娅")
        assert score >= 2.0 / 3.0  # at least 2/3 match

    def test_fuzzy_sequence_no_match(self):
        score = WakeWordDetector._fuzzy_sequence_match("你好世界", "阿米娅")
        assert score < 0.5

    def test_fuzzy_sequence_short_text(self):
        # text shorter than pattern
        score = WakeWordDetector._fuzzy_sequence_match("阿", "阿米娅")
        assert score == 0.0

    # ── 模糊唤醒检测 ──

    def test_fuzzy_detect_amiya_variants(self):
        """常见ASR误识别变体应被模糊匹配捕获"""
        # ASR可能将"阿米娅"误识别为以下变体
        variants = [
            "阿米亚",      # 娅→亚
            "阿米呀",      # 娅→呀
            "阿米雅",      # 娅→雅
            "啊米娅",      # 阿→啊
            "阿咪娅",      # 米→咪
            "阿米丫",      # 娅→丫
        ]
        for v in variants:
            assert self.wake.check_wake_word_in_text(v), f"'{v}' should match"

    def test_fuzzy_detect_in_sentence(self):
        assert self.wake.check_wake_word_in_text("那个阿米亚在吗")

    def test_fuzzy_no_false_positive(self):
        """不应匹配完全无关的文本"""
        assert not self.wake.check_wake_word_in_text("今天天气真好")
        assert not self.wake.check_wake_word_in_text("帮我定个闹钟")

    # ── 前缀匹配（打断门控） ──

    def test_starts_with_wake_word_exact(self):
        assert self.wake.starts_with_wake_word("阿米娅帮我查一下")

    def test_starts_with_wake_word_english(self):
        assert self.wake.starts_with_wake_word("amiya what time is it")

    def test_starts_with_wake_word_variant(self):
        assert self.wake.starts_with_wake_word("阿米亚帮我查一下")

    def test_starts_with_wake_word_fuzzy_prefix(self):
        # "啊咪娅" vs "阿米娅" — 两个字在相似组
        assert self.wake.starts_with_wake_word("啊咪娅帮我查一下")

    def test_starts_with_wake_word_not_at_start(self):
        """唤醒词在中间不应被判定为开头"""
        assert not self.wake.starts_with_wake_word("帮我阿米娅查一下")

    def test_starts_with_wake_word_empty(self):
        assert not self.wake.starts_with_wake_word("")

    def test_starts_with_wake_word_short_text(self):
        """很短但匹配的文本也应识别"""
        assert self.wake.starts_with_wake_word("阿米")

    def test_starts_with_wake_word_no_match(self):
        assert not self.wake.starts_with_wake_word("你好帮我查一下天气")

    # ── 冷却管理 ──

    def test_cooldown_initially_inactive(self):
        assert not self.wake.is_in_cooldown()

    def test_cooldown_active_after_mark(self):
        self.wake.mark_awake()
        assert self.wake.is_in_cooldown()

    # ── 唤醒词列表覆盖 ──

    def test_core_prefixes_not_empty(self):
        assert len(WakeWordDetector.CORE_WAKE_PREFIXES) > 0

    def test_all_wake_words_covered(self):
        """每个 WAKE_WORDS 条目应至少被一个 CORE_WAKE_PREFIXES 近似匹配"""
        for word in WakeWordDetector.WAKE_WORDS:
            # 清理空格变体
            cleaned = word.lower().replace(" ", "")
            if len(cleaned) <= 2:
                continue  # 太短的忽略
            found = False
            for prefix in WakeWordDetector.CORE_WAKE_PREFIXES:
                p = prefix.lower().replace(" ", "")
                score = WakeWordDetector._fuzzy_sequence_match(cleaned, p)
                if score >= 0.6:
                    found = True
                    break
            assert found, f"WAKE_WORD '{word}' not covered by any CORE_WAKE_PREFIXES"


class TestBargeInDetection:
    """打断检测测试"""

    def setup_method(self):
        self.wake = WakeWordDetector()

    def test_barge_in_mock_returns_none(self):
        """Mock模式下打断检测返回None"""
        # 不传audio_handler/vad/asr，因为mock模式不需要
        result = self.wake._mock_check_barge_in()
        assert result is None

    def test_check_barge_in_accepts_params(self):
        """验证 check_barge_in 方法签名正确"""
        import inspect
        sig = inspect.signature(self.wake.check_barge_in)
        params = list(sig.parameters.keys())
        assert "audio_handler" in params
        assert "vad_handler" in params
        assert "asr_client" in params
        assert "timeout_seconds" in params
