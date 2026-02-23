# Contract-Violation, Refactoring-Drift & Multi-Site Bug Generation

Bug generation methodologies for SWE-smith that produce bugs by analyzing
inter-function dependencies and asking an LLM to introduce subtle defects
that exploit the implicit agreements between caller and callee.

## Strategies

### Contract Violation (default)

Ask the LLM to rewrite a target function with a **contract-violating bug** —
a change that breaks the implicit agreement between the target and its
callers/callees. The function looks correct in isolation but breaks something
upstream or downstream.

### Refactoring Drift (`--strategy refactor_drift`)

Ask the LLM to **refactor** the target function as a plausible code-quality
improvement. The bug is a *side effect* of the refactoring — a subtle
behavioral drift hidden inside what looks like a legitimate cleanup. These
bugs are harder to detect because the diff looks like an improvement, not a
mistake.

Examples of refactoring drift:
- Simplifying `if x is None` to `if not x` (now catches falsy values like 0)
- Replacing `sorted(items)` with `list(set(items))` (loses ordering)
- Adding an early return that skips a side effect
- Switching from `dict.get(k, default)` to `dict[k]` (raises on missing keys)

### Multi-Site (`--strategy multi_site`)

The most challenging strategy. Simulates a **partial API migration** where a
function's contract is changed and *some* callers are updated but others are
not. The LLM rewrites both the target function and one "coordinated caller"
in a different file to work with a new contract, while leaving other callers
un-updated — creating a multi-file bug that requires understanding cross-module
dependencies to fix.

This is uniquely interesting from a research perspective because:
- It produces **multi-file bugs** (no other SWE-smith strategy does this)
- The bug is a **partial migration** — a realistic failure mode in real codebases
- An agent must identify that TWO files are wrong and fix both consistently
- The coordinated caller's change looks intentional, making it harder to detect

Examples of multi-site bugs:
- Target returns a dict instead of a tuple; one caller unpacks the dict, others still unpack a tuple
- Target returns a list instead of a string; one caller joins it, others assume string operations
- Target changes error handling; one caller is updated, others still catch the old exception

**Important constraint:** The coordinated caller must be a source file, not a
test file. The eval harness restores test files after applying the gold patch,
so modifying test files as coordinated callers would cause gold eval failures.

## Motivation

Existing SWE-smith bug generation methods operate at the single-function level:

| Method | Approach | Limitation |
|---|---|---|
| **Procedural** | Syntactic transforms (swap operators, shuffle lines) | Mechanical, easy to detect |
| **LLM modify** | Ask LLM to introduce bugs in one function | No cross-function context |
| **LLM rewrite** | Blank out function, ask LLM to reimplement | Bugs are "wrong implementation", not "broken contract" |
| **Mirror** | Port real bugs from PRs | Requires existing PR history |

**Contract violation**, **refactoring drift**, and **multi-site** fill a gap:
they generate bugs that are **semantically realistic** because they exploit the
implicit agreements between functions that call each other.

## How it works

1. **Static analysis** (`analyze.py`): Parse source files' AST to extract
   all functions and build a call graph (who calls whom). For multi-site,
   also resolve cross-file imports to find callers in other modules.

2. **Candidate selection**: Filter for functions with meaningful dependencies.
   In single-file mode, this means in-file callees. In cross-file mode, this
   means functions imported and called by other modules. For multi-site, need
   2+ cross-file callers with at least one non-test source caller.

3. **Context-aware prompting** (`prompts.py`): Show the LLM the target function
   *plus* its callers, callees, and (in cross-file/multi-site mode) functions
   from other files that import and use the target. The system prompt differs
   by strategy.

4. **Patch generation** (`generate.py`): Apply the LLM's rewrite(s), generate a
   git-compatible diff, and save it alongside metadata.

## Modes

### Single-file (default)

Analyzes caller/callee relationships within one file. Functions must have at
least `--min_callees` in-file callees to be candidates.

### Cross-file (`--cross_file`)

Scans the entire repository to find functions in other modules that import and
call the target. The LLM sees cross-module usage context, producing bugs that
cascade across module boundaries. This mode typically has a higher validation
rate and breaks more tests per bug.

### Multi-site (`--strategy multi_site`)

Automatically uses cross-file analysis. Finds functions with 2+ cross-file
callers, picks one as the "coordinated caller" to update alongside the target,
and leaves the rest un-updated. Produces multi-file diffs.

## Usage

```bash
# Contract violation — single-file mode
python -m swesmith.bug_gen.contract.generate $repo \
    --model openai/gpt-4o \
    --max_bugs 10

# Contract violation — cross-file mode (recommended)
python -m swesmith.bug_gen.contract.generate $repo \
    --model bedrock/us.anthropic.claude-sonnet-4-6 \
    --max_bugs 10 \
    --cross_file

# Refactoring drift — cross-file mode (recommended)
python -m swesmith.bug_gen.contract.generate $repo \
    --model bedrock/us.anthropic.claude-sonnet-4-6 \
    --max_bugs 10 \
    --cross_file \
    --strategy refactor_drift

# Multi-site — automatically cross-file
python -m swesmith.bug_gen.contract.generate $repo \
    --model bedrock/us.anthropic.claude-sonnet-4-6 \
    --max_bugs 5 \
    --strategy multi_site

# Then collect patches (same as other bug_gen methods)
python -m swesmith.bug_gen.collect_patches logs/bug_gen/$repo
```

### CLI arguments

| Argument | Default | Description |
|---|---|---|
| `repo` | (required) | SWE-smith repository name |
| `--model` | `anthropic/claude-3-5-sonnet-20241022` | LiteLLM model identifier |
| `-n, --n_bugs` | `1` | Bugs to generate per function |
| `-w, --n_workers` | `1` | Parallel workers |
| `-m, --max_bugs` | `-1` (unlimited) | Maximum total bugs |
| `-s, --seed` | `24` | Random seed |
| `--min_callees` | `1` | Minimum in-file callees (single-file mode) |
| `--cross_file` | `false` | Enable cross-file dependency analysis |
| `--strategy` | `contract_violation` | `contract_violation`, `refactor_drift`, or `multi_site` |
| `--user` | — | GitHub personal account for mirrors |
| `--org` | — | GitHub organization for mirrors |

## Running tests

```bash
python -m pytest tests/bug_gen/contract/ -v
```
