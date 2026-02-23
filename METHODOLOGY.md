# Methodology: Contract-Aware Bug Generation for SWE-smith

## The Gap We Target

Recent research (2025–2026) reveals a consistent pattern: modern coding agents
are strong at writing code but weak at doing engineering work. The tasks that
remain disproportionately hard for agents are exactly the ones human engineers
consider routine — debugging across modules, propagating changes through
dependency chains, and reasoning about implicit contracts between components.

On curated benchmarks like SWE-bench Verified, top agents exceed 70–80%
success. On production-like variants, success drops to 15–25%. The gap comes
from problems that are conceptually simple but structurally open-ended:
multi-file consistency, indirect failure signals, and long-horizon exploration.

The bugs in existing SWE-smith methods don't fully exercise these failure
modes. Procedural mutations (swap operators, shuffle lines) are mechanical.
Single-function LLM rewrites produce bugs that are localized and detectable
by reading one function. Neither requires the cross-module reasoning that
separates benchmark performance from real-world capability.

We introduce three bug generation strategies that target specific agent
weaknesses identified in recent research.

## Strategy 1: Contract Violation

**What it does.** Given a function and its callers/callees (extracted via AST
call-graph analysis), ask an LLM to rewrite the function with a bug that
violates the implicit contract between it and its dependencies. The function
still runs without crashing, but silently breaks an assumption that another
function depends on.

**Why it matters.** This targets the problem of *fixing tests that fail
indirectly*. The failing test doesn't directly describe the bug — it exercises
a caller that depends on a contract the target no longer honors. An agent must
trace the failure backward through the call chain to find the root cause,
which requires the kind of hypothesis testing that agents consistently
struggle with.

The key design choice is showing the LLM the dependency context (callers,
callees, cross-file importers) rather than the function in isolation. This
produces bugs that are semantically realistic — they look like plausible
implementations that happen to break a downstream assumption.

## Strategy 2: Refactoring Drift

**What it does.** Ask the LLM to refactor the target function as a plausible
code-quality improvement, with exactly one subtle behavioral drift hidden
inside the cleanup.

**Why it matters.** This targets the problem of *small conceptual change,
large surface impact*. The diff looks like an improvement — a developer might
propose it in a pull request. The behavioral change is a side effect of the
refactoring, not an obvious intentional bug.

This is harder to detect than contract violation because the agent must
distinguish between cosmetic changes (safe) and semantic changes (buggy)
within a diff that looks uniformly like cleanup. Agents are known to struggle
with abstraction-level reasoning — understanding *intent* behind code changes
rather than just *syntax*.

## Strategy 3: Multi-Site

**What it does.** Simulate a partial API migration: rewrite both a target
function AND one cross-file caller with a new, internally consistent contract.
Other callers in different files are left un-updated. The bug is the mismatch
between updated and un-updated call sites.

**Why it matters.** This directly targets *multi-file consistency edits*,
which research consistently identifies as a core agent failure mode. To fix
a multi-site bug, an agent must:

1. Identify that two files are wrong (not just one)
2. Understand the contract between them
3. Determine which version of the contract is "correct" (the original)
4. Fix both files consistently

The coordinated caller's change looks intentional — it's consistent with the
target's new behavior. An agent that only looks at one file will either miss
the bug entirely or "fix" the wrong file. The agent must reason about the
*relationship* between modules, not just local correctness.

**Implementation detail.** We discovered that the coordinated caller must be
a source file, not a test file. The SWE-bench eval harness restores test files
after applying the gold patch, so modifying test files as coordinated callers
causes gold eval failures. We filter test files from the coordinated caller
selection during static analysis.

## Why These Methods Over Alternatives

We evaluated several candidate approaches before selecting these three. The
key criteria were:

**Scalability.** The method must work on any Python repository with a Docker
environment, without requiring PR history, issue databases, or manual
annotation. All three strategies use only static analysis (AST parsing) and
a single LLM call per bug.

**Realism.** The bugs must look like plausible mistakes, not synthetic
mutations. Contract violation and refactoring drift both produce bugs that
could survive code review. Multi-site produces bugs that look like incomplete
migrations — a common failure mode in real codebases.

**Complementarity.** Each strategy targets a different agent weakness.
Contract violation tests indirect failure tracing. Refactoring drift tests
intent reasoning. Multi-site tests cross-module consistency.

### Rejected alternatives

Several approaches sound appealing in the abstract but don't work within
SWE-smith's architecture:

**Performance regression.** SWE-smith's validation harness runs tests and
checks pass/fail. There's no infrastructure for runtime thresholds, and most
repos don't have performance benchmarks in their test suites. This would
require a completely different validation pipeline.

**Concurrency bugs.** Nondeterministic failures can't be reliably validated
with a deterministic test harness. You'd need probabilistic validation (run
N times, check failure rate), which is a fundamental architecture change.

**Dependency/environment perturbation.** SWE-smith builds Docker images with
pinned environments. Changing dependencies means rebuilding the image, which
is expensive and fragile. The bug also wouldn't be in the code — it'd be in
the environment — so there's no code patch to learn from.

**Specification reinterpretation.** "Change requirements, not code" sounds
elegant but the agent needs to produce a code patch. If the code isn't wrong,
what's the training signal? You'd need to modify tests and code, which makes
the task definition circular.

**Test-coverage exploitation.** Generating bugs that pass tests but violate
spec is the opposite of what SWE-smith needs. The whole pipeline depends on
test failures to validate bugs.

## Results Summary

Tested on Instagram/MonkeyType (368 tests, 299 code entities):

| Strategy | Generated | Valid | Rate | Gold Eval | Avg Tests Broken |
|---|---|---|---|---|---|
| Contract Violation | 5 | 4 | 80% | 4/4 ✓ | 6.8 |
| Refactoring Drift | 5 | 2 | 40% | 2/2 ✓ | 1.0 |
| Multi-Site | 5 | 4 | 80% | 4/4 ✓ | 22.2 |

Multi-site bugs break significantly more tests on average (22.2 vs 6.8 and
1.0), reflecting their broader cross-module impact. Refactoring drift has a
lower validation rate but produces the most deceptive bugs — minimal diffs
with minimal test signal.

## Next Steps

**Partial migration.** Pick a pattern used throughout the codebase (e.g., a
utility function, a class interface, a naming convention). Ask the LLM to
"migrate" some call sites to a new pattern but leave others unchanged. The
inconsistency breaks tests. This is a natural extension of multi-site: the
cross-file analysis already identifies pattern usage sites, the diff is
multi-file (harder to fix), and the fix requires understanding the migration
direction and completing it. Where multi-site coordinates one target and one
caller, partial migration would coordinate a pattern change across N call
sites with K left un-updated — producing bugs with tunable difficulty.

**Adversarial difficulty calibration.** Use an agent-in-the-loop to filter
generated bugs: run a baseline agent on each candidate and only keep bugs
the agent fails to solve. This would produce a benchmark that specifically
targets current agent weaknesses rather than sampling uniformly.

**Cross-language generalization.** The static analysis (AST call graph,
import resolution) is Python-specific, but the prompting strategy is
language-agnostic. Extending to TypeScript or Java would test whether the
approach generalizes.
