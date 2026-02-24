"""
Static analysis of inter-function dependencies within and across files.

Uses the AST to build a call graph and extract caller/callee relationships,
shared state, and return-value usage patterns — both within a single file
and across the repository via import resolution.
"""

import ast
import os
import textwrap
from dataclasses import dataclass, field
from swesmith.constants import CodeEntity


@dataclass
class FunctionInfo:
    """Metadata about a single function/method extracted from the AST."""

    name: str
    qualified_name: str  # e.g. "ClassName.method_name"
    node: ast.FunctionDef | ast.AsyncFunctionDef
    line_start: int
    line_end: int
    source: str
    calls: set[str] = field(default_factory=set)  # names this function calls
    called_by: set[str] = field(default_factory=set)  # names that call this function
    class_name: str | None = None


@dataclass
class CrossFileUsage:
    """A call site in another file that uses a function from the target's module."""

    file_path: str
    function_name: str  # the function in the other file that makes the call
    source: str  # source of that function
    imported_names: list[str]  # which names from the target module are imported


@dataclass
class DependencyContext:
    """A function together with its dependency context (callers, callees, shared file)."""

    target: FunctionInfo
    callers: list[FunctionInfo]
    callees: list[FunctionInfo]
    file_source: str
    file_path: str
    cross_file_usages: list[CrossFileUsage] = field(default_factory=list)


@dataclass
class MultiSiteContext:
    """Context for multi-site contract violation: a target, one coordinated caller, and remaining callers."""

    target: FunctionInfo
    target_file_path: str
    target_file_source: str
    coordinated_caller: CrossFileUsage  # the caller that will be updated WITH the target
    other_callers: list[CrossFileUsage]  # callers that will NOT be updated (they break)
    in_file_callees: list[FunctionInfo]
    in_file_callers: list[FunctionInfo]


class _CallCollector(ast.NodeVisitor):
    """Collect all function/method call names from an AST subtree."""

    def __init__(self):
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            # Capture both "self.method" → "method" and "obj.method" → "method"
            self.calls.add(node.func.attr)
        self.generic_visit(node)


def _get_source_segment(file_lines: list[str], node: ast.AST) -> str:
    """Extract source code for an AST node using line numbers."""
    start = node.lineno - 1  # 0-indexed
    end = node.end_lineno  # end_lineno is 1-indexed, inclusive
    segment = "".join(file_lines[start:end])
    return textwrap.dedent(segment)


def extract_functions(file_path: str) -> list[FunctionInfo]:
    """Parse a Python file and extract all top-level and class-level functions."""
    with open(file_path, "r") as f:
        source = f.read()
    file_lines = source.splitlines(keepends=True)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    functions: list[FunctionInfo] = []

    # Only iterate over direct children of the module (top-level statements)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    collector = _CallCollector()
                    collector.visit(item)
                    src = _get_source_segment(file_lines, item)
                    functions.append(
                        FunctionInfo(
                            name=item.name,
                            qualified_name=f"{class_name}.{item.name}",
                            node=item,
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            source=src,
                            calls=collector.calls,
                            class_name=class_name,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            collector = _CallCollector()
            collector.visit(node)
            src = _get_source_segment(file_lines, node)
            functions.append(
                FunctionInfo(
                    name=node.name,
                    qualified_name=node.name,
                    node=node,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    source=src,
                    calls=collector.calls,
                )
            )

    # Build reverse call graph (called_by)
    name_to_func = {f.name: f for f in functions}
    for func in functions:
        for callee_name in func.calls:
            if callee_name in name_to_func:
                name_to_func[callee_name].called_by.add(func.name)

    return functions


def build_dependency_contexts(
    file_path: str,
    min_callees: int = 1,
    min_source_lines: int = 2,
    max_source_lines: int = 200,
) -> list[DependencyContext]:
    """
    Build dependency contexts for functions that have meaningful inter-function
    relationships (i.e., they call or are called by other functions in the same file).

    Args:
        file_path: Path to the Python source file.
        min_callees: Minimum number of in-file callees a function must have.
        min_source_lines: Minimum lines of source code for the target function.
        max_source_lines: Maximum lines of source code for the target function.

    Returns:
        List of DependencyContext objects suitable for contract-violation bug generation.
    """
    with open(file_path, "r") as f:
        file_source = f.read()

    functions = extract_functions(file_path)
    if not functions:
        return []

    name_to_func = {f.name: f for f in functions}
    contexts: list[DependencyContext] = []

    for func in functions:
        # Filter: must have enough in-file callees
        in_file_callees = [name_to_func[c] for c in func.calls if c in name_to_func]
        if len(in_file_callees) < min_callees:
            continue

        # Filter: reasonable size
        num_lines = func.line_end - func.line_start + 1
        if num_lines < min_source_lines or num_lines > max_source_lines:
            continue

        # Build caller list
        in_file_callers = [name_to_func[c] for c in func.called_by if c in name_to_func]

        contexts.append(
            DependencyContext(
                target=func,
                callers=in_file_callers,
                callees=in_file_callees,
                file_source=file_source,
                file_path=file_path,
            )
        )

    return contexts


def dependency_context_for_entity(
    entity: CodeEntity,
) -> DependencyContext | None:
    """
    Build a DependencyContext for a specific CodeEntity (from the SWE-smith profile).

    Returns None if the entity has no meaningful in-file dependencies.
    """
    contexts = build_dependency_contexts(entity.file_path, min_callees=1)
    # Match by line range
    for ctx in contexts:
        if ctx.target.line_start == entity.line_start and ctx.target.line_end == entity.line_end:
            return ctx
    # Fallback: match by name
    entity_name = entity.name
    for ctx in contexts:
        if ctx.target.name == entity_name:
            return ctx
    return None


def _file_to_module(file_path: str, repo_root: str) -> str:
    """Convert a file path to a dotted module name relative to repo root."""
    rel = os.path.relpath(file_path, repo_root)
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace(os.sep, ".")


def _resolve_imports(file_path: str) -> dict[str, list[str]]:
    """
    Parse a file and return a map of module_name -> [imported_names].
    Only handles ``from <module> import <names>`` style imports.
    """
    try:
        with open(file_path, "r") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError):
        return {}
    result: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [a.name for a in node.names]
            result.setdefault(node.module, []).extend(names)
    return result


def find_cross_file_usages(
    target_func_name: str,
    target_file: str,
    repo_root: str,
    max_usages: int = 5,
    max_func_lines: int = 80,
) -> list[CrossFileUsage]:
    """
    Find functions in other files that import and call ``target_func_name``
    from the module containing ``target_file``.

    Walks the repo, resolves imports, and checks whether any function body
    references the target name.
    """
    target_module = _file_to_module(target_file, repo_root)
    # Also check parent module (for re-exports via __init__.py)
    parent_module = ".".join(target_module.split(".")[:-1]) if "." in target_module else ""

    usages: list[CrossFileUsage] = []

    for root, _, files in os.walk(repo_root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            other_path = os.path.join(root, fname)
            if os.path.abspath(other_path) == os.path.abspath(target_file):
                continue

            imports = _resolve_imports(other_path)
            # Check if this file imports the target name from the target module
            imported_names: list[str] = []
            for mod, names in imports.items():
                if mod == target_module or mod == parent_module:
                    if target_func_name in names:
                        imported_names = names
                        break
            if not imported_names:
                continue

            # Find functions in this file that reference the target name
            try:
                with open(other_path, "r") as fh:
                    source = fh.read()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            file_lines = source.splitlines(keepends=True)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Check if this function's body references the target name
                collector = _CallCollector()
                collector.visit(node)
                if target_func_name not in collector.calls:
                    continue
                num_lines = (node.end_lineno or node.lineno) - node.lineno + 1
                if num_lines > max_func_lines:
                    continue
                func_source = _get_source_segment(file_lines, node)
                rel_path = os.path.relpath(other_path, repo_root)
                usages.append(
                    CrossFileUsage(
                        file_path=rel_path,
                        function_name=node.name,
                        source=func_source,
                        imported_names=imported_names,
                    )
                )
                if len(usages) >= max_usages:
                    return usages

    return usages


def build_cross_file_contexts(
    repo_root: str,
    min_callees: int = 0,
    min_cross_file_usages: int = 1,
    min_source_lines: int = 3,
    max_source_lines: int = 150,
) -> list[DependencyContext]:
    """
    Build dependency contexts that include cross-file usage information.

    Unlike ``build_dependency_contexts`` (single-file only), this scans the
    entire repo and enriches each context with functions from *other* files
    that import and call the target.

    Args:
        repo_root: Path to the cloned repository root.
        min_callees: Minimum in-file callees (0 = allow functions with only cross-file deps).
        min_cross_file_usages: Minimum cross-file call sites required.
        min_source_lines: Minimum lines for the target function.
        max_source_lines: Maximum lines for the target function.
    """
    contexts: list[DependencyContext] = []

    # Collect all Python source files (excluding tests)
    py_files = []
    for root, dirs, files in os.walk(repo_root):
        # Skip test directories and hidden dirs
        dirs[:] = [d for d in dirs if d not in ("tests", "test", ".git", "__pycache__")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    for file_path in py_files:
        try:
            with open(file_path, "r") as fh:
                file_source = fh.read()
        except (UnicodeDecodeError, OSError):
            continue

        functions = extract_functions(file_path)
        if not functions:
            continue

        name_to_func = {f.name: f for f in functions}

        for func in functions:
            num_lines = func.line_end - func.line_start + 1
            if num_lines < min_source_lines or num_lines > max_source_lines:
                continue

            # Find cross-file usages
            cross_usages = find_cross_file_usages(
                func.name, file_path, repo_root
            )
            if len(cross_usages) < min_cross_file_usages:
                continue

            # Build in-file context too
            in_file_callees = [name_to_func[c] for c in func.calls if c in name_to_func]
            in_file_callers = [name_to_func[c] for c in func.called_by if c in name_to_func]

            contexts.append(
                DependencyContext(
                    target=func,
                    callers=in_file_callers,
                    callees=in_file_callees,
                    file_source=file_source,
                    file_path=file_path,
                    cross_file_usages=cross_usages,
                )
            )

    return contexts


def _is_test_file(file_path: str) -> bool:
    """Check if a file path looks like a test file."""
    parts = file_path.replace("\\", "/").split("/")
    # Check directory components
    for part in parts[:-1]:
        if part in ("tests", "test", "testing"):
            return True
    # Check filename
    fname = parts[-1]
    return fname.startswith("test_") or fname.endswith("_test.py")


def build_multi_site_contexts(
    repo_root: str,
    min_cross_file_usages: int = 2,
    min_source_lines: int = 3,
    max_source_lines: int = 150,
) -> list[MultiSiteContext]:
    """
    Build multi-site contexts: functions with 2+ cross-file callers.

    For each candidate, one caller is chosen as the "coordinated" caller
    (will be rewritten alongside the target), and the rest become "other"
    callers (will break because they weren't updated).

    IMPORTANT: The coordinated caller must NOT be in a test file, because
    the eval harness restores test files after applying the gold patch.
    If the coordinated caller is a test file, the gold patch reversal would
    be undone for that file, causing P2P test failures.

    Requires at least ``min_cross_file_usages`` cross-file callers so that
    at least one caller is left un-updated.
    """
    contexts: list[MultiSiteContext] = []

    py_files = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in ("tests", "test", ".git", "__pycache__")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    for file_path in py_files:
        try:
            with open(file_path, "r") as fh:
                file_source = fh.read()
        except (UnicodeDecodeError, OSError):
            continue

        functions = extract_functions(file_path)
        if not functions:
            continue

        name_to_func = {f.name: f for f in functions}

        for func in functions:
            num_lines = func.line_end - func.line_start + 1
            if num_lines < min_source_lines or num_lines > max_source_lines:
                continue

            cross_usages = find_cross_file_usages(
                func.name, file_path, repo_root, max_usages=10
            )
            if len(cross_usages) < min_cross_file_usages:
                continue

            # Separate source callers from test callers.
            # The coordinated caller must be a source file (not a test file)
            # because the eval harness restores test files after gold patch.
            source_callers = [u for u in cross_usages if not _is_test_file(u.file_path)]
            test_callers = [u for u in cross_usages if _is_test_file(u.file_path)]

            if not source_callers:
                # No non-test callers available for coordinated update
                continue

            # Need at least 1 other caller (test or source) that will break
            remaining = source_callers[1:] + test_callers
            if not remaining:
                continue

            in_file_callees = [name_to_func[c] for c in func.calls if c in name_to_func]
            in_file_callers = [name_to_func[c] for c in func.called_by if c in name_to_func]

            coordinated = source_callers[0]
            others = remaining

            contexts.append(
                MultiSiteContext(
                    target=func,
                    target_file_path=file_path,
                    target_file_source=file_source,
                    coordinated_caller=coordinated,
                    other_callers=others,
                    in_file_callees=in_file_callees,
                    in_file_callers=in_file_callers,
                )
            )

    return contexts

