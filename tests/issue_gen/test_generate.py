"""Tests for swesmith.issue_gen.generate — focused on the messages reuse bug fix."""

import json

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_completion_response(content="Generated issue text"):
    """Return a mock that looks like a litellm completion response."""
    choice = SimpleNamespace(message=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice])


@patch("swesmith.issue_gen.generate.LOG_DIR_ISSUE_GEN")
@patch("swesmith.issue_gen.generate.completion")
@patch("swesmith.issue_gen.generate.completion_cost", return_value=0.01)
def test_generate_issue_reuses_existing_messages(
    mock_cost, mock_completion, mock_log_dir, tmp_path
):
    """When a previous run already wrote messages to the output JSON, the code
    must assign the local `messages` variable from metadata so the completion()
    call doesn't crash with UnboundLocalError."""
    from swesmith.issue_gen.generate import IssueGen

    # Build a minimal IssueGen bypassing __init__ (avoids HF download)
    ig = object.__new__(IssueGen)
    ig.model = "test-model"
    ig.n_instructions = 1
    ig.config = {
        "system": "sys", "demonstration": None,
        "instance": "{{patch}}", "parameters": {},
    }

    saved_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Describe the bug"},
    ]

    # Write pre-existing metadata (simulates a previous interrupted run)
    repo_dir = tmp_path / "Owner__Repo.abc12345"
    repo_dir.mkdir()
    output_file = repo_dir / "Owner__Repo.abc12345.method__xyz.json"
    output_file.write_text(json.dumps({"messages": saved_messages, "repos_to_remove": []}))

    mock_log_dir.__truediv__ = lambda self, key: tmp_path / key
    mock_completion.return_value = _mock_completion_response()
    ig.get_test_functions = MagicMock(return_value=(["def test(): pass"], []))

    result = ig.generate_issue({
        "instance_id": "Owner__Repo.abc12345.method__xyz",
        "repo": "org/Owner__Repo.abc12345",
        "patch": "diff",
        "FAIL_TO_PASS": ["test.py::test_x"],
    })

    # The completion call must have received the saved messages (not crash)
    assert mock_completion.call_args.kwargs["messages"] == saved_messages
    assert result["status"] == "completed"
