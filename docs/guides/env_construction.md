# Build Environments

SWE-smith enables automatic conversion of code repositories into reinforcement learning environments.

We'll review the two steps of this process:

1. SWE-agent + LM attempts to install a repository + run the testing suite.
2. Construct an execution environment (Docker image).

For this section, we'll use the [Instagram/MonkeyType](https://github.com/Instagram/MonkeyType/) repository as a running example, 
specifically at commit [`70c3acf`](https://github.com/Instagram/MonkeyType/tree/70c3acf62950be5dfb28743c7a719bfdecebcd84).

## Automatically Install Repos with SWE-agent

Coming soon!

!!! note "Python installation scripts"

    Early on in SWE-smith's development, we focused exclusively on Python repositories and wrote Python-specific scripts for automatic repo instllation.
    More information [here](../guides/env_construction_py.md)

## Create an Execution Environment
Run the following command to create a Docker image for the repository.

```bash
python -m swesmith.build_repo.create_images -r MonkeyType --user <github_username>
```

This command will create two artifacts:
1. A mirror of the original repository at the specified commit, created under your GitHub account. To change the target account, you can...
    * Pass `--user <username>` for a personal GitHub account, or
    * Pass `--org <org>` for a GitHub organization, or
    * (If built from source) Change `ORG_NAME_GH` in `swesmith/constants.py`

    `--org` and `--user` are mutually exclusive. The account type is auto-detected via the GitHub API.

2. A Docker image (`swesmith.x86_64.<repo>.<commit>`) which contains the installed codebase.

!!! note "`create_images` arguments"

    By default, without `-r`, the command will build images for *all* SWE-smith repositories (300+ as of 12/2025).
    
    `-r`: Select specific repositories to build using fuzzy matching (e.g., `-r django` matches any repo containing "django").
    
    `-f`: Force rebuild images even if they already exist locally.

    `--user`: GitHub personal account to create mirrors under.

    `--org`: GitHub organization to create mirrors under.

It's good practice to check that your Docker image works as expected.
```bash
docker run -it --rm swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6
```
Within the container, run the testing suite (e.g. `pytest`) to ensure that the codebase is functioning as expected.

!!! note "Get existing Docker images"

    All repositories represented in the SWE-smith [dataset](https://huggingface.co/datasets/SWE-bench/SWE-smith) are available to download. Simply run:
    ```bash
    python -m swesmith.build_repo.download_images
    ```
