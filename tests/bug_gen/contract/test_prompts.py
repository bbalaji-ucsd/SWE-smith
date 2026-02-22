"""Tests for swesmith.bug_gen.contract.prompts — prompt construction."""

import textwrap
import pytest

from swesmith.bug_gen.contract.analyze import (
    DependencyContext,
    FunctionInfo,
    extract_functions,
    build_dependency_contexts,
)
from swesmith.bug_gen.contract.prompts import build_messages, SYSTEM_PROMPT


SAMPLE_CODE = textwrap.dedent("""\
    def validate(data):
        if not isinstance(data, dict):
            return False
        return "key" in data

    def transform(data):
        if not validate(data):
            raise ValueError("Invalid data")
        return data["key"].upper()

    def pipeline(items):
        results = []
        for item in items:
            results.append(transform(item))
        return results
""")


@pytest.fixture
def sample_file(tmp_path):
    p = tmp_path / "pipeline.py"
    p.write_text(SAMPLE_CODE)
    return str(p)


class TestBuildMessages:
    def test_returns_system_and_user_messages(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        assert len(contexts) > 0
        messages = build_messages(contexts[0])
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_content(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        messages = build_messages(contexts[0])
        assert "contract" in messages[0]["content"].lower()

    def test_user_prompt_contains_target(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        messages = build_messages(contexts[0])
        user_content = messages[1]["content"]
        # Should contain the target function name
        assert contexts[0].target.name in user_content

    def test_user_prompt_contains_callees(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        # Find the context for 'transform' which calls 'validate'
        ctx = next((c for c in contexts if c.target.name == "transform"), None)
        if ctx is None:
            pytest.skip("transform context not found")
        messages = build_messages(ctx)
        user_content = messages[1]["content"]
        assert "validate" in user_content

    def test_user_prompt_contains_file_path(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        messages = build_messages(contexts[0])
        assert sample_file in messages[1]["content"]

    def test_user_prompt_contains_callers_section(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        # Find a context that has callers
        ctx_with_callers = next((c for c in contexts if c.callers), None)
        if ctx_with_callers is None:
            pytest.skip("No context with callers found")
        messages = build_messages(ctx_with_callers)
        assert "Caller" in messages[1]["content"]
