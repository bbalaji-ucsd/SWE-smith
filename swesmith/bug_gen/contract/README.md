# Contract-Violation & Refactoring-Drift Bug Generation

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

## Motivation

Existing SWE-smith bug generation methods operate at the single-function level:

| Method | Approach | Limitation |
|---|---|---|
| **Procedural** | Syntactic transforms (swap operators, shuffle lines) | Mechanical, easy to detect |
| **LLM modify** | Ask LLM to introduce bugs in one function | No cross-function context |
| **LLM rewrite** | Blank out function, ask LLM to reimplement | Bugs are "wrong implementation", not "broken contract" |
| **Mirror** | Port real bugs from PRs | Requires existing PR history |

**Contract violation** and **refactoring drift** fill a gap: they generate bugs
that are **semantically realistic** because they exploit the implicit agreements
between functions that call each other.

## How it works

1. **Static analysis** (`analyze.py`): Parse source files' AST to extract
   all functions and build a call graph (who calls whom).

2. **Candidate selection**: Filter for functions with meaningful dependencies.
   In single-file mode, this means in-file callees. In cross-file mode, this
   means functions imported and called by other modules.

3. **Context-aware prompting** (`prompts.py`): Show the LLM the target function
   *plus* its callers, callees, and (in cross-file mode) functions from other
   files that import and use the target. The system prompt differs by strategy.

4. **Patch generation** (`generate.py`): Apply the LLM's rewrite, generate a
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
| `--strategy` | `contract_violation` | `contract_violation` or `refactor_drift` |
| `--user` | — | GitHub personal account for mirrors |
| `--org` | — | GitHub organization for mirrors |

## Running tests

```bash
python -m pytest tests/bug_gen/contract/ -v
```

A bug generation methodology for SWE-smith that produces bugs by analyzing
inter-function dependencies and asking an LLM to introduce subtle **contract
violations** — bugs that break the implicit agreements between caller and callee.

## Motivation

Existing SWE-smith bug generation methods operate at the single-function level:

| Method | Approach | Limitation |
|---|---|---|
| **Procedural** | Syntactic transforms (swap operators, shuffle lines) | Mechanical, easy to detect |
| **LLM modify** | Ask LLM to introduce bugs in one function | No cross-function context |
| **LLM rewrite** | Blank out function, ask LLM to reimplement | Bugs are "wrong implementation", not "broken contract" |
| **Mirror** | Port real bugs from PRs | Requires existing PR history |

**Contract violation** fills a gap: it generates bugs that are **semantically
realistic** because they exploit the implicit agreements between functions that
call each other. These are the kinds of bugs that survive code review — the
function looks correct in isolation, but breaks something upstream or downstream.

## How it works

1. **Static analysis** (`analyze.py`): Parse source files' AST to extract
   all functions and build a call graph (who calls whom).

2. **Candidate selection**: Filter for functions with meaningful dependencies.
   In single-file mode, this means in-file callees. In cross-file mode, this
   means functions imported and called by other modules.

3. **Context-aware prompting** (`prompts.py`): Show the LLM the target function
   *plus* its callers, callees, and (in cross-file mode) functions from other
   files that import and use the target.

4. **Patch generation** (`generate.py`): Apply the LLM's rewrite, generate a
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

## Usage

```bash
# Single-file mode
python -m swesmith.bug_gen.contract.generate $repo \
    --model openai/gpt-4o \
    --max_bugs 10

# Cross-file mode (recommended)
python -m swesmith.bug_gen.contract.generate $repo \
    --model bedrock/us.anthropic.claude-sonnet-4-6 \
    --max_bugs 10 \
    --cross_file

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
| `--user` | — | GitHub personal account for mirrors |
| `--org` | — | GitHub organization for mirrors |

## Running tests

```bash
python -m pytest tests/bug_gen/contract/ -v
```
