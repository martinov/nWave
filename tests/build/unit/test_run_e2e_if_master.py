"""Tests for the branch-conditional e2e pre-push wrapper.

The wrapper at ``scripts/hooks/run_e2e_if_master.py`` gates the e2e test
hook on the current branch: only ``master`` invokes the full e2e suite
locally on pre-push (developers push feature branches frequently and the
~10-15 min e2e cost would dominate; e2e is run in CI on every PR).

Decision (Ale 2026-04-28, RCA #31.2): e2e tests in pre-push only when
on ``master`` branch. Feature branches -> CI-only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


WRAPPER_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "hooks" / "run_e2e_if_master.py"
)


def _load_wrapper_module():
    """Load the wrapper script as a module, fail clearly if absent."""
    assert WRAPPER_PATH.is_file(), f"wrapper script missing at {WRAPPER_PATH}"
    spec = importlib.util.spec_from_file_location(
        "run_e2e_if_master_under_test", WRAPPER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wrapper():
    """Load the wrapper module fresh for each test (clean monkeypatched state)."""
    return _load_wrapper_module()


def test_on_master_invokes_pytest(wrapper) -> None:
    """When the current branch is ``master``, the wrapper invokes pytest."""
    with (
        patch.object(wrapper, "_current_branch", return_value="master"),
        patch.object(wrapper.subprocess, "run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        exit_code = wrapper.main([])

    assert exit_code == 0
    assert mock_run.call_count == 1, "pytest must be invoked exactly once on master"
    cmd = mock_run.call_args.args[0]
    # Real pytest invocation: pipenv run pytest -m "e2e and e2e_smoke" ...
    # The pre-push gate runs only the smoke subset (4 critical-path files);
    # full e2e remains on CI per PR. See e2e_smoke marker in pyproject.toml.
    assert "pipenv" in cmd[0] or "pytest" in " ".join(cmd), (
        f"Expected pytest invocation, got: {cmd}"
    )
    assert "-m" in cmd, f"Expected ``-m`` selector, got: {cmd}"
    marker_expr = cmd[cmd.index("-m") + 1]
    assert "e2e" in marker_expr and "e2e_smoke" in marker_expr, (
        f"Expected ``e2e and e2e_smoke`` marker expression, got: {marker_expr!r}"
    )


def test_on_feature_branch_skips_pytest(wrapper) -> None:
    """On a feature branch, the wrapper exits 0 without invoking pytest."""
    with (
        patch.object(
            wrapper, "_current_branch", return_value="feat/test-suite-optimization"
        ),
        patch.object(wrapper.subprocess, "run") as mock_run,
    ):
        exit_code = wrapper.main([])

    assert exit_code == 0, "feature-branch path must exit 0 (skip)"
    assert mock_run.call_count == 0, "pytest must NOT be invoked on a non-master branch"


def test_git_error_propagates_nonzero_exit(wrapper) -> None:
    """If ``git branch --show-current`` fails, the wrapper exits non-zero.

    A failing git invocation could mean the worktree is in a bad state;
    silently treating that as "not master" would let buggy branches push
    without e2e validation. Better to fail loud.
    """
    with patch.object(
        wrapper, "_current_branch", side_effect=RuntimeError("git invocation failed")
    ):
        exit_code = wrapper.main([])

    assert exit_code != 0, "git error must propagate as non-zero exit code"
