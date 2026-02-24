# SWE-smith: Contract-Aware Bug Generation

## Overview

This submission adds a new bug generation method to SWE-smith: **contract-aware
bug generation**. Instead of mutating a function in isolation, this method
analyzes inter-function dependencies via Abstract Syntax Tree (AST)
call-graph analysis and asks an
LLM to introduce bugs that exploit the implicit contracts between components.

The method has three strategy variants that build on each other:

1. **Contract Violation** (`--strategy contract_violation`): Rewrites a function
   with a bug that violates the implicit contract between caller and callee.
2. **Refactoring Drift** (`--strategy refactor_drift`): Refactors a function as
   a plausible code-quality improvement, hiding a subtle behavioral drift inside
   what looks like a legitimate cleanup.
3. **Multi-Site** (`--strategy multi_site`): Simulates a partial API migration —
   rewrites both a target function AND one cross-file caller with a new contract,
   leaving other callers un-updated. Produces multi-file bugs.

All strategies support single-file and cross-file (`--cross_file`) dependency
analysis. Multi-site automatically uses cross-file analysis.

For a detailed discussion of the research motivation, design decisions, and
rejected alternatives, see [METHODOLOGY.md](METHODOLOGY.md).

For a per-bug walkthrough of all 10 generated instances with analysis of what
makes each one interesting for agent evaluation, see [BUG_REPORT.md](BUG_REPORT.md).

## Research Motivation

Modern coding agents perform well on curated benchmarks but struggle with
production-like tasks. OpenAI's February 2026 analysis found that 59.4% of
remaining unsolved SWE-bench Verified tasks are flawed, with evidence of
training data contamination across frontier models
([source](https://the-decoder.com/openai-wants-to-retire-the-ai-coding-benchmark-that-everyone-has-been-competing-on/)).
On production-like benchmarks like SWE-bench Pro, baseline Sonnet 4.5 scored
43.6% without context augmentation
([source](https://www.prnewswire.com/news-releases/bitos-ai-architect-achieves-highest-success-rate-of-60-8-on-swe-bench-pro-302676926.html)).

The gap stems from problems that are structurally open-ended. OpenAI's
engineering team found that agents require extensive human-built scaffolding
to reason across module boundaries
([source](https://openai.com/index/harness-engineering/)).
Practitioner retrospectives identify "context drift" — agents losing coherence
across multi-step, multi-file tasks — as a persistent failure mode
([source](https://crawshaw.io/blog/eight-more-months-of-agents)).

Existing SWE-smith methods produce localized, single-function perturbations
that don't exercise cross-module reasoning. Contract-aware bug generation
fills this gap by producing bugs that require tracing indirect failures
(contract violation), distinguishing cosmetic from semantic changes
(refactoring drift), and reasoning about cross-file dependencies (multi-site).

## Installation

```bash
git clone <this-repo>
cd SWE-smith
conda create -n swesmith python=3.11 -y
conda activate swesmith
pip install -e ".[all]"
```

### API Key Setup

Set your Anthropic API key in the `.env` file at the repository root:

```bash
echo 'ANTHROPIC_API_KEY=<your-key>' >> .env
```

## Prerequisites: Build Docker Environment

Before generating bugs, you need a Docker image for the target repository.
The build is a two-step process: first export the conda environment spec,
then build the Docker image.

For the MonkeyType example used in this submission:

```bash
# Step 1: Export conda environment (installs repo, runs smoke test)
python -m swesmith.build_repo.try_install_py Instagram/MonkeyType configs/install_repo.sh \
    --commit 70c3acf62950be5dfb28743c7a719bfdecebcd84 \
    --extra-test-deps "pytest<8" \
    --smoke-cmd "pytest tests/ -q --maxfail=1" \
    --force

# Step 2: Build the Docker image from the exported environment
python -m swesmith.build_repo.create_images \
    -r MonkeyType \
    --user bbalaji-ucsd \
    -y --force

# Verify the image was created
docker images | grep MonkeyType
```

Step 1 clones the repository, installs it in a temporary conda environment,
runs the test suite as a smoke test, and exports the environment spec to
`logs/build_images/env/`. Step 2 reads that spec and builds a Docker image
`swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6:latest`.

To verify the tests pass inside the Docker container:

```bash
docker run --rm swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6 \
    bash -c "source /opt/miniconda3/bin/activate testbed && cd /testbed && pytest tests/ -q"
```

This should show 371 passed.

## Replication Steps

```bash
export repo=Instagram__MonkeyType.70c3acf6
```

### Step 1: Generate bugs

```bash
# Contract Violation (cross-file mode)
python -m swesmith.bug_gen.contract.generate $repo \
  --model anthropic/claude-sonnet-4-6 \
  --max_bugs 5 --cross_file --strategy contract_violation \
  --user bbalaji-ucsd

# Refactoring Drift (cross-file mode)
python -m swesmith.bug_gen.contract.generate $repo \
  --model anthropic/claude-sonnet-4-6 \
  --max_bugs 5 --cross_file --strategy refactor_drift \
  --user bbalaji-ucsd

# Multi-Site (automatically cross-file)
python -m swesmith.bug_gen.contract.generate $repo \
  --model anthropic/claude-sonnet-4-6 \
  --max_bugs 5 --strategy multi_site \
  --user bbalaji-ucsd
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
python -m swesmith.harness.gather logs/run_validation/$repo --user bbalaji-ucsd
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
  -c configs/issue_gen/ig_v2.yaml \
  --user bbalaji-ucsd
```

## Generated Instances

Pre-generated artifacts from our run are in
[`generated_instances/`](generated_instances/):

| Directory | Contents |
|---|---|
| [`generated_instances/bug_gen/`](generated_instances/bug_gen/) | Raw bug diffs and metadata |
| [`generated_instances/run_validation/`](generated_instances/run_validation/) | Validation results (per-instance pass/fail reports) |
| [`generated_instances/run_evaluation/`](generated_instances/run_evaluation/) | Gold-patch evaluation results |
| [`generated_instances/task_insts/`](generated_instances/task_insts/) | Final task instances in SWE-bench format |
| [`generated_instances/issue_gen/`](generated_instances/issue_gen/) | Generated issue descriptions |

When you run the replication steps above, the code writes output to `logs/`
(the default output directory).

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
- [`swesmith/bug_gen/contract/analyze.py`](swesmith/bug_gen/contract/analyze.py) — Static analysis: AST call graph, cross-file import resolution, multi-site context building
- [`swesmith/bug_gen/contract/generate.py`](swesmith/bug_gen/contract/generate.py) — Generation pipeline with `--strategy` flag
- [`swesmith/bug_gen/contract/prompts.py`](swesmith/bug_gen/contract/prompts.py) — System prompts for all three strategies
- [`swesmith/bug_gen/contract/README.md`](swesmith/bug_gen/contract/README.md) — Detailed documentation

Configuration:
- [`configs/bug_gen/contract_violation.yml`](configs/bug_gen/contract_violation.yml)
- [`configs/bug_gen/refactor_drift.yml`](configs/bug_gen/refactor_drift.yml)
- [`configs/bug_gen/multi_site.yml`](configs/bug_gen/multi_site.yml)

Tests:
- [`tests/bug_gen/contract/test_analyze.py`](tests/bug_gen/contract/test_analyze.py)
- [`tests/bug_gen/contract/test_generate.py`](tests/bug_gen/contract/test_generate.py)
- [`tests/bug_gen/contract/test_prompts.py`](tests/bug_gen/contract/test_prompts.py)

## Running Tests

```bash
python -m pytest tests/bug_gen/contract/ -v   # 48 tests
python -m pytest tests/ -q                     # 682 tests (full suite)
```
