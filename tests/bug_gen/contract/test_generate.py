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
    VALID_STRATEGIES,
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
        assert bugs[0].strategy == "contract_violation"
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


class TestRefactorDriftStrategy:
    def test_refactor_drift_sets_strategy_name(self, sample_context):
        """Test that refactor_drift strategy produces BugRewrite with correct strategy."""
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Refactoring rationale:\nSimplified list comprehension.\n\n"
            "Refactored Code:\n```python\ndef process(items):\n    return list(map(helper, items))\n```"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.001),
        ):
            bugs = gen_contract_violation(
                sample_context, "test-model", n_bugs=1, strategy="refactor_drift"
            )

        assert len(bugs) == 1
        assert bugs[0].strategy == "refactor_drift"

    def test_refactor_drift_extracts_rationale(self, sample_context):
        """Test that refactoring rationale is extracted as explanation."""
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Refactoring rationale:\nUsed map() for clarity.\n\n"
            "Refactored Code:\n```python\ndef process(items):\n    return list(map(helper, items))\n```"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.001),
        ):
            bugs = gen_contract_violation(
                sample_context, "test-model", n_bugs=1, strategy="refactor_drift"
            )

        assert "map()" in bugs[0].explanation

    def test_valid_strategies_contains_both(self):
        assert "contract_violation" in VALID_STRATEGIES
        assert "refactor_drift" in VALID_STRATEGIES


class TestMultiSiteGeneration:
    def test_extract_two_code_blocks(self):
        from swesmith.bug_gen.contract.generate import _extract_two_code_blocks

        content = (
            "Explanation:\nChanged return type.\n\n"
            "Target function:\n```python\ndef foo():\n    return []\n```\n\n"
            "Coordinated caller:\n```python\ndef bar():\n    return foo()\n```"
        )
        target, caller = _extract_two_code_blocks(content)
        assert target is not None
        assert caller is not None
        assert "def foo" in target
        assert "def bar" in caller

    def test_extract_two_code_blocks_missing(self):
        from swesmith.bug_gen.contract.generate import _extract_two_code_blocks

        content = "No code blocks here."
        target, caller = _extract_two_code_blocks(content)
        assert target is None
        assert caller is None

    def test_extract_two_code_blocks_only_one(self):
        from swesmith.bug_gen.contract.generate import _extract_two_code_blocks

        content = "Only one:\n```python\ndef foo():\n    pass\n```"
        target, caller = _extract_two_code_blocks(content)
        assert target is None
        assert caller is None

    def test_gen_multi_site_returns_pairs(self):
        from swesmith.bug_gen.contract.analyze import MultiSiteContext, FunctionInfo, CrossFileUsage
        from swesmith.bug_gen.contract.generate import gen_multi_site_violation
        import ast

        target = FunctionInfo(
            name="target_fn", qualified_name="target_fn",
            node=ast.parse("def target_fn(): pass").body[0],
            line_start=1, line_end=1, source="def target_fn(): pass",
        )
        caller = CrossFileUsage(
            file_path="other.py", function_name="caller_fn",
            source="def caller_fn(): target_fn()", imported_names=["target_fn"],
        )
        other = CrossFileUsage(
            file_path="third.py", function_name="other_fn",
            source="def other_fn(): target_fn()", imported_names=["target_fn"],
        )
        ctx = MultiSiteContext(
            target=target, target_file_path="mod.py", target_file_source="def target_fn(): pass",
            coordinated_caller=caller, other_callers=[other],
            in_file_callees=[], in_file_callers=[],
        )

        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Explanation:\nChanged return.\n\n"
            "Target function:\n```python\ndef target_fn():\n    return None\n```\n\n"
            "Coordinated caller:\n```python\ndef caller_fn():\n    r = target_fn()\n    if r is None: return\n```"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with (
            patch("swesmith.bug_gen.contract.generate.completion", return_value=mock_response),
            patch("swesmith.bug_gen.contract.generate.completion_cost", return_value=0.002),
        ):
            pairs = gen_multi_site_violation(ctx, "test-model", "/tmp", n_bugs=1)

        assert len(pairs) == 1
        target_bug, caller_bug = pairs[0]
        assert target_bug.strategy == "multi_site"
        assert caller_bug.strategy == "multi_site"
        assert "def target_fn" in target_bug.rewrite
        assert "def caller_fn" in caller_bug.rewrite
