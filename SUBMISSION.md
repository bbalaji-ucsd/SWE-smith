# SWE-smith: Contract-Violation & Refactoring-Drift Bug Generation

## Overview

This submission adds two new bug generation strategies to SWE-smith that produce harder, more realistic bugs by analyzing inter-function dependencies:

1. **Contract Violation** (`--strategy contract_violation`): Asks an LLM to rewrite a function with a bug that violates the implicit contract between caller and callee.
2. **Refactoring Drift** (`--strategy refactor_drift`): Asks an LLM to *refactor* a function as a plausible code-quality improvement, where the bug is a subtle behavioral drift hidden inside what looks like a legitimate cleanup.

Both strategies support single-file and cross-file (`--cross_file`) dependency analysis. Cross-file mode scans the repository for functions imported by other modules and shows the LLM cross-module context, producing bugs that cascade across module boundaries.

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

Below are the exact commands to replicate the bug generation pipeline with the new methods. Replace `$repo` with `Instagram__MonkeyType.70c3acf6` (or any other repo with a built Docker image).

```bash
export repo=Instagram__MonkeyType.70c3acf6
```

### Step 1: Generate bugs (Contract Violation, cross-file mode)

```bash
python -m swesmith.bug_gen.contract.generate $repo \
  --model bedrock/us.anthropic.claude-sonnet-4-6 \
  --max_bugs 5 \
  --cross_file \
  --strategy contract_violation \
  --user <github_username>
```

### Step 2: Generate bugs (Refactoring Drift, cross-file mode)

```bash
python -m swesmith.bug_gen.contract.generate $repo \
  --model bedrock/us.anthropic.claude-sonnet-4-6 \
  --max_bugs 5 \
  --cross_file \
  --strategy refactor_drift \
  --user <github_username>
```

### Step 3: Collect patches

```bash
python -m swesmith.bug_gen.collect_patches logs/bug_gen/$repo
```

### Step 4: Validate bugs

Runs each candidate patch in Docker, checks which ones break at least one test:

```bash
python -m swesmith.harness.valid logs/bug_gen/${repo}_all_patches.json
```

### Step 5: Gather valid instances

Converts validated patches into task instances (SWE-bench format):

```bash
python -m swesmith.harness.gather logs/run_validation/$repo \
  --user <github_username>
```

### Step 6: Evaluate with gold patches

Verifies that the gold (reverse) patch resolves each instance:

```bash
python -m swesmith.harness.eval \
  -d logs/task_insts/${repo}.json \
  --run_id eval_contract
```

### Step 7: Generate issue descriptions

```bash
python -m swesmith.issue_gen.generate \
  -d logs/task_insts/${repo}.json \
  -c configs/issue_gen/ig_v2_bedrock.yaml \
  --user <github_username>
```

## Generated Instances

All generated artifacts are included in the `logs/` directory:

| Directory | Contents |
|---|---|
| `logs/bug_gen/` | Raw bug diffs and metadata |
| `logs/run_validation/` | Validation results (per-instance reports) |
| `logs/run_evaluation/` | Gold-patch evaluation results |
| `logs/task_insts/` | Final task instances in SWE-bench format |
| `logs/issue_gen/` | Generated issue descriptions |

### Summary of results

| Strategy | Generated | Valid | Validation Rate | Eval (gold) | Issues |
|---|---|---|---|---|---|
| Contract Violation (cross-file) | 5 | 4 | 80% | 4/4 resolved | 4 |
| Refactoring Drift (cross-file) | 5 | 3 | 60% | 3/3 resolved | 3 |
| **Total** | **10** | **7** | **70%** | **7/7** | **7** |

### Valid instance IDs

Contract Violation:
- `Instagram__MonkeyType.70c3acf6.contract_violation__2opq6lvu` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__fu4p89oi` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__phv96u4q` (12 tests broken)
- `Instagram__MonkeyType.70c3acf6.contract_violation__ssmtghz1` (13 tests broken)

Refactoring Drift:
- `Instagram__MonkeyType.70c3acf6.refactor_drift__05o1fv9q` (1 test broken)
- `Instagram__MonkeyType.70c3acf6.refactor_drift__phv96u4q` (12 tests broken)
- `Instagram__MonkeyType.70c3acf6.refactor_drift__teococyw` (1 test broken)

## Implementation Files

Core implementation:
- `swesmith/bug_gen/contract/analyze.py` — Static analysis: AST call graph, cross-file import resolution
- `swesmith/bug_gen/contract/generate.py` — Generation pipeline with `--strategy` flag
- `swesmith/bug_gen/contract/prompts.py` — System prompts for both strategies
- `swesmith/bug_gen/contract/README.md` — Detailed documentation

Configuration:
- `configs/bug_gen/contract_violation.yml`
- `configs/bug_gen/refactor_drift.yml`

Tests:
- `tests/bug_gen/contract/test_analyze.py`
- `tests/bug_gen/contract/test_generate.py`
- `tests/bug_gen/contract/test_prompts.py`

Documentation:
- `docs/guides/create_instances.md` — Updated with contract violation and refactoring drift sections

## Running Tests

```bash
python -m pytest tests/bug_gen/contract/ -v   # 35 tests
python -m pytest tests/ -q                     # 669 tests (full suite)
```
