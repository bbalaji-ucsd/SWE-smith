"""
Contract-violation bug generation.

Given a repository, identify functions with inter-function dependencies and ask an
LLM to introduce bugs that violate the implicit contract between caller and callee.

Usage:
    python -m swesmith.bug_gen.contract.generate <repo> \\
        --model claude-3-5-sonnet-20241022 \\
        --max_bugs 10

Example:
    python -m swesmith.bug_gen.contract.generate Instagram__MonkeyType.70c3acf6 \\
        --model claude-3-5-sonnet-20241022 --max_bugs 10 --n_workers 2
"""

import argparse
import json
import litellm
import logging
import os
import random
import shutil
import subprocess

from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from litellm import completion
from litellm.cost_calculator import completion_cost
from swesmith.bug_gen.contract.analyze import (
    DependencyContext,
    MultiSiteContext,
    build_dependency_contexts,
    build_cross_file_contexts,
    build_multi_site_contexts,
    extract_functions,
)
from swesmith.bug_gen.contract.prompts import build_messages, build_multi_site_messages
from swesmith.bug_gen.llm.utils import extract_code_block
from swesmith.bug_gen.utils import (
    apply_code_change,
    get_bug_directory,
    get_patch,
)
from swesmith.constants import (
    LOG_DIR_BUG_GEN,
    PREFIX_BUG,
    PREFIX_METADATA,
    BugRewrite,
    CodeEntity,
)
from swesmith.profiles import registry, add_org_args, apply_org_args
from tqdm.auto import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from typing import Any

load_dotenv(dotenv_path=os.getenv("SWEFT_DOTENV_PATH"))

logging.getLogger("LiteLLM").setLevel(logging.WARNING)
litellm.drop_params = True
litellm.suppress_debug_info = True

VALID_STRATEGIES = ("contract_violation", "refactor_drift", "multi_site")


def _find_matching_entity(
    entities: list[CodeEntity], ctx: DependencyContext
) -> CodeEntity | None:
    """Find the CodeEntity that matches a DependencyContext target."""
    for entity in entities:
        if (
            entity.file_path == ctx.file_path
            and entity.line_start == ctx.target.line_start
            and entity.line_end == ctx.target.line_end
        ):
            return entity
    # Fallback: match by name and file
    for entity in entities:
        if entity.file_path == ctx.file_path and entity.name == ctx.target.name:
            return entity
    return None

def _extract_two_code_blocks(content: str) -> tuple[str | None, str | None]:
    """Extract two code blocks from LLM response (target + caller)."""
    blocks = []
    parts = content.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i]
        # Strip optional language tag (e.g., "python\n")
        if block.startswith(("python\n", "py\n")):
            block = block.split("\n", 1)[1]
        block = block.strip()
        if block:
            blocks.append(block)
    if len(blocks) >= 2:
        return blocks[0], blocks[1]
    return None, None


def _find_caller_entity(
    caller_file_path: str, caller_func_name: str, repo_root: str
) -> CodeEntity | None:
    """Find a CodeEntity for a cross-file caller function."""
    abs_path = os.path.join(repo_root, caller_file_path)
    if not os.path.exists(abs_path):
        return None
    functions = extract_functions(abs_path)
    for func in functions:
        if func.name == caller_func_name:
            # Build a minimal CodeEntity
            with open(abs_path, "r") as f:
                src = f.read()
            lines = src.splitlines(keepends=True)
            # Detect indent
            first_line = lines[func.line_start - 1] if func.line_start <= len(lines) else ""
            stripped = first_line.lstrip()
            indent_chars = len(first_line) - len(stripped)
            # Guess indent size (4 spaces default)
            indent_size = 4
            indent_level = indent_chars // indent_size if indent_size else 0
            return CodeEntity(
                file_path=abs_path,
                indent_level=indent_level,
                indent_size=indent_size,
                line_end=func.line_end,
                line_start=func.line_start,
                node=func.node,
                src_code=func.source,
            )
    return None


def gen_multi_site_violation(
    ctx: MultiSiteContext,
    model: str,
    repo_root: str,
    n_bugs: int = 1,
) -> list[tuple[BugRewrite, BugRewrite]]:
    """
    Generate a multi-site contract violation: rewrite target + one caller.

    Returns list of (target_rewrite, caller_rewrite) tuples.
    """
    messages = build_multi_site_messages(ctx)
    results = []

    for _ in range(n_bugs):
        try:
            response: Any = completion(
                model=model, messages=messages, n=1, temperature=1
            )
        except Exception as e:
            logging.warning(f"Multi-site LLM call failed for {ctx.target.qualified_name}: {e}")
            continue

        cost = completion_cost(completion_response=response)
        content = response.choices[0].message.content
        target_code, caller_code = _extract_two_code_blocks(content)
        if not target_code or not caller_code:
            logging.warning(f"Could not extract two code blocks for {ctx.target.qualified_name}")
            continue

        explanation = content.split("```")[0].strip()
        if "Explanation:" in content:
            explanation = content.split("Explanation:")[-1].split("```")[0].strip()

        target_rewrite = BugRewrite(
            rewrite=target_code,
            explanation=explanation,
            cost=cost / 2,
            strategy="multi_site",
            output=content,
        )
        caller_rewrite = BugRewrite(
            rewrite=caller_code,
            explanation=f"Coordinated caller update: {explanation}",
            cost=cost / 2,
            strategy="multi_site",
            output=content,
        )
        results.append((target_rewrite, caller_rewrite))

    return results



def gen_contract_violation(
    ctx: DependencyContext,
    model: str,
    n_bugs: int = 1,
    strategy: str = "contract_violation",
) -> list[BugRewrite]:
    """
    Given a dependency context, ask the LLM to introduce a contract-violating bug
    or a refactoring-drift bug.

    Returns a list of BugRewrite objects.
    """
    messages = build_messages(ctx, strategy=strategy)
    bugs = []

    # Loop individually — some providers (e.g. Bedrock) don't support n>1
    for _ in range(n_bugs):
        try:
            response: Any = completion(
                model=model, messages=messages, n=1, temperature=1
            )
        except Exception as e:
            logging.warning(f"LLM call failed for {ctx.target.qualified_name}: {e}")
            continue

        cost = completion_cost(completion_response=response)
        content = response.choices[0].message.content
        code_block = extract_code_block(content)
        if not code_block or len(code_block.strip()) == 0:
            continue

        # Extract explanation (text before the code block)
        explanation = content.split("```")[0].strip()
        if "Explanation:" in content:
            explanation = content.split("Explanation:")[-1].split("```")[0].strip()
        elif "Refactoring rationale:" in content:
            explanation = content.split("Refactoring rationale:")[-1].split("```")[0].strip()

        bugs.append(
            BugRewrite(
                rewrite=code_block,
                explanation=explanation,
                cost=cost,
                strategy=strategy,
                output=content,
            )
        )

    return bugs


def main(
    repo: str,
    model: str,
    n_bugs: int = 1,
    n_workers: int = 1,
    max_bugs: int = -1,
    seed: int = 24,
    min_callees: int = 1,
    cross_file: bool = False,
    strategy: str = "contract_violation",
):
    random.seed(seed)

    # Clone repository, extract entities
    print(f"Cloning {repo}...")
    rp = registry.get(repo)
    rp.clone()
    print("Extracting entities...")
    entities = rp.extract_entities()
    print(f"{len(entities)} entities found in {repo}")

    if not entities:
        print(f"No entities found in {repo}.")
        return

    # Set up logging
    log_dir = LOG_DIR_BUG_GEN / repo
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"Logging bugs to {log_dir}")

    if strategy == "multi_site":
        _run_multi_site(repo, model, entities, n_bugs, n_workers, max_bugs, seed, log_dir)
    else:
        _run_single_target(repo, model, entities, n_bugs, n_workers, max_bugs, seed,
                           min_callees, cross_file, strategy, log_dir)

    shutil.rmtree(repo)


def _run_multi_site(
    repo: str,
    model: str,
    entities: list[CodeEntity],
    n_bugs: int,
    n_workers: int,
    max_bugs: int,
    seed: int,
    log_dir,
):
    """Run multi-site contract violation generation."""
    print("Analyzing multi-site cross-file dependencies (need 2+ cross-file callers)...")
    ms_contexts = build_multi_site_contexts(repo, min_cross_file_usages=2)
    print(f"Found {len(ms_contexts)} multi-site candidates.")

    if not ms_contexts:
        print("No multi-site candidates found (need functions with 2+ cross-file callers).")
        return

    if max_bugs > 0:
        max_contexts = max_bugs // max(n_bugs, 1)
        if max_contexts < len(ms_contexts):
            random.shuffle(ms_contexts)
            ms_contexts = ms_contexts[:max_contexts]
            print(f"Limited to {len(ms_contexts)} contexts (max_bugs={max_bugs})")

    def _process_ms_context(ctx: MultiSiteContext):
        # Find the target entity
        target_entity = None
        for entity in entities:
            if (entity.file_path == ctx.target_file_path
                    and entity.line_start == ctx.target.line_start
                    and entity.line_end == ctx.target.line_end):
                target_entity = entity
                break
        if target_entity is None:
            for entity in entities:
                if entity.file_path == ctx.target_file_path and entity.name == ctx.target.name:
                    target_entity = entity
                    break
        if target_entity is None:
            return {"cost": 0.0, "n_bugs_generated": 0, "n_generation_failed": 1}

        # Find the caller entity
        caller_entity = _find_caller_entity(
            ctx.coordinated_caller.file_path,
            ctx.coordinated_caller.function_name,
            repo,
        )
        if caller_entity is None:
            logging.warning(f"Could not find caller entity for {ctx.coordinated_caller.function_name}")
            return {"cost": 0.0, "n_bugs_generated": 0, "n_generation_failed": 1}

        pairs = gen_multi_site_violation(ctx, model, repo, n_bugs)
        cost = sum(t.cost + c.cost for t, c in pairs)
        n_generated, n_failed = 0, 0

        for target_bug, caller_bug in pairs:
            bug_dir = get_bug_directory(log_dir, target_entity)
            bug_dir.mkdir(parents=True, exist_ok=True)
            combined_hash = target_bug.get_hash()[:4] + caller_bug.get_hash()[:4]
            uuid_str = f"multi_site__{combined_hash}"
            metadata_path = f"{PREFIX_METADATA}__{uuid_str}.json"
            bug_path = f"{PREFIX_BUG}__{uuid_str}.diff"

            try:
                metadata = {
                    **target_bug.to_dict(),
                    "target_function": ctx.target.qualified_name,
                    "coordinated_caller": {
                        "file": ctx.coordinated_caller.file_path,
                        "function": ctx.coordinated_caller.function_name,
                    },
                    "other_callers": [
                        {"file": u.file_path, "function": u.function_name}
                        for u in ctx.other_callers
                    ],
                }
                with open(bug_dir / metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)

                # Apply BOTH changes before getting the patch
                apply_code_change(target_entity, target_bug)
                apply_code_change(caller_entity, caller_bug)
                patch = get_patch(repo, reset_changes=True)
                if not patch:
                    raise ValueError("Patch is empty.")
                with open(bug_dir / bug_path, "w") as f:
                    f.write(patch)
            except Exception as e:
                logging.warning(
                    f"Error applying multi-site bug for {ctx.target.qualified_name}: {e}"
                )
                (bug_dir / metadata_path).unlink(missing_ok=True)
                # Reset repo in case of partial apply
                subprocess.run(["git", "-C", repo, "reset", "--hard"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "-C", repo, "clean", "-fdx"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                n_failed += 1
                continue
            else:
                n_generated += 1

        return {"cost": cost, "n_bugs_generated": n_generated, "n_generation_failed": n_failed}

    stats = {"cost": 0.0, "n_bugs_generated": 0, "n_generation_failed": 0}
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(_process_ms_context, ctx) for ctx in ms_contexts]
        with logging_redirect_tqdm():
            with tqdm(total=len(ms_contexts), desc="Generating (multi_site)") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    for k, v in result.items():
                        stats[k] += v
                    pbar.set_postfix(stats, refresh=True)
                    pbar.update(1)

    print(f"\nGeneration complete. Stats: {stats}")


def _run_single_target(
    repo: str,
    model: str,
    entities: list[CodeEntity],
    n_bugs: int,
    n_workers: int,
    max_bugs: int,
    seed: int,
    min_callees: int,
    cross_file: bool,
    strategy: str,
    log_dir,
):
    """Run single-target strategies (contract_violation, refactor_drift)."""
    all_contexts: list[DependencyContext] = []

    if cross_file:
        print("Analyzing cross-file dependencies...")
        all_contexts = build_cross_file_contexts(repo, min_callees=0)
        print(
            f"Found {len(all_contexts)} functions with cross-file dependencies."
        )
    else:
        # Build dependency contexts from all source files (single-file mode)
        print("Analyzing inter-function dependencies...")
        source_files = list({e.file_path for e in entities})
        for fp in source_files:
            try:
                contexts = build_dependency_contexts(fp, min_callees=min_callees)
                all_contexts.extend(contexts)
            except Exception as e:
                logging.warning(f"Failed to analyze {fp}: {e}")
        print(
            f"Found {len(all_contexts)} functions with inter-function dependencies "
            f"across {len(source_files)} files."
        )

    if not all_contexts:
        print("No dependency contexts found. Try lowering --min_callees.")
        return

    # Limit contexts if max_bugs is set
    if max_bugs > 0:
        max_contexts = max_bugs // max(n_bugs, 1)
        if max_contexts < len(all_contexts):
            random.shuffle(all_contexts)
            all_contexts = all_contexts[:max_contexts]
            print(f"Limited to {len(all_contexts)} contexts (max_bugs={max_bugs})")

    def _process_context(ctx: DependencyContext):
        entity = _find_matching_entity(entities, ctx)
        if entity is None:
            return {"cost": 0.0, "n_bugs_generated": 0, "n_generation_failed": 1}

        bugs = gen_contract_violation(ctx, model, n_bugs, strategy=strategy)
        cost = sum(b.cost for b in bugs)
        n_generated, n_failed = 0, 0

        for bug in bugs:
            bug_dir = get_bug_directory(log_dir, entity)
            bug_dir.mkdir(parents=True, exist_ok=True)
            uuid_str = f"{strategy}__{bug.get_hash()}"
            metadata_path = f"{PREFIX_METADATA}__{uuid_str}.json"
            bug_path = f"{PREFIX_BUG}__{uuid_str}.diff"

            try:
                metadata = {
                    **bug.to_dict(),
                    "target_function": ctx.target.qualified_name,
                    "callees": [c.qualified_name for c in ctx.callees],
                    "callers": [c.qualified_name for c in ctx.callers],
                }
                if ctx.cross_file_usages:
                    metadata["cross_file_usages"] = [
                        {
                            "file": u.file_path,
                            "function": u.function_name,
                            "imported_names": u.imported_names,
                        }
                        for u in ctx.cross_file_usages
                    ]
                with open(bug_dir / metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
                apply_code_change(entity, bug)
                patch = get_patch(repo, reset_changes=True)
                if not patch:
                    raise ValueError("Patch is empty.")
                with open(bug_dir / bug_path, "w") as f:
                    f.write(patch)
            except Exception as e:
                logging.warning(
                    f"Error applying bug to {entity.name} in {entity.file_path}: {e}"
                )
                (bug_dir / metadata_path).unlink(missing_ok=True)
                n_failed += 1
                continue
            else:
                n_generated += 1

        return {"cost": cost, "n_bugs_generated": n_generated, "n_generation_failed": n_failed}

    stats = {"cost": 0.0, "n_bugs_generated": 0, "n_generation_failed": 0}
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(_process_context, ctx) for ctx in all_contexts]

        with logging_redirect_tqdm():
            with tqdm(total=len(all_contexts), desc=f"Generating ({strategy})") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    for k, v in result.items():
                        stats[k] += v
                    pbar.set_postfix(stats, refresh=True)
                    pbar.update(1)

    print(f"\nGeneration complete. Stats: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate contract-violation bugs for a repository."
    )
    parser.add_argument(
        "repo",
        type=str,
        help="Name of a SWE-smith repository to generate bugs for.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="anthropic/claude-3-5-sonnet-20241022",
        help="LiteLLM model identifier.",
    )
    parser.add_argument(
        "-n", "--n_bugs", type=int, default=1, help="Bugs to generate per function."
    )
    parser.add_argument(
        "-w", "--n_workers", type=int, default=1, help="Number of parallel workers."
    )
    parser.add_argument(
        "-m", "--max_bugs", type=int, default=-1, help="Maximum total bugs to generate."
    )
    parser.add_argument(
        "-s", "--seed", type=int, default=24, help="Random seed."
    )
    parser.add_argument(
        "--min_callees",
        type=int,
        default=1,
        help="Minimum in-file callees for a function to be a candidate.",
    )
    parser.add_argument(
        "--cross_file",
        action="store_true",
        help="Use cross-file dependency analysis (shows the LLM how other modules use the target).",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="contract_violation",
        choices=VALID_STRATEGIES,
        help="Bug generation strategy: 'contract_violation' (default), 'refactor_drift', or 'multi_site'.",
    )
    add_org_args(parser)
    args = parser.parse_args()
    apply_org_args(args, parser)
    main(**vars(args))
