"""
Prompt templates for contract-violation bug generation.

The key insight: instead of asking the LLM to mutate a function in isolation,
we show it the function *and* its callers/callees, then ask it to introduce a
bug that violates the implicit contract between them.
"""

from swesmith.bug_gen.contract.analyze import CrossFileUsage, DependencyContext


SYSTEM_PROMPT_CONTRACT = """\
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

SYSTEM_PROMPT_REFACTOR_DRIFT = """\
You are an expert software engineer performing a code review and refactoring pass.

Your task: given a target function and the other functions it interacts with \
(callers, callees, and cross-file usage), refactor the target function to \
improve its code quality. Your refactoring should be a plausible improvement \
that a senior developer might propose in a pull request.

Acceptable refactoring patterns:
- Simplify complex conditional logic.
- Extract repeated expressions into local variables.
- Replace a loop with a more Pythonic comprehension (or vice versa).
- Improve variable naming for clarity.
- Consolidate duplicated branches.
- Replace manual iteration with a standard library call.
- Add early returns to reduce nesting.
- Normalize data handling (e.g., always return a list instead of sometimes None).

CRITICAL CONSTRAINT — introduce exactly ONE subtle behavioral drift:
Your refactoring must look like a genuine improvement, but it must silently \
change the function's behavior in a way that breaks at least one caller or \
test. The drift should be a *side effect* of the refactoring, not an obvious \
intentional bug.

IMPORTANT — maximize the chance of breaking tests:
- Target the PRIMARY code path, not edge cases. Most tests exercise the happy path.
- The behavioral change MUST affect the return value, a raised exception, or \
  shared mutable state on the most common inputs.
- Do NOT make purely cosmetic refactors (renaming variables, reordering \
  independent statements, extracting variables without changing evaluation). \
  These will not break anything.
- Do NOT add validation or type checks that were not there before — these are \
  obvious additions, not refactoring.
- Prefer changes that alter WHAT is returned or HOW iteration/filtering works.
- If the function has a conditional, change the condition's semantics (e.g., \
  ``is None`` → ``not``, ``>=`` → ``>``, ``in`` → ``==``).
- If the function builds a collection, change the collection semantics (e.g., \
  generator → list, set → list, dict ordering).

Examples of behavioral drift hidden inside refactoring:
- Simplifying ``if x is None: return []`` to ``if not x: return []`` — now \
  falsy values like 0 or "" are also caught.
- Replacing ``sorted(items)`` with ``list(set(items))`` for "deduplication" — \
  loses ordering.
- Extracting a variable but evaluating it once instead of per-iteration.
- Switching from ``dict.get(k, default)`` to ``dict[k]`` during "cleanup" — \
  now raises KeyError on missing keys.
- Adding an early return that skips a side effect (logging, state reset).
- Normalizing a return type (always list) when callers check for None.

Rules:
- The refactored code MUST NOT cause a syntax error or import error.
- The refactored code MUST NOT change the function signature.
- The refactored code MUST look like a legitimate improvement — it should pass \
  a casual code review.
- The behavioral drift SHOULD cause at least one existing test to fail.
- Do NOT add comments that reveal the drift.
- Output ONLY the refactored target function.

Format your response as:

Refactoring rationale:
<brief description of the refactoring improvement you made>

Refactored Code:
```
<refactored target function>
```"""



def build_messages(
    ctx: DependencyContext, strategy: str = "contract_violation"
) -> list[dict[str, str]]:
    """
    Build the LLM message list for a contract-violation or refactor-drift request.

    Args:
        ctx: The dependency context for the target function.
        strategy: Either "contract_violation" or "refactor_drift".
    """
    is_refactor = strategy == "refactor_drift"
    system_prompt = SYSTEM_PROMPT_REFACTOR_DRIFT if is_refactor else SYSTEM_PROMPT_CONTRACT

    # Build the user prompt with dependency context
    parts = [
        f"**File:** `{ctx.file_path}`\n",
    ]

    if is_refactor:
        parts.append("## Target function to refactor:\n")
    else:
        parts.append("## Target function to rewrite with a contract-violating bug:\n")

    parts.append(
        _format_function_block("Target", ctx.target.qualified_name, ctx.target.source)
    )

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

    if is_refactor:
        parts.append(
            "\n---\n"
            "Now refactor the **target function only** to improve its code quality. "
            "The refactoring must be a plausible improvement, but it must introduce "
            "exactly one subtle behavioral drift that breaks a caller or test. "
            "The drift should look like an accidental side effect of the refactoring, "
            "not an intentional bug. "
            "Remember: no comments revealing the drift, no signature changes, "
            "and the code must still parse correctly."
        )
    else:
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
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
