"""PipxPackageManagerAdapter - real pipx-backed PackageManagerPort implementation.

Two-phase upgrade model:

1. ``<pipx> upgrade nwave-ai`` - delegates version selection to pipx (it
   always upgrades to the latest version satisfying any existing pins).
2. ``nwave-ai install`` - re-runs the nWave installer so framework assets
   (agents, skills, commands) track the newly installed package version.

Failures are reported via ``UpgradeResult.phase`` as ``"pm_upgrade"`` or
``"nwave_install"`` so the caller can tailor remediation.
"""

from __future__ import annotations

import shutil
import subprocess

from des.ports.driven_ports.package_manager_port import UpgradeResult


_UPGRADE_TIMEOUT_SECONDS = 120
_PACKAGE_NAME = "nwave-ai"


class PipxPackageManagerAdapter:
    """PackageManagerPort adapter that shells out to pipx."""

    def upgrade(self, pm_binary_abspath: str, target_version: str) -> UpgradeResult:
        pm_result = self._run_pipx_upgrade(pm_binary_abspath)
        if pm_result is not None:
            return pm_result
        return self._run_nwave_install()

    def _run_pipx_upgrade(self, pm_binary_abspath: str) -> UpgradeResult | None:
        """Run ``pipx upgrade nwave-ai``; return failure result or None on success."""
        cmd = [pm_binary_abspath, "upgrade", _PACKAGE_NAME]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_UPGRADE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return UpgradeResult(
                success=False,
                error=f"timeout after {_UPGRADE_TIMEOUT_SECONDS}s running pipx upgrade",
                phase="pm_upgrade",
            )
        except FileNotFoundError:
            return UpgradeResult(
                success=False,
                error=f"binary not found: {pm_binary_abspath}",
                phase="pm_upgrade",
            )
        except OSError as exc:
            return UpgradeResult(
                success=False,
                error=f"pipx upgrade failed: {exc}",
                phase="pm_upgrade",
            )

        if completed.returncode != 0:
            return UpgradeResult(
                success=False,
                error=completed.stderr or completed.stdout or "pipx upgrade failed",
                phase="pm_upgrade",
            )
        return None

    def _run_nwave_install(self) -> UpgradeResult:
        """Run the freshly upgraded ``nwave-ai install`` binary."""
        nwave_ai_path = shutil.which(_PACKAGE_NAME)
        if nwave_ai_path is None:
            return UpgradeResult(
                success=False,
                error=f"binary not found: {_PACKAGE_NAME}",
                phase="nwave_install",
            )

        cmd = [nwave_ai_path, "install"]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_UPGRADE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return UpgradeResult(
                success=False,
                error=f"timeout after {_UPGRADE_TIMEOUT_SECONDS}s running nwave-ai install",
                phase="nwave_install",
            )
        except FileNotFoundError:
            return UpgradeResult(
                success=False,
                error=f"binary not found: {nwave_ai_path}",
                phase="nwave_install",
            )
        except OSError as exc:
            return UpgradeResult(
                success=False,
                error=f"nwave-ai install failed: {exc}",
                phase="nwave_install",
            )

        if completed.returncode != 0:
            return UpgradeResult(
                success=False,
                error=completed.stderr or completed.stdout or "nwave-ai install failed",
                phase="nwave_install",
            )
        return UpgradeResult(success=True, error=None)
