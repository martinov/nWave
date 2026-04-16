"""Unit tests for package_manager_detector.detect_pm.

Behaviors under test (3 distinct behaviors; budget = 6):
1. pipx path detection (substring match)
2. uv path detection (under `uv tool dir`)
3. unknown path fallback
   Plus tolerance: `uv` missing / `uv tool dir` failing degrades to fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from des.adapters.driven.package_managers.package_manager_detector import detect_pm


class TestDetectPm:
    def test_detects_pipx_when_path_contains_pipx_venvs(self) -> None:
        executable = Path("/home/user/.local/share/pipx/venvs/nwave-ai/bin/python")
        with patch(
            "des.adapters.driven.package_managers.package_manager_detector."
            "subprocess.check_output",
            return_value="/home/user/.local/share/uv/tools\n",
        ):
            assert detect_pm(executable) == "pipx"

    def test_detects_uv_when_executable_under_uv_tool_dir(self) -> None:
        uv_tool_dir = "/home/user/.local/share/uv/tools"
        executable = Path(f"{uv_tool_dir}/nwave-ai/bin/python")
        with patch(
            "des.adapters.driven.package_managers.package_manager_detector."
            "subprocess.check_output",
            return_value=f"{uv_tool_dir}\n",
        ):
            assert detect_pm(executable) == "uv"

    def test_returns_unknown_when_no_match(self) -> None:
        executable = Path("/usr/bin/python3")
        with patch(
            "des.adapters.driven.package_managers.package_manager_detector."
            "subprocess.check_output",
            return_value="/home/user/.local/share/uv/tools\n",
        ):
            assert detect_pm(executable) == "unknown"

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("uv not installed"),
            subprocess.CalledProcessError(1, ["uv", "tool", "dir"]),
        ],
    )
    def test_uv_probe_failure_falls_back_to_pipx_match(
        self, exc: BaseException
    ) -> None:
        executable = Path("/home/user/.local/share/pipx/venvs/nwave-ai/bin/python")
        with patch(
            "des.adapters.driven.package_managers.package_manager_detector."
            "subprocess.check_output",
            side_effect=exc,
        ):
            assert detect_pm(executable) == "pipx"

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("uv not installed"),
            subprocess.CalledProcessError(1, ["uv", "tool", "dir"]),
        ],
    )
    def test_uv_probe_failure_without_pipx_returns_unknown(
        self, exc: BaseException
    ) -> None:
        executable = Path("/usr/bin/python3")
        with patch(
            "des.adapters.driven.package_managers.package_manager_detector."
            "subprocess.check_output",
            side_effect=exc,
        ):
            assert detect_pm(executable) == "unknown"
