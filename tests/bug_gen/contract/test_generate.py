"""Tests for swesmith.bug_gen.contract.generate — generation logic."""

import textwrap
import pytest
from unittest.mock import patch, MagicMock

from swesmith.bug_gen.contract.analyze import (
    DependencyContext,
    FunctionInfo,
    build_dependency_contexts,
)
from swesmith.bug_gen.contract.generate import (
    gen_contract_violation,
    _find_matching_entity,
    STRATEGY_NAME,
)
from swesmith.constants import BugRewrite, CodeEntity


SAMPLE_CODE = textwrap.dedent("""\
    def helper(x):
        return x + 1

    def process(items):
        return [helper(i) for i in items]
""")


@pytest.fixture
def sample_file(tmp_path):
    p = tmp_path / "mod.py"
    p.write_text(SAMPLE_CODE)
    return str(p)


@pytest.fixture
def sample_context(sample_file):
    contexts = build_dependency_contexts(sample_file, min_callees=1)
    assert len(contexts) > 0
    return contexts[0]


class TestFindMatchingEntity:
    def test_matches_by_line_range(self, sample_context):
        entity = MagicMock(spec=CodeEntity)
        entity.file_path = sample_context.file_path
        entity.line_start = sample_context.target.line_start
        entity.line_end = sample_context.target.line_end
        entity.name = "something_else"

        result = _find_matching_entity([entity], sample_context)
        assert result is entity

    def test_matches_by_name_fallback(self, sample_context):
        entity = MagicMock(spec=CodeEntity)
        entity.file_path = sample_context.file_path
        entity.line_start = 999  # wrong line
        entity.line_end = 999
        entity.name = sample_context.target.name

        result = _find_matching_entity([entity], sample_context)
        assert result is entity

    def test_returns_none_when_no_match(self, sample_context):
        entity = MagicMock(spec=CodeEntity)
        entity.file_path = "/other/file.py"
        entity.line_start = 999
        entity.line_end = 999
        entity.name = "unrelated"

        result = _find_matching_entity([entity], sample_context)
        assert result is None


class TestGenContractViolation:
    def test_returns_bug_rewrites(self, sample_context):
        """Test that gen_contract_violation returns BugRewrite objects when LLM succeeds."""
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Explanation:\nChanged return value semantics.\n\n"
            "Bugged Code:\n```python\ndef process(items):\n    return [helper(i) - 1 for i in items]\n```"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.001),
        ):
            bugs = gen_contract_violation(sample_context, "test-model", n_bugs=1)

        assert len(bugs) == 1
        assert isinstance(bugs[0], BugRewrite)
        assert bugs[0].strategy == STRATEGY_NAME
        assert bugs[0].cost > 0

    def test_handles_llm_failure(self, sample_context):
        """Test graceful handling of LLM API errors."""
        with patch(
            "swesmith.bug_gen.contract.generate.completion",
            side_effect=Exception("API error"),
        ):
            bugs = gen_contract_violation(sample_context, "test-model")
        assert bugs == []

    def test_handles_empty_code_block(self, sample_context):
        """Test handling when LLM returns no code block."""
        mock_choice = MagicMock()
        mock_choice.message.content = "I can't do that."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.0),
        ):
            bugs = gen_contract_violation(sample_context, "test-model")
        assert bugs == []

    def test_multiple_bugs(self, sample_context):
        """Test generating multiple bugs per function."""
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Explanation:\nBug.\n\n```python\ndef process(items):\n    return []\n```"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.001),
        ):
            bugs = gen_contract_violation(sample_context, "test-model", n_bugs=2)
        assert len(bugs) == 2
