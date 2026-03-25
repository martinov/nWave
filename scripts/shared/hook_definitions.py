"""Canonical DES hook definitions -- single source of truth.

Both the plugin builder (build_plugin.py) and the custom installer
(des_plugin.py) generate Claude Code hook configurations. This module
provides the shared definitions so hook events, matchers, and actions
are defined exactly once.

The two distribution paths differ only in HOW the Python command is
constructed (plugin uses CLAUDE_PLUGIN_ROOT, installer uses $HOME),
not in WHAT hooks are registered.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HookEvent:
    """A single DES hook event registration.

    Attributes:
        event: Claude Code hook event type (e.g., "PreToolUse").
        matcher: Optional matcher string (e.g., "Agent", "Write").
            None means the hook fires for all invocations of that event.
        action: DES adapter action string (e.g., "pre-task").
        is_guard: Whether this hook uses the shell fast-path guard
            (only for Write/Edit hooks that need to check for active
            deliver sessions before spawning Python).
        shell_command: Verbatim shell command string. When set,
            generate_hook_config uses this directly instead of
            command_fn or guard_command_fn. No Python handler needed.
    """

    event: str
    matcher: str | None
    action: str
    is_guard: bool = False
    shell_command: str | None = None


# Pure-shell guard for Bash commands that target execution-log.json.
# The "# des-hook:pre-bash;" prefix is a shell comment (no-op) that serves
# as a DES marker string for is_des_hook_entry detection.
_BASH_EXECUTION_LOG_GUARD = (
    "# des-hook:pre-bash\n"
    "INPUT=$(cat); "
    'CMD=$(echo "$INPUT" | python3 -c '
    '"import sys,json; print(json.load(sys.stdin)'
    ".get('tool_input',{}).get('command',''))\"); "
    "echo \"$CMD\" | grep -q 'execution-log' || exit 0; "
    'echo "$CMD" | grep -qE '
    "'des\\.cli\\.(log_phase|init_log|verify_deliver_integrity)' && exit 0; "
    'echo \'{"decision":"block","reason":"Direct modification of '
    "execution-log.json via Bash is blocked.\\n"
    "To read it, use the Read tool.\\n"
    "To modify it, use des.cli.log_phase.\"}'; "
    "exit 2"
)

# Canonical hook event definitions -- the ONLY place these are defined.
# Order matters: PreToolUse/Agent must come before Write/Edit guards.
HOOK_EVENTS: tuple[HookEvent, ...] = (
    HookEvent(event="PreToolUse", matcher="Agent", action="pre-task"),
    HookEvent(event="PreToolUse", matcher="Write", action="pre-write", is_guard=True),
    HookEvent(event="PreToolUse", matcher="Edit", action="pre-edit", is_guard=True),
    HookEvent(
        event="PreToolUse",
        matcher="Bash",
        action="pre-bash",
        shell_command=_BASH_EXECUTION_LOG_GUARD,
    ),
    HookEvent(event="PostToolUse", matcher="Agent", action="post-tool-use"),
    HookEvent(event="SubagentStop", matcher=None, action="subagent-stop"),
    HookEvent(event="SubagentStop", matcher=None, action="deliver-progress"),
    HookEvent(event="SessionStart", matcher="startup", action="session-start"),
    HookEvent(event="SubagentStart", matcher=None, action="subagent-start"),
)

# The distinct event types DES registers (for validation).
HOOK_EVENT_TYPES: frozenset[str] = frozenset(h.event for h in HOOK_EVENTS)


def generate_hook_config(
    command_fn: callable,
    guard_command_fn: callable | None = None,
) -> dict[str, list[dict]]:
    """Generate hooks config in Claude Code hooks.json format.

    Args:
        command_fn: Callable(action: str) -> str that produces the
            hook command string for a given action. Each distribution
            path provides its own (plugin vs installer paths).
        guard_command_fn: Optional callable(action: str) -> str for
            Write/Edit guard hooks that use shell fast-path. If None,
            guard hooks use command_fn instead (no fast-path).

    Returns:
        Dict mapping event names to lists of hook entries, matching
        the Claude Code hooks.json schema:
        {"EventName": [{"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}]}
    """
    config: dict[str, list[dict]] = {}

    for hook_event in HOOK_EVENTS:
        if hook_event.shell_command is not None:
            command = hook_event.shell_command
        elif hook_event.is_guard and guard_command_fn is not None:
            command = guard_command_fn(hook_event.action)
        else:
            command = command_fn(hook_event.action)

        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if hook_event.matcher is not None:
            entry["matcher"] = hook_event.matcher

        config.setdefault(hook_event.event, []).append(entry)

    return config


def build_guard_command(python_cmd: str) -> str:
    """Build the shell fast-path guard command template for Write/Edit hooks.

    The guard:
    1. Buffers stdin (hook input JSON)
    2. If the target is execution-log.json, always invokes Python (unconditional)
    3. Otherwise, checks for deliver-session.json -- exits 0 if absent (fast path)
    4. If present, invokes Python for full DES enforcement

    Args:
        python_cmd: The full Python command string (PYTHONPATH=... python3 -m ...)
            WITHOUT the action suffix. The action will be appended by the caller.

    Returns:
        Shell command template string. The caller must format it with the action.
    """
    return (  # noqa: UP032 — .format() required for shell template with literal braces
        "INPUT=$(cat); "
        "echo \"$INPUT\" | grep -q 'execution-log\\.json' && "
        '{{ echo "$INPUT" | {python_cmd}; exit $?; }}; '
        "test -f .nwave/des/deliver-session.json || exit 0; "
        'echo "$INPUT" | {python_cmd}'
    ).format(python_cmd=python_cmd)


def _is_des_command(command: str) -> bool:
    """Check if a command string belongs to DES.

    Detects:
    - Python-based hooks via module name (claude_code_hook_adapter)
    - Python-based hooks via module path (des.adapters.drivers.hooks)
    - Shell-based hooks via marker prefix (# des-hook:)

    Multiple markers provide defense-in-depth: if the adapter module is
    renamed or the command format changes between versions, at least one
    marker should still match, preventing duplicate hooks on upgrade.
    """
    return (
        "claude_code_hook_adapter" in command
        or "des-hook:" in command
        or "des.adapters.drivers.hooks" in command
    )


def is_des_hook_entry(hook_entry: dict) -> bool:
    """Check if a hook entry is a DES hook.

    Supports old flat format, new nested format, and shell-based hooks:
    - Old flat: {"command": "...claude_code_hook_adapter..."}
    - New nested: {"hooks": [{"type": "command", "command": "...claude_code_hook_adapter..."}]}
    - Shell-based: {"hooks": [{"type": "command", "command": "# des-hook:pre-bash; ..."}]}

    Args:
        hook_entry: Hook entry dictionary from settings JSON.

    Returns:
        True if entry is a DES hook.
    """
    # Check old flat format
    if _is_des_command(hook_entry.get("command", "")):
        return True
    # Check new nested format
    for h in hook_entry.get("hooks", []):
        if _is_des_command(h.get("command", "")):
            return True
    return False
