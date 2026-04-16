"""Package manager detector - identifies which PM installed a Python executable.

Pure detection function + one subprocess probe. Used by `/nw-update` before
invoking PendingUpdateService.request_update() to record the correct PM backend
in the pending update flag.

Detection order:
1. `uv tool dir` prefix match (authoritative for uv)
2. `/pipx/venvs/` substring in executable path
3. Fallback: "unknown"
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal


PMBackend = Literal["pipx", "uv", "unknown"]


def _probe_uv_tool_dir() -> Path | None:
    """Return the directory reported by `uv tool dir`, or None on any failure."""
    try:
        output = subprocess.check_output(["uv", "tool", "dir"], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    stripped = output.strip()
    if not stripped:
        return None
    return Path(stripped)


def _is_under(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
    except ValueError:
        return False
    return True


def detect_pm(executable: Path) -> PMBackend:
    """Identify the package manager that installed ``executable``.

    Args:
        executable: absolute path to the Python interpreter of the installed package.

    Returns:
        "uv" if executable lives under ``uv tool dir``,
        "pipx" if the path contains ``/pipx/venvs/``,
        "unknown" otherwise.
    """
    uv_root = _probe_uv_tool_dir()
    if uv_root is not None and _is_under(executable, uv_root):
        return "uv"
    if "/pipx/venvs/" in str(executable):
        return "pipx"
    return "unknown"
