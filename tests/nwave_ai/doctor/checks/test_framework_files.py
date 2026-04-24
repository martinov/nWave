"""Acceptance tests for FrameworkFilesCheck.

Tests enter through the check's run() driving port.
Pass path: agents/, skills/, commands/ all exist and contain at least 1 file each.
Fail path: one or more directories absent or empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nwave_ai.doctor.checks.framework_files import FrameworkFilesCheck
from nwave_ai.doctor.context import DoctorContext


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(home_dir=tmp_path)


def _populate_framework_dirs(context: DoctorContext) -> None:
    for subdir in ("agents", "skills", "commands"):
        d = context.claude_dir / subdir
        d.mkdir(parents=True)
        (d / "example.md").write_text("# stub\n")


def test_passes_when_all_dirs_populated(context: DoctorContext) -> None:
    """run() returns passed=True when agents/, skills/, commands/ each have >= 1 file."""
    _populate_framework_dirs(context)

    check = FrameworkFilesCheck()
    result = check.run(context)
    assert result.passed is True
    # Message should mention file counts
    assert "agents" in result.message
    assert "skills" in result.message
    assert "commands" in result.message


def test_fails_when_directory_absent(context: DoctorContext) -> None:
    """run() returns passed=False when one of the required directories is missing."""
    # Create agents and skills but not commands
    for subdir in ("agents", "skills"):
        d = context.claude_dir / subdir
        d.mkdir(parents=True)
        (d / "file.md").write_text("# stub\n")

    check = FrameworkFilesCheck()
    result = check.run(context)
    assert result.passed is False
    assert result.remediation is not None


def test_fails_when_directory_empty(context: DoctorContext) -> None:
    """run() returns passed=False when a required directory is empty."""
    for subdir in ("agents", "skills", "commands"):
        (context.claude_dir / subdir).mkdir(parents=True)
    # agents is empty — add files only to skills and commands
    (context.claude_dir / "skills" / "file.md").write_text("# stub\n")
    (context.claude_dir / "commands" / "file.md").write_text("# stub\n")

    check = FrameworkFilesCheck()
    result = check.run(context)
    assert result.passed is False
    assert "agents" in result.message


def test_passes_with_realistic_install_layout(context: DoctorContext) -> None:
    """run() passes when files are nested in subdirectories (real install layout).

    Real install has agents/nw/*.md, skills/*/SKILL.md, commands/*.md.
    The previous is_file() on direct children fails for skills/ and agents/nw/.
    """
    # agents/nw/nw-foo.md (nested)
    agents_nw = context.claude_dir / "agents" / "nw"
    agents_nw.mkdir(parents=True)
    (agents_nw / "nw-foo.md").write_text("# agent\n")

    # skills/nw-bar/SKILL.md (directory per skill)
    skill_dir = context.claude_dir / "skills" / "nw-bar"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# skill\n")

    # commands/nw-baz.md (direct file)
    commands_dir = context.claude_dir / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "nw-baz.md").write_text("# command\n")

    check = FrameworkFilesCheck()
    result = check.run(context)
    assert result.passed is True, (
        f"Expected PASS with real layout, got: {result.message}"
    )


def test_fails_when_directory_contains_only_backup_files(
    context: DoctorContext,
) -> None:
    """run() fails when a directory contains only *.md.bak files (no real .md files)."""
    (context.claude_dir / "agents").mkdir(parents=True)
    (context.claude_dir / "agents" / "nw-foo.md").write_text("# agent\n")

    (context.claude_dir / "skills").mkdir(parents=True)
    (context.claude_dir / "skills" / "nw-bar.md.bak").write_text("# backup\n")

    (context.claude_dir / "commands").mkdir(parents=True)
    (context.claude_dir / "commands" / "nw-baz.md").write_text("# command\n")

    check = FrameworkFilesCheck()
    result = check.run(context)
    assert result.passed is False, (
        f"Expected FAIL when skills/ has only .md.bak, got: {result.message}"
    )
    assert "skills" in result.message
