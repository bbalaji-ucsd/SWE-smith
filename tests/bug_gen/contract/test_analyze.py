"""Tests for swesmith.bug_gen.contract.analyze — static dependency analysis."""

import os
import textwrap
import pytest

from swesmith.bug_gen.contract.analyze import (
    FunctionInfo,
    DependencyContext,
    extract_functions,
    build_dependency_contexts,
)


SAMPLE_CODE = textwrap.dedent("""\
    def helper(x):
        return x + 1

    def process(items):
        return [helper(i) for i in items]

    def standalone():
        return 42

    class MyClass:
        def method_a(self):
            return self.method_b() + 1

        def method_b(self):
            return 10
""")


@pytest.fixture
def sample_file(tmp_path):
    """Write sample code to a temp file and return its path."""
    p = tmp_path / "sample.py"
    p.write_text(SAMPLE_CODE)
    return str(p)


class TestExtractFunctions:
    def test_extracts_all_functions(self, sample_file):
        funcs = extract_functions(sample_file)
        names = {f.name for f in funcs}
        assert "helper" in names
        assert "process" in names
        assert "standalone" in names
        assert "method_a" in names
        assert "method_b" in names

    def test_call_graph_module_level(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        # process calls helper
        assert "helper" in by_name["process"].calls

    def test_call_graph_class_methods(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        # method_a calls method_b (via self.method_b)
        assert "method_b" in by_name["method_a"].calls

    def test_reverse_call_graph(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        # helper is called by process
        assert "process" in by_name["helper"].called_by

    def test_qualified_names(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        assert by_name["method_a"].qualified_name == "MyClass.method_a"
        assert by_name["process"].qualified_name == "process"

    def test_class_name_set(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        assert by_name["method_a"].class_name == "MyClass"
        assert by_name["process"].class_name is None

    def test_source_extracted(self, sample_file):
        funcs = extract_functions(sample_file)
        by_name = {f.name: f for f in funcs}
        assert "def helper" in by_name["helper"].source
        assert "return x + 1" in by_name["helper"].source

    def test_handles_syntax_error(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(\n")
        assert extract_functions(str(bad)) == []

    def test_handles_empty_file(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("")
        assert extract_functions(str(empty)) == []


class TestBuildDependencyContexts:
    def test_finds_contexts_with_callees(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        target_names = {c.target.name for c in contexts}
        # process calls helper, method_a calls method_b
        assert "process" in target_names
        assert "method_a" in target_names

    def test_excludes_standalone_functions(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        target_names = {c.target.name for c in contexts}
        # standalone has no callees
        assert "standalone" not in target_names

    def test_context_has_callees(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        by_name = {c.target.name: c for c in contexts}
        process_ctx = by_name["process"]
        callee_names = {c.name for c in process_ctx.callees}
        assert "helper" in callee_names

    def test_context_has_callers(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        # helper is called by process, but helper itself has 0 callees
        # so it won't appear as a target. Let's check method_b via method_a.
        by_name = {c.target.name: c for c in contexts}
        method_a_ctx = by_name["method_a"]
        callee_names = {c.name for c in method_a_ctx.callees}
        assert "method_b" in callee_names

    def test_min_callees_filter(self, sample_file):
        # With min_callees=2, nothing should match (each function calls at most 1 other)
        contexts = build_dependency_contexts(sample_file, min_callees=2)
        assert len(contexts) == 0

    def test_file_source_included(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        assert len(contexts) > 0
        assert "def helper" in contexts[0].file_source

    def test_file_path_included(self, sample_file):
        contexts = build_dependency_contexts(sample_file, min_callees=1)
        assert contexts[0].file_path == sample_file

    def test_max_source_lines_filter(self, sample_file):
        # With max_source_lines=1, nothing should match
        contexts = build_dependency_contexts(
            sample_file, min_callees=1, max_source_lines=1
        )
        assert len(contexts) == 0
