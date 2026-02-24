# SWE-smith: Contract-Violation, Refactoring-Drift & Multi-Site Bug Generation

## Overview

This submission adds three new bug generation strategies to SWE-smith that produce harder, more realistic bugs by analyzing inter-function dependencies:

1. **Contract Violation** (`--strategy contract_violation`): Rewrites a function with a bug that violates the implicit contract between caller and callee.
2. **Refactoring Drift** (`--strategy refactor_drift`): Refactors a function as a plausible code-quality improvement, where the bug is a subtle behavioral drift hidden inside what looks like a legitimate cleanup.
3. **Multi-Site** (`--strategy multi_site`): Simulates a partial API migration — rewrites both a target function AND one cross-file caller with a new contract, leaving other callers un-updated. Produces multi-file bugs.

All strategies support single-file and cross-file (`--cross_file`) dependency analysis. Multi-site automatically uses cross-file analysis.

For a detailed discussion of the research motivation, design decisions, and rejected alternatives, see [METHODOLOGY.md](METHODOLOGY.md).

For a per-bug walkthrough of all 10 generated instances with analysis of what makes each one interesting for agent evaluation, see [BUG_REPORT.md](BUG_REPORT.md).

## Research Motivation

Existing SWE-smith methods generate single-function, single-file bugs. Real-world bugs often involve **cross-module contract violations** — a function's behavior changes and some callers are updated but others are not. This is especially common during refactoring, API evolution, and partial migrations.

**Multi-site** produces **coordinated multi-file bugs**, which are harder for LLM agents because:
- The agent must identify that TWO files are wrong (not just one)
- The coordinated caller's change looks intentional, making it harder to detect
- Fixing requires understanding the contract between modules, not just local code

Multi-site bugs test whether coding agents can reason about **cross-module dependencies** — a capability that single-file benchmarks don't evaluate well.

## Installation

No additional dependencies beyond the standard SWE-smith setup:

```bash
git clone <this-repo>
cd SWE-smith
pip install -e ".[dev]"
```

## Prerequisites

Before generating bugs, you need a Docker environment for the target repository. Follow the [Environment Construction guide](docs/guides/env_construction_py.md) or use an existing image.

For the MonkeyType example used in this submission:

```bash
# The Docker image should already exist: swesmith/Instagram__MonkeyType.70c3acf6:latest
docker images | grep MonkeyType
```

## Replication Steps

Replace `$repo` with `Instagram__MonkeyType.70c3acf6` (or any repo with a built Docker image).

```bash
export repo=Instagram__MonkeyType.70c3acf6
```

### Step 1: Generate bugs

```bash
# Contract Violation (cross-file mode)
python -m swesmith.bug_gen.contract.generate $repo \
  --model bedrock/us.anthropic.claude-sonnet-4-6 \
  --max_bugs 5 --cross_file --strategy contract_violation \
  --user <github_username>

# Refactoring Drift (cross-file mode)
python -m swesmith.bug_gen.contract.generate $repo \
  --model bedrock/us.anthropic.claude-sonnet-4-6 \
  --max_bugs 5 --cross_file --strategy refactor_drift \
  --user <github_username>

# Multi-Site (automatically cross-file)
python -m swesmith.bug_gen.contract.generate $repo \
  --model bedrock/us.anthropic.claude-sonnet-4-6 \
  --max_bugs 5 --strategy multi_site \
  --user <github_username>
```

### Step 2: Collect patches

```bash
python -m swesmith.bug_gen.collect_patches logs/bug_gen/$repo
```

### Step 3: Validate bugs

```bash
python -m swesmith.harness.valid logs/bug_gen/${repo}_all_patches.json
```

### Step 4: Gather valid instances

```bash
python -m swesmith.harness.gather logs/run_validation/$repo --user <github_username>
```

### Step 5: Evaluate with gold patches

```bash
python -m swesmith.harness.eval \
  -d logs/task_insts/${repo}.json \
  --run_id eval_all
```

### Step 6: Generate issue descriptions

```bash
python -m swesmith.issue_gen.generate \
  -d logs/task_insts/${repo}.json \
  -c configs/issue_gen/ig_v2_bedrock.yaml \
  --user <github_username>
```

## Generated Instances

All generated artifacts are in the `logs/` directory:

| Directory | Contents |
|---|---|
| `logs/bug_gen/` | Raw bug diffs and metadata |
| `logs/run_validation/` | Validation results (per-instance reports) |
| `logs/run_evaluation/` | Gold-patch evaluation results |
| `logs/task_insts/` | Final task instances in SWE-bench format |
| `logs/issue_gen/` | Generated issue descriptions |

### Summary of results

| Strategy | Generated | Valid | Validation Rate | Gold Eval | Issues |
|---|---|---|---|---|---|
| Contract Violation (cross-file) | 5 | 4 | 80% | 4/4 ✓ | 4 |
| Refactoring Drift (cross-file) | 5 | 2 | 40% | 2/2 ✓ | 2 |
| Multi-Site | 5 | 4 | 80% | 4/4 ✓ | 4 |
| **Total** | **15** | **10** | **67%** | **10/10** | **10** |

### Difficulty analysis

| Bug ID | Strategy | Files | Diff | F2P | Difficulty |
|---|---|---|---|---|---|
| `refactor_drift__teococyw` | refactor_drift | 1 | +1/-1 | 1 | Hard — `if (x is None) or (x == "null")` → `if not x`, minimal signal |
| `multi_site__ugn4y34m` | multi_site | 2 | +3/-3 | 5 | Hard — `pascal_case` returns list instead of string, 2-file fix |
| `multi_site__jb2mkutw` | multi_site | 2 | +5/-3 | 9 | Medium — return type change across compat.py → encoding.py |
| `multi_site__x0jlc96y` | multi_site | 2 | +7/-5 | 31 | Medium — tuple→dict return type, 2-file coordinated change |
| `multi_site__lyvaed11` | multi_site | 2 | +2/-2 | 44 | Medium — return type change across util.py → cli.py, many tests |
| `contract_violation__phv96u4q` | contract_violation | 1 | +1/-1 | 12 | Medium — `is None` → `is not None` condition inversion |
| `contract_violation__2opq6lvu` | contract_violation | 1 | +1/-1 | 1 | Medium — `except Exception` → `except TypeError` |
| `contract_violation__fu4p89oi` | contract_violation | 1 | +3/-1 | 1 | Medium — `"null"` handling split into separate branch |
| `contract_violation__ssmtghz1` | contract_violation | 1 | +2/-0 | 13 | Medium — strips `elem_types` from generic type dicts |
| `refactor_drift__05o1fv9q` | refactor_drift | 1 | +2/-1 | 1 | Medium — `json.loads` → `ast.literal_eval` |

### Valid instance IDs

Contract Violation:
- `Instagram__MonkeyType.70c3acf6.contract_violation__2opq6lvu` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__fu4p89oi` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__phv96u4q` (12 tests broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__ssmtghz1` (13 tests broken)

Refactoring Drift:
- `Instagram__MonkeyType.70c3acf6.refactor_drift__05o1fv9q` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.refactor_drift__teococyw` (1 test broken)

Multi-Site:
- `Instagram__MonkeyType.70c3acf6.multi_site__jb2mkutw` (9 tests broken, 2 files)
- `Instagram__MonkeyType.70c3acf6.multi_site__lyvaed11` (44 tests broken, 2 files)
- `Instagram__MonkeyType.70c3acf6.multi_site__ugn4y34m` (5 tests broken, 2 files)
- `Instagram__MonkeyType.70c3acf6.multi_site__x0jlc96y` (31 tests broken, 2 files)

## Implementation Files

Core implementation:
- `swesmith/bug_gen/contract/analyze.py` — Static analysis: AST call graph, cross-file import resolution, multi-site context building
- `swesmith/bug_gen/contract/generate.py` — Generation pipeline with `--strategy` flag
- `swesmith/bug_gen/contract/prompts.py` — System prompts for all three strategies
- `swesmith/bug_gen/contract/README.md` — Detailed documentation

Configuration:
- `configs/bug_gen/contract_violation.yml`
- `configs/bug_gen/refactor_drift.yml`
- `configs/bug_gen/multi_site.yml`

Tests:
- `tests/bug_gen/contract/test_analyze.py`
- `tests/bug_gen/contract/test_generate.py`
- `tests/bug_gen/contract/test_prompts.py`

## Running Tests

```bash
python -m pytest tests/bug_gen/contract/ -v   # 48 tests
python -m pytest tests/ -q                     # 682 tests (full suite)
```
