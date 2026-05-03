"""Tests for cost formatting utilities."""

from graybench.llm.cost_tracker import format_cost, format_tokens


class TestFormatCost:
    def test_sub_millicent(self):
        assert format_cost(0.000123) == "$0.000123"

    def test_sub_dollar(self):
        assert format_cost(0.1234) == "$0.1234"

    def test_dollar_plus(self):
        assert format_cost(1.5) == "$1.50"
        assert format_cost(12.345) == "$12.35"

    def test_zero(self):
        assert format_cost(0.0) == "$0.000000"


class TestFormatTokens:
    def test_small(self):
        assert format_tokens(500) == "500"

    def test_thousands(self):
        assert format_tokens(1500) == "1.5K"
        assert format_tokens(10000) == "10.0K"

    def test_millions(self):
        assert format_tokens(1500000) == "1.5M"
        assert format_tokens(2000000) == "2.0M"

    def test_zero(self):
        assert format_tokens(0) == "0"

    def test_boundary(self):
        assert format_tokens(999) == "999"
        assert format_tokens(1000) == "1.0K"
        assert format_tokens(999999) == "1000.0K"
        assert format_tokens(1000000) == "1.0M"
