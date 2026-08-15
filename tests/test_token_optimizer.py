"""Tests for TokenOptimizer (Wave D — coverage 85% plan)."""
import pytest

from vibe_trading.agents.token_optimizer import (
    PromptTemplateManager,
    TokenOptimizer,
    TokenUsageStats,
)


class TestTokenUsageStats:
    def test_update(self):
        s = TokenUsageStats()
        s.update(1000, 500, {"input": 1.0, "output": 2.0})
        assert s.total_input_tokens == 1000
        assert s.total_output_tokens == 500
        assert s.total_tokens == 1500
        assert s.request_count == 1
        assert s.input_cost_usd == pytest.approx(0.001)
        assert s.total_cost_usd == pytest.approx(0.002)
        assert s.avg_input_per_request == 1000.0

    def test_update_multiple(self):
        s = TokenUsageStats()
        s.update(1000, 500, {"input": 0.5, "output": 1.5})
        s.update(2000, 1000, {"input": 0.5, "output": 1.5})
        assert s.request_count == 2
        assert s.avg_input_per_request == 1500.0
        assert s.avg_output_per_request == 750.0


class TestTokenOptimizer:
    def test_compress_prompt(self):
        t = TokenOptimizer()
        prompt = "指令: 分析\n\n\n\n  很多   空白\n\n\n\n重複格式"
        compressed = t.compress_prompt(prompt)
        assert len(compressed) <= len(prompt)
        assert "compression_ratios" in t.get_stats()

    def test_compress_lists(self):
        t = TokenOptimizer()
        text = "1. - item1\n2. - item2\n3. - item3\n後續"
        compressed = t._compress_lists(text)
        assert "item1" in compressed
        assert compressed.count("item") == 3

    def test_compress_repeated_structures(self):
        t = TokenOptimizer()
        text = "line1\n============\nline2\n============\nline3"
        compressed = t._compress_repeated_structures(text)
        assert compressed.count("====") >= 1

    def test_summarize_history_empty(self):
        t = TokenOptimizer()
        assert t.summarize_history([]) == ""

    def test_summarize_history_messages(self):
        t = TokenOptimizer()
        messages = [
            {"role": "user", "content": "看漲", "timestamp": "1"},
            {"role": "assistant", "content": "同意", "timestamp": "2"},
        ]
        summary = t.summarize_history(messages)
        assert "user" in summary
        assert "assistant" in summary

    def test_summarize_history_truncates(self):
        t = TokenOptimizer()
        messages = [{"role": "user", "content": "x" * 5000, "timestamp": "1"}]
        summary = t.summarize_history(messages)
        assert "[truncated]" in summary

    def test_optimize_system_prompt(self):
        t = TokenOptimizer()
        prompt = "你是分析師\n你是分析師\n分析市場\n分析市場"
        optimized = t.optimize_system_prompt(prompt, agent_role="technical")
        # 重複行被移除
        assert optimized.count("你是分析師") == 1

    def test_generic_prompt_optimization(self):
        t = TokenOptimizer()
        prompt = "line1\nline1\nline2\nline2"
        optimized = t._generic_prompt_optimization(prompt)
        assert optimized.count("line1") == 1

    def test_estimate_tokens(self):
        t = TokenOptimizer()
        # 中文 ≈ 2字/token, 英文 ≈ 4字/token
        assert t.estimate_tokens("abc") == 0  # 3/4 = 0
        assert t.estimate_tokens("abcd") == 1
        assert t.estimate_tokens("你好") == 1  # 2 中文 / 2

    def test_track_usage(self):
        t = TokenOptimizer()
        t.track_usage("analyst", "input text here", "output text")
        stats = t.get_stats()
        assert stats["request_count"] == 1
        assert stats["total_input_tokens"] > 0

    def test_optimization_suggestions_empty(self):
        t = TokenOptimizer()
        suggestions = t.get_optimization_suggestions()
        assert "效率良好" in suggestions[0]

    def test_optimization_suggestions_high_input(self):
        t = TokenOptimizer()
        t.stats.update(100000, 100, {"input": 0.5, "output": 1.5})
        suggestions = t.get_optimization_suggestions()
        assert any("平均输入" in s for s in suggestions)

    def test_optimization_suggestions_high_cost(self):
        t = TokenOptimizer()
        t.stats.update(10000000, 10000000, {"input": 0.5, "output": 1.5})
        suggestions = t.get_optimization_suggestions()
        assert any("成本" in s for s in suggestions)


class TestPromptTemplateManager:
    def test_register_get(self):
        m = PromptTemplateManager()
        m.register_template("tech", "你是技術分析師")
        assert m.get_template("tech") == "你是技術分析師"
        assert m.get_template("missing") is None

    def test_render_template(self):
        m = PromptTemplateManager()
        m.register_template("greet", "你好 {user}")
        assert m.render_template("greet", user="世界") == "你好 世界"
