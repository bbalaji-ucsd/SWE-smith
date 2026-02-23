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


class TestIsTestFile:
    def test_test_directory(self):
        from swesmith.bug_gen.contract.analyze import _is_test_file
        assert _is_test_file("tests/test_foo.py") is True
        assert _is_test_file("test/test_bar.py") is True

    def test_test_filename(self):
        from swesmith.bug_gen.contract.analyze import _is_test_file
        assert _is_test_file("src/test_utils.py") is True
        assert _is_test_file("pkg/foo_test.py") is True

    def test_source_file(self):
        from swesmith.bug_gen.contract.analyze import _is_test_file
        assert _is_test_file("src/utils.py") is False
        assert _is_test_file("mypkg/core.py") is False
        assert _is_test_file("mypkg/cli.py") is False


class TestBuildMultiSiteContexts:
    def test_finds_multi_site_candidates(self, tmp_path):
        """Test that build_multi_site_contexts finds functions with 2+ cross-file callers."""
        from swesmith.bug_gen.contract.analyze import build_multi_site_contexts

        # Create a mini repo with a target and two callers in different files
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        (pkg / "core.py").write_text(textwrap.dedent("""\
            def encode(data):
                result = str(data)
                return result
        """))

        (pkg / "cli.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def run_cli():
                return encode({"key": "value"})
        """))

        (pkg / "api.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def handle_request():
                return encode([1, 2, 3])
        """))

        contexts = build_multi_site_contexts(str(tmp_path), min_cross_file_usages=2)
        assert len(contexts) >= 1
        ctx = contexts[0]
        assert ctx.target.name == "encode"
        assert ctx.coordinated_caller is not None
        assert len(ctx.other_callers) >= 1

    def test_skips_functions_with_too_few_callers(self, tmp_path):
        """Functions with only 1 cross-file caller should be skipped."""
        from swesmith.bug_gen.contract.analyze import build_multi_site_contexts

        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("def encode(data):\n    return str(data)\n")
        (pkg / "cli.py").write_text("from mypkg.core import encode\n\ndef run():\n    encode(1)\n")

        contexts = build_multi_site_contexts(str(tmp_path), min_cross_file_usages=2)
        assert len(contexts) == 0

    def test_excludes_test_files_as_coordinated_caller(self, tmp_path):
        """Coordinated caller must NOT be a test file (eval harness restores test files)."""
        from swesmith.bug_gen.contract.analyze import build_multi_site_contexts

        # Create a repo where the only cross-file callers are test files
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text(textwrap.dedent("""\
            def encode(data):
                result = str(data)
                return result
        """))

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_core.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def test_encode_str():
                assert encode("hello") == "hello"
        """))
        (tests_dir / "test_core2.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def test_encode_int():
                assert encode(42) == "42"
        """))

        # Both callers are test files → no valid coordinated caller → no contexts
        contexts = build_multi_site_contexts(str(tmp_path), min_cross_file_usages=2)
        assert len(contexts) == 0

    def test_prefers_source_file_as_coordinated_caller(self, tmp_path):
        """When both source and test callers exist, source file should be coordinated."""
        from swesmith.bug_gen.contract.analyze import build_multi_site_contexts, _is_test_file

        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text(textwrap.dedent("""\
            def encode(data):
                result = str(data)
                return result
        """))
        (pkg / "cli.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def run_cli():
                return encode({"key": "value"})
        """))

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_core.py").write_text(textwrap.dedent("""\
            from mypkg.core import encode

            def test_encode():
                assert encode("x") == "x"
        """))

        contexts = build_multi_site_contexts(str(tmp_path), min_cross_file_usages=2)
        assert len(contexts) >= 1
        ctx = contexts[0]
        # Coordinated caller should be the source file, not the test file
        assert not _is_test_file(ctx.coordinated_caller.file_path)
