# Build Environments

SWE-smith enables automatic conversion of code repositories into reinforcement learning environments.

We'll review the three steps of this process:

1. Install a repository and generate a conda environment file.
2. Construct an execution environment (Docker image).
3. Verify the Docker image by running the test suite.

For this section, we'll use the [Instagram/MonkeyType](https://github.com/Instagram/MonkeyType/) repository as a running example, 
specifically at commit [`70c3acf`](https://github.com/Instagram/MonkeyType/tree/70c3acf62950be5dfb28743c7a719bfdecebcd84).

## Step 1: Install Repository and Generate Environment File

Before building a Docker image, you need to generate a conda environment YAML file by installing the repository locally. For Python repositories, use `try_install_py`:

```bash
python -m swesmith.build_repo.try_install_py Instagram/MonkeyType configs/install_repo.sh \
    --commit 70c3acf62950be5dfb28743c7a719bfdecebcd84 \
    --extra-test-deps "pytest<8" \
    --smoke-cmd "pytest tests/ -q --maxfail=1"
```

This will clone the repository, create a conda environment, install dependencies, run a smoke test, and export the environment to a YAML file under `logs/build_images/env/`.

For more details on Python-specific options (version selection, test deps, debugging), see the [Python Environment Options](../guides/env_construction_py.md) guide.

!!! note "Automatic installation with SWE-agent"

    We are working on a general-purpose automatic installation flow using SWE-agent. Coming soon!

## Step 2: Create an Execution Environment

Once the environment YAML file exists, run the following command to create a Docker image:

```bash
python -m swesmith.build_repo.create_images -r MonkeyType --user <github_username>
```

This command will create two artifacts:
1. A mirror of the original repository at the specified commit, created under your GitHub account. To change the target account, you can...
    * Pass `--user <username>` for a personal GitHub account, or
    * Pass `--org <org>` for a GitHub organization, or
    * (If built from source) Change `ORG_NAME_GH` in `swesmith/constants.py`

    `--org` and `--user` are mutually exclusive. The account type is auto-detected via the GitHub API.

2. A Docker image (`swebench/swesmith.x86_64.<repo>.<commit>`) which contains the installed codebase.

!!! note "`create_images` arguments"

    By default, without `-r`, the command will build images for *all* SWE-smith repositories (300+ as of 12/2025).
    
    `-r`: Select specific repositories to build using fuzzy matching (e.g., `-r django` matches any repo containing "django").
    
    `-f`: Force rebuild images even if they already exist locally.

    `-y`: Proceed without confirmation prompt.

    `--user`: GitHub personal account to create mirrors under.

    `--org`: GitHub organization to create mirrors under.

## Step 3: Verify the Docker Image

It's good practice to check that your Docker image works as expected. Start an interactive container:

```bash
docker run -it --rm swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6
```

Within the container, activate the environment and run the test suite:

```bash
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
pytest tests/
```

Expected output (for MonkeyType):

```
371 passed, 2 skipped, 1 xpassed, 702 warnings in 2.94s
```

All core tests should pass. A small number of skipped tests and `xpassed` (expected-failure tests that unexpectedly passed) are normal.

!!! note "Get existing Docker images"

    All repositories represented in the SWE-smith [dataset](https://huggingface.co/datasets/SWE-bench/SWE-smith) are available to download. Simply run:
    ```bash
    python -m swesmith.build_repo.download_images
    ```
