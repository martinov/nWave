"""HooksRegisteredCheck — verifies all required hook types are in settings.json."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nwave_ai.common.check_result import CheckResult


if TYPE_CHECKING:
    from nwave_ai.doctor.context import DoctorContext


REQUIRED_HOOK_TYPES: tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "SubagentStop",
    "SessionStart",
    "SubagentStart",
)


class HooksRegisteredCheck:
    """Check that settings.json contains all 5 required hook type entries."""

    name: str = "hooks_registered"
    description: str = "All 5 required hook types are registered in settings.json"

    def run(self, context: DoctorContext) -> CheckResult:
        """Return passed=True when all required hook type keys are present.

        Args:
            context: Filesystem roots — reads context.settings_path.

        Returns:
            CheckResult listing any missing hook types in message.
        """
        if not context.settings_path.exists():
            return CheckResult(
                passed=False,
                error_code="SETTINGS_MISSING",
                message="settings.json not found",
                remediation="Run `nwave-ai install` to create the Claude settings file.",
            )

        try:
            data = json.loads(context.settings_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            return CheckResult(
                passed=False,
                error_code="SETTINGS_UNREADABLE",
                message=f"settings.json could not be parsed: {exc}",
                remediation="Inspect settings.json for syntax errors.",
            )

        registered = set(data.get("hooks", {}).keys())
        missing = [h for h in REQUIRED_HOOK_TYPES if h not in registered]

        if not missing:
            total = sum(
                len(data["hooks"].get(h, [])) for h in REQUIRED_HOOK_TYPES
            )
            return CheckResult(
                passed=True,
                error_code=None,
                message=(
                    f"All {len(REQUIRED_HOOK_TYPES)} hook types registered "
                    f"({total} total entries)"
                ),
                remediation=None,
            )

        missing_str = ", ".join(missing)
        return CheckResult(
            passed=False,
            error_code="HOOKS_MISSING",
            message=f"Missing hook types: {missing_str}",
            remediation="Run `nwave-ai install` to register the missing hook entries.",
        )
