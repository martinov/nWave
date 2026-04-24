"""Acceptance tests for ShimsDeployedCheck.

Tests enter through the check's run() driving port.
Pass path: all 5 des-* shim files exist and are executable under claude_dir/bin/.
Fail path: bin/ absent or one or more shims missing/not executable.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest
from nwave_ai.doctor.checks.shims_deployed import ShimsDeployedCheck
from nwave_ai.doctor.context import DoctorContext


if TYPE_CHECKING:
    from pathlib import Path


EXPECTED_SHIMS = [
    "des-log-phase",
    "des-init-log",
    "des-verify-integrity",
    "des-roadmap",
    "des-health-check",
]


@pytest.fixture()
def context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(home_dir=tmp_path)


def _make_executable_shim(path: Path) -> None:
    path.write_text("#!/usr/bin/env python3\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_passes_when_all_shims_present_and_executable(context: DoctorContext) -> None:
    """run() returns passed=True when all 5 shims exist and are executable."""
    bin_dir = context.claude_dir / "bin"
    bin_dir.mkdir(parents=True)
    for shim in EXPECTED_SHIMS:
        _make_executable_shim(bin_dir / shim)

    check = ShimsDeployedCheck()
    result = check.run(context)
    assert result.passed is True
    for shim in EXPECTED_SHIMS:
        assert shim in result.message


def test_fails_when_bin_dir_absent(context: DoctorContext) -> None:
    """run() returns passed=False (no exception) when bin/ does not exist."""
    check = ShimsDeployedCheck()
    result = check.run(context)
    assert result.passed is False
    assert result.remediation is not None


def test_fails_when_shim_not_executable(context: DoctorContext) -> None:
    """run() returns passed=False when a shim file exists but is not executable."""
    bin_dir = context.claude_dir / "bin"
    bin_dir.mkdir(parents=True)
    for shim in EXPECTED_SHIMS:
        _make_executable_shim(bin_dir / shim)
    # Remove executable bit from one shim
    non_exec = bin_dir / EXPECTED_SHIMS[0]
    non_exec.chmod(
        non_exec.stat().st_mode & ~(stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    )

    check = ShimsDeployedCheck()
    result = check.run(context)
    assert result.passed is False
    assert EXPECTED_SHIMS[0] in result.message
