"""RED regression tests for the git-pollution detective guard fixture.

Background
----------
On 2026-04-27 a pre-push pytest run mutated host `.git/config`
(`core.bare=true`, `core.hooksPath=/dev/null`) and reset the worktree HEAD
to a synthetic test-fixture commit. RCA in
`docs/analysis/rca-test-git-pollution-2026-04-27.md` traced the leak to
subprocess git invocations from `cwd=tmp_path` without
`GIT_CEILING_DIRECTORIES`, combined with the autouse chdir back to
project_root.

Step 01-02 (separate dispatch) will install an autouse detective fixture in
`tests/conftest.py` that snapshots `.git/config`, the resolved HEAD path,
and `.git/refs/{heads,tags}` before each test, diffs the snapshot
afterwards, and calls `pytest.fail()` naming the corruption type ("config",
"HEAD", "refs/") if pollution is detected.

This file is the self-validation harness for that guard. It MUST fail today
because the guard's pure-function seams do not yet exist in
`tests.conftest`. The expected RED failure is `ImportError` on the imports
below.

Once Step 01-02 is implemented, these tests must turn GREEN by exercising
the guard's diff over the EXACT subprocess pollution path that caused the
incident: real `git config core.hooksPath /dev/null` and real `git commit`
against a real on-disk repo, with NO mocks.

Design notes
------------
- The pollution `subprocess.run` deliberately omits `GIT_CEILING_DIRECTORIES`
  from its env, faithfully reproducing the failure mode. Containment comes
  from the fact that `tmp_path` itself contains a freshly-initialized
  `.git`; git's walk-up resolves to that directly without crossing into the
  host repo. The bug-victim path is the same shape; what differs is the
  presence of a closer `.git` to absorb the write.
- The driving port for the guard is the pair of pure functions
  `_compute_git_state_snapshot` and `_diff_git_state`. Testing them
  port-to-port at domain scope IS the correct port-to-port unit-testing
  pattern for the detective guard's domain logic.
- We snapshot before mutation, perform the real subprocess pollution,
  snapshot after, and assert that the diff reports the expected target
  name. The assertion mirrors what the autouse fixture in 01-02 will do
  inline (diff -> pytest.fail).
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

# Import the pure-function seams the detective guard will expose.
# These do not exist yet — that is the RED gate. Step 01-02 introduces them
# in tests/conftest.py.
from tests.conftest import (  # type: ignore[attr-defined]
    _atomic_restore_git_state,
    _compute_git_state_snapshot,
    _diff_git_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_isolated_repo(repo_root: Path) -> None:
    """Initialize a fresh git repo inside `repo_root`.

    Sets `GIT_CEILING_DIRECTORIES` for THIS call so the setup itself cannot
    escape `repo_root`. The pollution subprocess call later in the test
    deliberately does NOT set this env var — that is the failure-mode
    reproduction.
    """
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(repo_root.parent)}
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_root)],
        check=True,
        capture_output=True,
        env=env,
    )
    # Minimum identity so commits can be created.
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(
            ["git", "-C", str(repo_root), "config", key, value],
            check=True,
            capture_output=True,
            env=env,
        )


def _create_initial_commit(repo_root: Path) -> None:
    """Create one commit so HEAD points at a real ref."""
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(repo_root.parent)}
    (repo_root / "seed.txt").write_text("seed\n")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "seed.txt"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "seed"],
        check=True,
        capture_output=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_guard_detects_config_corruption(tmp_path: Path) -> None:
    """Real `git config core.hooksPath /dev/null` mutates `.git/config`.

    Reproduces the EXACT subprocess pollution path observed at
    `tests/release/test_cz_integration.py:66` and witnessed in the master
    worktree's mutated config on 2026-04-27. The diff predicate must report
    `"config"` so the autouse fixture in 01-02 can name the corruption type
    in its `pytest.fail()` message.
    """
    repo_root = tmp_path / "victim_repo"
    repo_root.mkdir()
    _init_isolated_repo(repo_root)

    before = _compute_git_state_snapshot(repo_root)

    # Real failure-mode reproduction: NO GIT_CEILING_DIRECTORIES in env.
    # cwd=repo_root contains a fresh .git so the walk-up resolves there
    # immediately — same shape as the incident, contained target.
    subprocess.run(
        ["git", "config", "core.hooksPath", "/dev/null"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )

    after = _compute_git_state_snapshot(repo_root)

    diff = _diff_git_state(before, after)
    assert "config" in diff, (
        f"Detective guard predicate failed to detect config corruption; "
        f"diff returned {diff!r}. Expected 'config' so the autouse fixture "
        f"can call pytest.fail() naming the corruption type."
    )


def test_guard_detects_head_corruption(tmp_path: Path) -> None:
    """Real `git commit` advances HEAD; the guard must report `"HEAD"`.

    Reproduces the Branch A failure mode from the RCA: a test commit
    landed in the host worktree's HEAD because subprocess git escaped
    `tmp_path`. Here we contain the commit inside `tmp_path/victim_repo`
    so the test is safe, but the diff predicate must still flag HEAD
    movement as corruption.
    """
    repo_root = tmp_path / "victim_repo"
    repo_root.mkdir()
    _init_isolated_repo(repo_root)
    _create_initial_commit(repo_root)

    before = _compute_git_state_snapshot(repo_root)

    # Real failure-mode reproduction: subprocess `git commit` with NO
    # GIT_CEILING_DIRECTORIES. Containment is structural (tmp_path has its
    # own .git), faithfulness to the bug is preserved (no env guard).
    (repo_root / "polluting.txt").write_text("would have hit host\n")
    subprocess.run(
        ["git", "add", "polluting.txt"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: something"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )

    after = _compute_git_state_snapshot(repo_root)

    diff = _diff_git_state(before, after)
    assert "HEAD" in diff, (
        f"Detective guard predicate failed to detect HEAD corruption; "
        f"diff returned {diff!r}. Expected 'HEAD' so the autouse fixture "
        f"can name the corruption type when a test escapes its tmp_path "
        f"and lands a commit on the host worktree."
    )


# ---------------------------------------------------------------------------
# Tests added in fixup pass for adversarial review findings (D1, D2, D3).
# ---------------------------------------------------------------------------


def test_guard_detects_refs_corruption(tmp_path: Path) -> None:
    """Real `git tag` creates a new ref; the guard must report `"refs"`.

    Adversarial review D3(a): the refs snapshot branch of
    `_compute_git_state_snapshot` (the rglob over refs/heads + refs/tags)
    had no test coverage. Real `git tag` writes a new file under
    refs/tags/<name>, and the diff predicate must flag this as `"refs"`
    so the autouse fixture surfaces the corruption type.

    Together with the head- and config-corruption tests, this test now
    covers all three branches of the snapshot dict ("config", "HEAD",
    "refs").
    """
    repo_root = tmp_path / "victim_repo"
    repo_root.mkdir()
    _init_isolated_repo(repo_root)
    _create_initial_commit(repo_root)

    before = _compute_git_state_snapshot(repo_root)

    # Real failure-mode reproduction: subprocess git creates a new ref.
    # `git tag` writes refs/tags/v0.1.0 directly; identical shape to the
    # pollution path that would create refs/heads/<spurious-branch> in
    # the host repo if a test escaped its tmp_path.
    subprocess.run(
        ["git", "-C", str(repo_root), "tag", "v0.1.0"],
        check=True,
        capture_output=True,
    )

    after = _compute_git_state_snapshot(repo_root)

    diff = _diff_git_state(before, after)
    assert "refs" in diff, (
        f"Detective guard predicate failed to detect refs corruption; "
        f"diff returned {diff!r}. Expected 'refs' so the autouse fixture "
        f"can name the corruption type when a test creates a stray ref "
        f"under refs/heads/ or refs/tags/."
    )


def test_guard_restore_deletes_created_refs(tmp_path: Path) -> None:
    """Restore must DELETE refs created during the test, not just write back snapshot entries.

    Adversarial review D2: the original `_atomic_restore_git_state` only
    wrote snapshot-before entries back to disk. Refs CREATED during the
    test (e.g., a stray `refs/heads/foo` or `refs/tags/v0.1.0`) survived
    restore — only their bytes-before-test would be missing, but the new
    file was untouched. This test exercises the full snapshot -> mutate
    -> restore -> snapshot loop and asserts the diff is empty after
    restore.

    Mirrors `_restore_hooks_dir`'s deletion-pass pattern (lines 96-99).
    Failing today proves the deletion pass is necessary; passing after
    the D2 fix proves the deletion pass is correct.
    """
    repo_root = tmp_path / "victim_repo"
    repo_root.mkdir()
    _init_isolated_repo(repo_root)
    _create_initial_commit(repo_root)

    before = _compute_git_state_snapshot(repo_root)

    # Pollute: create a tag that did not exist in `before`.
    subprocess.run(
        ["git", "-C", str(repo_root), "tag", "stray-tag"],
        check=True,
        capture_output=True,
    )

    # Sanity check: before the restore, the diff must be non-empty.
    polluted = _compute_git_state_snapshot(repo_root)
    assert _diff_git_state(before, polluted) == ["refs"], (
        "Setup failure: pollution did not produce the expected refs diff."
    )

    # Restore from `before` snapshot.
    _atomic_restore_git_state(repo_root, before)

    # The restore must have deleted refs/tags/stray-tag — not just
    # written back the absent entry. Snapshot equality is the contract.
    after_restore = _compute_git_state_snapshot(repo_root)
    diff = _diff_git_state(before, after_restore)
    assert diff == [], (
        f"Restore left ref pollution behind; diff after restore: {diff!r}. "
        f"Adversarial review D2: restore must mirror _restore_hooks_dir "
        f"and delete refs that were not present in the snapshot-before."
    )

    # Belt-and-braces: assert the stray tag file is actually gone on disk.
    stray_path = repo_root / ".git" / "refs" / "tags" / "stray-tag"
    assert not stray_path.exists(), (
        f"Restore wrote back snapshot entries but did NOT delete the "
        f"newly-created ref at {stray_path}."
    )


def test_guard_restore_preserves_symbolic_head(tmp_path: Path) -> None:
    """Restore must preserve the symbolic-ref form of HEAD, not write a raw SHA.

    Adversarial review D1: the original snapshot stored the RESOLVED
    target of HEAD (the commit SHA from refs/heads/<branch>) in the
    `"HEAD"` key, and the restore wrote those bytes back to the HEAD
    file. This left the worktree in detached-HEAD state because HEAD
    originally contained `ref: refs/heads/<branch>\\n`, not the SHA.

    The fix splits HEAD into `HEAD_raw` (the literal HEAD file bytes,
    used for restore) and `HEAD_resolved` (the resolved SHA, used for
    diff). This test asserts the restore writes the symbolic-ref TEXT
    back, so the worktree remains attached to its branch.

    Failing today: the restore writes the SHA. Passing after D1 fix:
    the restore writes `ref: refs/heads/main\\n`.
    """
    repo_root = tmp_path / "victim_repo"
    repo_root.mkdir()
    _init_isolated_repo(repo_root)
    _create_initial_commit(repo_root)

    head_path = repo_root / ".git" / "HEAD"
    original_head_text = head_path.read_text()
    # Sanity: confirm we start from a symbolic-ref HEAD on `main`.
    assert original_head_text.startswith("ref: refs/heads/main"), (
        f"Setup failure: expected symbolic-ref HEAD, got {original_head_text!r}."
    )

    before = _compute_git_state_snapshot(repo_root)

    # Pollute HEAD: simulate a test that detached HEAD by writing a raw
    # SHA. Equivalent in shape to `git checkout <sha>`.
    seed_sha = (repo_root / ".git" / "refs" / "heads" / "main").read_text().strip()
    head_path.write_text(seed_sha + "\n")

    # Restore from snapshot.
    _atomic_restore_git_state(repo_root, before)

    # The restored HEAD must contain the symbolic-ref TEXT, not the SHA.
    restored_head_text = head_path.read_text()
    assert restored_head_text == original_head_text, (
        f"Restore corrupted HEAD: expected symbolic-ref text "
        f"{original_head_text!r}, got {restored_head_text!r}. "
        f"Adversarial review D1: restore must write HEAD_raw (the literal "
        f"file bytes), not HEAD_resolved (the SHA target)."
    )
    # Belt-and-braces: explicitly check we did NOT leave HEAD detached.
    assert restored_head_text.startswith("ref:"), (
        f"Restore left HEAD detached; HEAD now reads {restored_head_text!r}. "
        f"Worktree should remain attached to refs/heads/main."
    )
