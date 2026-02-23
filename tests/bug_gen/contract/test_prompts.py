"""Tests for swesmith.bug_gen.contract.prompts — prompt construction."""

import textwrap
import pytest

from swesmith.bug_gen.contract.analyze import (
    DependencyContext,
    FunctionInfo,
    extract_functions,
    build_dependency_contexts,
)
from swesmith.bug_gen.contract.prompts import (
    build_messages,
    SYSTEM_PROMPT_CONTRACT,
    SYSTEM_PROMPT_REFACTOR_DRIFT,
)


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

    def test_refactor_drift_uses_refactor_prompt(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        messages = build_messages(contexts[0], strategy="refactor_drift")
        assert messages[0]["content"] == SYSTEM_PROMPT_REFACTOR_DRIFT
        assert "refactor" in messages[1]["content"].lower()

    def test_contract_violation_uses_contract_prompt(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        messages = build_messages(contexts[0], strategy="contract_violation")
        assert messages[0]["content"] == SYSTEM_PROMPT_CONTRACT

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


class TestBuildMultiSiteMessages:
    def test_returns_system_and_user(self):
        import ast
        from swesmith.bug_gen.contract.analyze import (
            FunctionInfo, CrossFileUsage, MultiSiteContext,
        )
        from swesmith.bug_gen.contract.prompts import (
            build_multi_site_messages, SYSTEM_PROMPT_MULTI_SITE,
        )

        target = FunctionInfo(
            name="encode", qualified_name="encode",
            node=ast.parse("def encode(x): return str(x)").body[0],
            line_start=1, line_end=1, source="def encode(x): return str(x)",
        )
        caller = CrossFileUsage(
            file_path="cli.py", function_name="run",
            source="def run():\n    encode(data)", imported_names=["encode"],
        )
        other = CrossFileUsage(
            file_path="api.py", function_name="handle",
            source="def handle():\n    encode(req)", imported_names=["encode"],
        )
        ctx = MultiSiteContext(
            target=target, target_file_path="core.py",
            target_file_source="def encode(x): return str(x)",
            coordinated_caller=caller, other_callers=[other],
            in_file_callees=[], in_file_callers=[],
        )

        messages = build_multi_site_messages(ctx)
        assert len(messages) == 2
        assert messages[0]["content"] == SYSTEM_PROMPT_MULTI_SITE
        user = messages[1]["content"]
        assert "encode" in user
        assert "cli.py" in user
        assert "api.py" in user
        assert "DO NOT rewrite" in user

    def test_contains_coordinated_caller_section(self):
        import ast
        from swesmith.bug_gen.contract.analyze import (
            FunctionInfo, CrossFileUsage, MultiSiteContext,
        )
        from swesmith.bug_gen.contract.prompts import build_multi_site_messages

        target = FunctionInfo(
            name="fn", qualified_name="fn",
            node=ast.parse("def fn(): pass").body[0],
            line_start=1, line_end=1, source="def fn(): pass",
        )
        c1 = CrossFileUsage(file_path="a.py", function_name="a_fn",
                            source="def a_fn(): fn()", imported_names=["fn"])
        c2 = CrossFileUsage(file_path="b.py", function_name="b_fn",
                            source="def b_fn(): fn()", imported_names=["fn"])
        ctx = MultiSiteContext(
            target=target, target_file_path="m.py", target_file_source="",
            coordinated_caller=c1, other_callers=[c2],
            in_file_callees=[], in_file_callers=[],
        )

        messages = build_multi_site_messages(ctx)
        user = messages[1]["content"]
        assert "Coordinated caller" in user
        assert "a.py" in user
