# Methodology: Contract-Aware Bug Generation for SWE-smith

## The Gap We Target

Modern coding agents perform well on curated benchmarks but struggle with
production-like tasks. On SWE-bench Verified, top agents report ~80% success,
but OpenAI's February 2026 analysis found that 59.4% of remaining unsolved
tasks are flawed and that frontier models show evidence of training data
contamination [1], leading OpenAI and the original benchmark authors to
recommend its retirement in favor of SWE-bench Pro. Anthropic's concurrent
research demonstrated that infrastructure noise alone can swing benchmark
scores by 6 percentage points [2]. On production-like benchmarks, performance
drops significantly — on SWE-bench Pro, which tests longer-horizon tasks
across larger codebases, baseline Sonnet 4.5 scored 43.6% without context
augmentation [3].

The gap stems from problems that are conceptually simple but structurally
open-ended. OpenAI's own engineering team found that agents require extensive
human-built scaffolding to reason across module boundaries, and that "the
primary job of [the] engineering team became enabling the [agent]" to handle
cross-file dependencies [4]. Practitioner retrospectives identify "context
drift" — agents losing coherence across multi-step, multi-file tasks — as a
persistent failure mode even with frontier models [5]. The existing bug
generation strategies in SWE-smith produce localized perturbations that don't
exercise these cross-module reasoning capabilities [6].

We introduce a contract-aware bug generation method with three strategy
variants that target specific agent weaknesses identified in this research.

## The Method: Contract-Aware Bug Generation

The core idea: instead of mutating a function in isolation, analyze its
inter-function dependencies (callers, callees, cross-file importers) via
AST call-graph analysis, then ask an LLM to introduce bugs that exploit
the implicit contracts between components.

This produces three strategy variants of increasing complexity:

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
struggle with [5].

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
rather than just *syntax* [4][5].

## Strategy 3: Multi-Site

**What it does.** Simulate a partial API migration: rewrite both a target
function AND one cross-file caller with a new, internally consistent contract.
Other callers in different files are left un-updated. The bug is the mismatch
between updated and un-updated call sites.

**Why it matters.** This directly targets *multi-file consistency edits*,
which research consistently identifies as a core agent failure mode [4][5].
To fix a multi-site bug, an agent must:

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

## Why This Method Over Alternatives

The key criteria were:

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

- **Performance regression.** SWE-smith's validation harness checks pass/fail.
  There's no infrastructure for runtime thresholds, and most repos don't have
  performance benchmarks in their test suites.

- **Concurrency bugs.** Nondeterministic failures can't be reliably validated
  with a deterministic test harness.

- **Dependency/environment perturbation.** SWE-smith builds Docker images with
  pinned environments. Changing dependencies means rebuilding the image, and
  the bug wouldn't be in the code — so there's no code patch to learn from.

- **Test-coverage exploitation.** Generating bugs that pass tests but violate
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

## References

[1] OpenAI, "SWE-bench Verified Retirement Analysis," Feb 2026.
    https://the-decoder.com/openai-wants-to-retire-the-ai-coding-benchmark-that-everyone-has-been-competing-on/

[2] Anthropic, "Quantifying Infrastructure Noise in Agentic Coding Evals," Feb 2026.
    https://www.anthropic.com/engineering/infrastructure-noise

[3] Bito, "AI Architect Achieves 60.8% on SWE-Bench Pro," Feb 2026.
    https://www.prnewswire.com/news-releases/bitos-ai-architect-achieves-highest-success-rate-of-60-8-on-swe-bench-pro-302676926.html

[4] OpenAI, "Harness Engineering: Leveraging Codex in an Agent-First World," Feb 2026.
    https://openai.com/index/harness-engineering/

[5] D. Crawshaw, "Eight More Months of Agents," Feb 2026.
    https://crawshaw.io/blog/eight-more-months-of-agents

[6] J. Yang et al., "SWE-smith: Scaling Data for Software Engineering Agents," NeurIPS 2025.
    https://arxiv.org/abs/2504.21798
