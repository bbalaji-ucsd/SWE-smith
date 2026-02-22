"""
Prompt templates for contract-violation bug generation.

The key insight: instead of asking the LLM to mutate a function in isolation,
we show it the function *and* its callers/callees, then ask it to introduce a
bug that violates the implicit contract between them.
"""

from swesmith.bug_gen.contract.analyze import CrossFileUsage, DependencyContext


SYSTEM_PROMPT = """\
You are an expert software tester specializing in contract-based testing and \
inter-function dependency analysis.

Your task: given a target function and the other functions it interacts with \
(callers and callees in the same file), rewrite the target function to introduce \
a subtle bug that violates the implicit contract between the target and its \
dependencies.

"Contract violations" are bugs where a function still runs without crashing, \
but silently breaks an assumption that another function depends on. Examples:

- Returning a value that is technically valid but semantically wrong for callers \
  (e.g., returning an empty list instead of None to signal "not found").
- Changing the order of side effects that a caller depends on.
- Altering how edge cases are handled in a way that propagates incorrect state.
- Modifying an internal data structure that a callee reads from.
- Subtly changing a precondition check so it accepts/rejects different inputs.
- Returning a shallow copy where a deep copy was expected (or vice versa).
- Off-by-one in a boundary that a caller uses for slicing or iteration.

Rules:
- The bug MUST NOT cause a syntax error or import error.
- The bug MUST NOT change the function signature (name, parameters, return type hint).
- The bug SHOULD be subtle — it should look like a plausible implementation.
- The bug SHOULD cause at least one existing test to fail.
- Do NOT add comments that reveal the bug.
- Output ONLY the rewritten target function (not the whole file).

IMPORTANT — maximize the chance of breaking tests:
- Target the PRIMARY code path, not obscure edge cases. Most test suites \
  exercise the happy path thoroughly.
- Prefer bugs that corrupt a return value or mutate shared state incorrectly — \
  these are almost always tested.
- Avoid changes that might be no-ops (e.g., wrapping a list in list(), \
  deduplicating items that are already unique, reordering items that may be \
  order-independent).
- If the function builds and returns a data structure, alter a key field in \
  that structure — callers almost certainly assert on it.
- If the function has a clear "contract" with callers (e.g., "returns sorted", \
  "resets state after use", "filters out invalid items"), violate THAT contract.

Format your response as:

Explanation:
<brief explanation of what contract is violated and why it's hard to detect>

Bugged Code:
```
<rewritten target function>
```"""


def _format_function_block(label: str, name: str, source: str) -> str:
    """Format a function source block with a label."""
    return f"### {label}: `{name}`\n```python\n{source}\n```"


def build_messages(ctx: DependencyContext) -> list[dict[str, str]]:
    """
    Build the LLM message list for a contract-violation generation request.
    """
    # Build the user prompt with dependency context
    parts = [
        f"**File:** `{ctx.file_path}`\n",
        "## Target function to rewrite with a contract-violating bug:\n",
        _format_function_block("Target", ctx.target.qualified_name, ctx.target.source),
    ]

    if ctx.callees:
        parts.append("\n## Functions called BY the target (callees, same file):\n")
        for callee in ctx.callees[:5]:  # Cap to avoid context overflow
            parts.append(
                _format_function_block("Callee", callee.qualified_name, callee.source)
            )

    if ctx.callers:
        parts.append("\n## Functions that CALL the target (callers, same file):\n")
        for caller in ctx.callers[:5]:
            parts.append(
                _format_function_block("Caller", caller.qualified_name, caller.source)
            )

    if ctx.cross_file_usages:
        parts.append(
            "\n## Cross-file usage — functions in OTHER files that import and call the target:\n"
        )
        for usage in ctx.cross_file_usages[:5]:
            parts.append(
                f"### From `{usage.file_path}` (imports: {', '.join(usage.imported_names)}):\n"
                f"```python\n{usage.source}\n```"
            )

    parts.append(
        "\n---\n"
        "Now rewrite the **target function only** to introduce a subtle contract "
        "violation. The bug should break the implicit agreement between the target "
        "and its callers/callees — especially the cross-file callers shown above. "
        "A bug that cascades across module boundaries is ideal. "
        "Remember: no comments revealing the bug, no "
        "signature changes, and the code must still parse correctly."
    )

    user_prompt = "\n".join(parts)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
