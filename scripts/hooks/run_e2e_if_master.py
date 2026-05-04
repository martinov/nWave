#!/usr/bin/env python3
"""Branch-conditional e2e pre-push wrapper.

Invokes the e2e pytest suite only when the current branch is ``master``.
On feature branches the wrapper exits 0 immediately, deferring e2e to
CI on PR.

Decision (Ale 2026-04-28, RCA #31.2): e2e tests in pre-push only when
on ``master`` branch. Feature branches -> CI-only. The ~10-15 min e2e
cost dominates per-push wall-time on feature branches that are pushed
frequently; PR-level CI is the right enforcement point there.

If ``git branch --show-current`` fails, the wrapper propagates a
non-zero exit code rather than silently skipping — a broken worktree
should not be allowed to push without e2e validation.
"""

from __future__ import annotations

import subprocess
import sys


# Color codes (consistent with sibling scripts in scripts/hooks/).
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

# Branches that DO run e2e on pre-push. Master is the canonical target;
# release-train branches could be added here if release flows ever push
# without going through CI first.
E2E_PREPUSH_BRANCHES: frozenset[str] = frozenset({"master"})


def _current_branch() -> str:
    """Return the current branch name via ``git branch --show-current``.

    Raises:
        RuntimeError: if git invocation fails (broken worktree, missing
            git binary, etc.). Caller decides how to surface.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"git branch --show-current failed: {exc}") from exc
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    """Pre-push entry point. Returns exit code for the shell."""
    if argv is None:
        argv = sys.argv[1:]

    try:
        branch = _current_branch()
    except RuntimeError as exc:
        print(f"{RED}run_e2e_if_master: {exc}{NC}", file=sys.stderr)
        return 1

    if branch not in E2E_PREPUSH_BRANCHES:
        print(
            f"{YELLOW}run_e2e_if_master: branch={branch!r} is not in "
            f"{sorted(E2E_PREPUSH_BRANCHES)}, skipping e2e (CI will run on PR){NC}"
        )
        return 0

    print(
        f"{BLUE}run_e2e_if_master: branch={branch!r} matches gate, "
        f"invoking pytest -m 'e2e and e2e_smoke' (smoke subset)...{NC}"
    )
    # Pre-push runs only the e2e SMOKE subset (4 critical-path files).
    # Full e2e remains gated by CI on PR. Decision ref:
    # docs/analysis/test-perf-research-2026-05-03.md (#1 ROI).
    cmd = [
        "pipenv",
        "run",
        "pytest",
        "-m",
        "e2e and e2e_smoke",
        "-n",
        "auto",
        "--dist=loadfile",
        "--tb=short",
        "-q",
        *argv,
    ]
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
