#!/usr/bin/env python3
"""OpenCode hook adapter with DES integration.

This adapter bridges OpenCode's plugin protocol to DES application services
(PreToolUseService, SubagentStopService, PostToolUseService).

Protocol-only: no business logic here. All decisions delegated to application layer.

OpenCode plugins communicate via subprocess: the TypeScript plugin calls this
adapter with JSON on stdin and reads JSON + exit code from stdout.

Commands:
  python3 -m src.des.adapters.drivers.hooks.opencode_hook_adapter pre-tool-use
  python3 -m src.des.adapters.drivers.hooks.opencode_hook_adapter stop
  python3 -m src.des.adapters.drivers.hooks.opencode_hook_adapter post-tool-use

Exit Codes:
  0 = allow/continue
  1 = fail-closed error (BLOCKS execution)
  2 = block/reject (validation failed)

Protocol Differences from Claude Code:
  - OpenCode sends tool.execute.before with {tool, args, sessionID}
  - Claude Code sends PreToolUse with {tool_name, tool_input, ...}
  - OpenCode's "stop" hook fires on session idle, not per-subagent
  - Transcript paths and DES context extraction differ

Architecture:
  OpenCode Plugin (TypeScript)  →  subprocess  →  This Adapter  →  Application Services
  Claude Code Hook (settings)   →  subprocess  →  Claude Adapter →  Application Services
                                                                          ↓
                                                                    Domain Policies
"""

import contextlib
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path


# Add project root to sys.path for standalone script execution
if __name__ == "__main__":
    project_root = str(Path(__file__).resolve().parent.parent.parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from des.adapters.driven.logging.jsonl_audit_log_writer import JsonlAuditLogWriter
from des.adapters.driven.time.system_time import SystemTimeProvider
from des.ports.driven_ports.audit_log_writer import AuditEvent, AuditLogWriter

# Re-use service factories from the Claude Code adapter to avoid duplication.
# Both adapters create the same application services with the same dependencies.
from des.adapters.drivers.hooks.claude_code_hook_adapter import (
    create_pre_tool_use_service,
    create_subagent_stop_service,
)
from des.ports.driver_ports.pre_tool_use_port import PreToolUseInput


def _create_audit_writer() -> AuditLogWriter:
    """Create appropriate AuditLogWriter based on DES configuration."""
    from des.adapters.driven.config.des_config import DESConfig
    from des.adapters.driven.logging.null_audit_log_writer import NullAuditLogWriter

    config = DESConfig()
    if not config.audit_logging_enabled:
        return NullAuditLogWriter()
    return JsonlAuditLogWriter()


# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

_SLOW_HOOK_THRESHOLD_MS = 5000.0
_STDERR_CAPTURE_MAX_CHARS = 1000

_EXIT_CODE_TO_DECISION = {
    0: "allow",
    1: "error",
    2: "block",
}


# ---------------------------------------------------------------------------
# Audit logging helpers (mirrors Claude Code adapter, tagged for OpenCode)
# ---------------------------------------------------------------------------


def _log_hook_invoked(
    handler: str, summary: dict | None = None, hook_id: str | None = None
) -> None:
    """Log a HOOK_INVOKED diagnostic event at handler entry."""
    try:
        audit_writer = _create_audit_writer()
        data: dict = {"handler": handler, "driver": "opencode"}
        if hook_id is not None:
            data["hook_id"] = hook_id
        if summary:
            data["input_summary"] = summary
        audit_writer.log_event(
            AuditEvent(
                event_type="HOOK_INVOKED",
                timestamp=SystemTimeProvider().now_utc().isoformat(),
                data=data,
            )
        )
    except Exception:
        pass


def _log_hook_completed(
    hook_id: str,
    handler: str,
    exit_code: int,
    decision: str,
    duration_ms: float,
    task_correlation_id: str | None = None,
) -> None:
    """Log a HOOK_COMPLETED diagnostic event at handler exit."""
    try:
        audit_writer = _create_audit_writer()
        data: dict = {
            "hook_id": hook_id,
            "handler": handler,
            "driver": "opencode",
            "exit_code": exit_code,
            "decision": decision,
            "duration_ms": duration_ms,
        }
        if duration_ms > _SLOW_HOOK_THRESHOLD_MS:
            data["slow_hook"] = True
        if task_correlation_id is not None:
            data["task_correlation_id"] = task_correlation_id
        audit_writer.log_event(
            AuditEvent(
                event_type="HOOK_COMPLETED",
                timestamp=SystemTimeProvider().now_utc().isoformat(),
                data=data,
            )
        )
    except Exception:
        pass


def _log_hook_error(handler: str, error: Exception, stderr_capture: str) -> None:
    """Log a HOOK_ERROR audit event for unhandled exceptions."""
    try:
        audit_writer = _create_audit_writer()
        audit_writer.log_event(
            AuditEvent(
                event_type="HOOK_ERROR",
                timestamp=SystemTimeProvider().now_utc().isoformat(),
                data={
                    "error": str(error),
                    "handler": handler,
                    "driver": "opencode",
                    "error_type": type(error).__name__,
                    "stderr_capture": stderr_capture,
                },
            )
        )
    except Exception:
        pass


def _log_protocol_anomaly(
    handler: str, anomaly_type: str, detail: str, fallback_action: str
) -> None:
    """Log a HOOK_PROTOCOL_ANOMALY for early-return paths."""
    try:
        audit_writer = _create_audit_writer()
        audit_writer.log_event(
            AuditEvent(
                event_type="HOOK_PROTOCOL_ANOMALY",
                timestamp=SystemTimeProvider().now_utc().isoformat(),
                data={
                    "handler": handler,
                    "driver": "opencode",
                    "anomaly_type": anomaly_type,
                    "detail": detail,
                    "fallback_action": fallback_action,
                },
            )
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared stdin parsing
# ---------------------------------------------------------------------------


class _StdinParseResult:
    """Result of reading and parsing JSON from stdin."""

    __slots__ = ("hook_input", "is_empty", "parse_error")

    def __init__(
        self,
        hook_input: dict | None = None,
        is_empty: bool = False,
        parse_error: str | None = None,
    ) -> None:
        self.hook_input = hook_input
        self.is_empty = is_empty
        self.parse_error = parse_error

    @property
    def ok(self) -> bool:
        return self.hook_input is not None


def _read_and_parse_stdin(
    handler: str,
    json_error_fallback: str = "error",
) -> _StdinParseResult:
    """Read JSON from stdin with protocol anomaly logging."""
    input_data = sys.stdin.read()

    if not input_data or not input_data.strip():
        _log_protocol_anomaly(
            handler=handler,
            anomaly_type="empty_stdin",
            detail="No input data received on stdin",
            fallback_action="allow",
        )
        return _StdinParseResult(is_empty=True)

    try:
        hook_input = json.loads(input_data)
    except json.JSONDecodeError as e:
        _log_protocol_anomaly(
            handler=handler,
            anomaly_type="json_parse_error",
            detail=f"Invalid JSON: {e!s}",
            fallback_action=json_error_fallback,
        )
        return _StdinParseResult(parse_error=f"Invalid JSON: {e!s}")

    return _StdinParseResult(hook_input=hook_input)


# ---------------------------------------------------------------------------
# OpenCode → DES field translation
# ---------------------------------------------------------------------------


def _translate_pre_tool_use_input(hook_input: dict) -> dict:
    """Translate OpenCode tool.execute.before format to DES adapter format.

    OpenCode sends:
        {"tool": "Task", "args": {"prompt": "...", "max_turns": N, ...}, "sessionID": "..."}

    DES expects (via PreToolUseInput):
        prompt, max_turns, subagent_type

    Returns:
        dict with keys matching PreToolUseInput constructor args.
    """
    args = hook_input.get("args", {})
    return {
        "prompt": args.get("prompt", ""),
        "max_turns": args.get("max_turns") or args.get("maxTurns"),
        "subagent_type": args.get("subagent_type") or args.get("subagentType", ""),
    }


def _translate_stop_input(hook_input: dict) -> dict:
    """Translate OpenCode stop hook format to DES adapter format.

    OpenCode sends:
        {"sessionID": "...", "transcript_path": "...", ...}

    For DES validation, we need project_id, step_id, execution_log_path.
    These are extracted from the transcript just like in the Claude Code adapter.

    Returns:
        dict with keys matching SubagentStopContext constructor args.
    """
    return {
        "agent_transcript_path": hook_input.get("transcript_path", ""),
        "cwd": hook_input.get("cwd") or hook_input.get("directory", ""),
        "stop_hook_active": hook_input.get("stop_hook_active", False),
        "session_id": hook_input.get("sessionID") or hook_input.get("session_id", ""),
    }


# ---------------------------------------------------------------------------
# DES task signal file management (shared with Claude Code adapter)
# ---------------------------------------------------------------------------

DES_SESSION_DIR = Path(".nwave") / "des"
DES_TASK_ACTIVE_FILE = DES_SESSION_DIR / "des-task-active"


def _signal_file_for(project_id: str, step_id: str) -> Path:
    """Return the namespaced signal file path for a project/step pair."""
    safe_name = f"{project_id}--{step_id}".replace("/", "_")
    return DES_SESSION_DIR / f"des-task-active-{safe_name}"


def _create_des_task_signal(step_id: str = "", project_id: str = "") -> str:
    """Create DES task active signal file. Returns task_correlation_id."""
    task_correlation_id = str(uuid.uuid4())
    try:
        DES_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        signal = json.dumps(
            {
                "step_id": step_id,
                "project_id": project_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "task_correlation_id": task_correlation_id,
            }
        )
        signal_file = _signal_file_for(project_id, step_id)
        signal_file.write_text(signal)
        DES_TASK_ACTIVE_FILE.write_text(signal)
    except Exception:
        pass
    return task_correlation_id


def _read_des_task_signal(project_id: str = "", step_id: str = "") -> dict | None:
    """Read DES task active signal file before removal."""
    try:
        if project_id and step_id:
            namespaced = _signal_file_for(project_id, step_id)
            if namespaced.exists():
                return json.loads(namespaced.read_text())
        if DES_TASK_ACTIVE_FILE.exists():
            return json.loads(DES_TASK_ACTIVE_FILE.read_text())
    except Exception:
        pass
    return None


def _remove_des_task_signal(project_id: str = "", step_id: str = "") -> None:
    """Remove DES task active signal file(s)."""
    try:
        if project_id and step_id:
            namespaced = _signal_file_for(project_id, step_id)
            if namespaced.exists():
                namespaced.unlink()
        if DES_TASK_ACTIVE_FILE.exists():
            DES_TASK_ACTIVE_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Handler: PreToolUse (tool.execute.before → Task validation)
# ---------------------------------------------------------------------------


def handle_pre_tool_use() -> int:
    """Handle pre-tool-use: validate Task tool invocation.

    OpenCode plugin calls this before executing a Task-type tool.
    Translates OpenCode's {tool, args, sessionID} format to DES PreToolUseInput.

    Returns:
        0 if validation passes (allow)
        1 if error occurs (fail-closed)
        2 if validation fails (block)
    """
    hook_id = str(uuid.uuid4())
    start_ns = time.perf_counter_ns()
    exit_code = 0
    task_correlation_id: str | None = None
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_buffer):
            stdin_result = _read_and_parse_stdin("opencode_pre_tool_use")

            if stdin_result.is_empty:
                print(json.dumps({"decision": "allow"}))
                return 0

            if stdin_result.parse_error:
                response = {"status": "error", "reason": stdin_result.parse_error}
                print(json.dumps(response))
                exit_code = 1
                return exit_code

            hook_input = stdin_result.hook_input

            # Translate OpenCode format to DES fields
            translated = _translate_pre_tool_use_input(hook_input)

            _log_hook_invoked(
                "opencode_pre_tool_use",
                {
                    "tool": hook_input.get("tool"),
                    "subagent_type": translated.get("subagent_type"),
                    "has_max_turns": translated.get("max_turns") is not None,
                },
                hook_id=hook_id,
            )

            prompt = translated["prompt"]
            max_turns = translated["max_turns"]
            subagent_type = translated["subagent_type"]

            # Delegate to same application service as Claude Code adapter
            service = create_pre_tool_use_service()
            decision = service.validate(
                PreToolUseInput(
                    prompt=prompt,
                    max_turns=max_turns,
                    subagent_type=subagent_type,
                ),
                hook_id=hook_id,
            )

            if decision.action == "allow":
                # Create DES task signal for DES-validated tasks
                from des.domain.des_marker_parser import DesMarkerParser

                if "DES-VALIDATION" in prompt:
                    parser = DesMarkerParser()
                    markers = parser.parse(prompt)
                    step_id_marker = markers.step_id or ""
                    project_id_marker = markers.project_id or ""
                    task_correlation_id = _create_des_task_signal(
                        step_id=step_id_marker, project_id=project_id_marker
                    )
                response = {"decision": "allow"}
                print(json.dumps(response))
                exit_code = 0
                return exit_code
            else:
                recovery = decision.recovery_suggestions or []
                reason_with_recovery = decision.reason or "Validation failed"
                if recovery:
                    reason_with_recovery += "\n\nRecovery:\n" + "\n".join(
                        f"  {i + 1}. {s}" for i, s in enumerate(recovery)
                    )
                response = {
                    "decision": "block",
                    "reason": reason_with_recovery,
                }
                print(json.dumps(response))
                exit_code = decision.exit_code
                return exit_code

    except Exception as e:
        stderr_capture = stderr_buffer.getvalue()[:_STDERR_CAPTURE_MAX_CHARS]
        _log_hook_error("opencode_pre_tool_use", e, stderr_capture)
        response = {"status": "error", "reason": f"Unexpected error: {e!s}"}
        print(json.dumps(response))
        exit_code = 1
        return exit_code
    finally:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        decision_str = _EXIT_CODE_TO_DECISION.get(exit_code, "error")
        _log_hook_completed(
            hook_id=hook_id,
            handler="opencode_pre_tool_use",
            exit_code=exit_code,
            decision=decision_str,
            duration_ms=duration_ms,
            task_correlation_id=task_correlation_id,
        )


# ---------------------------------------------------------------------------
# Handler: Stop (session stop → step completion validation)
# ---------------------------------------------------------------------------


def handle_stop() -> int:
    """Handle stop: validate step completion when agent session ends.

    OpenCode's "stop" hook fires when the agent session becomes idle or completes.
    Unlike Claude Code's SubagentStop (which fires per-subagent), OpenCode's stop
    fires once per session. The adapter resolves DES context from the transcript.

    Returns:
        0 if gate passes or non-DES session
        1 if error occurs (fail-closed)
        2 if gate fails (BLOCKS completion)
    """
    hook_id = str(uuid.uuid4())
    start_ns = time.perf_counter_ns()
    exit_code = 0
    task_correlation_id: str | None = None
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_buffer):
            stdin_result = _read_and_parse_stdin("opencode_stop")

            if stdin_result.is_empty:
                print(json.dumps({"decision": "allow"}))
                return 0

            if stdin_result.parse_error:
                response = {"status": "error", "reason": stdin_result.parse_error}
                print(json.dumps(response))
                exit_code = 1
                return exit_code

            hook_input = stdin_result.hook_input

            # Translate OpenCode format
            translated = _translate_stop_input(hook_input)

            _log_hook_invoked(
                "opencode_stop",
                {
                    "session_id": translated.get("session_id"),
                    "has_transcript": bool(translated.get("agent_transcript_path")),
                },
                hook_id=hook_id,
            )

            # Extract DES context from transcript (same logic as Claude Code)
            from des.adapters.drivers.hooks.claude_code_hook_adapter import (
                extract_des_context_from_transcript,
            )

            agent_transcript_path = translated["agent_transcript_path"]
            cwd = translated["cwd"]

            des_context = None
            if agent_transcript_path:
                des_context = extract_des_context_from_transcript(
                    agent_transcript_path
                )

            if des_context is None:
                # Non-DES session — allow through
                print(json.dumps({"decision": "allow"}))
                return 0

            project_id = des_context["project_id"]
            step_id = des_context["step_id"]
            execution_log_path = os.path.join(
                cwd, "docs", "feature", project_id, "execution-log.yaml"
            )

            # Read task signal for correlation
            signal_data = _read_des_task_signal(
                project_id=project_id, step_id=step_id
            )
            task_start_time = ""
            if signal_data:
                task_start_time = signal_data.get("created_at", "")
                task_correlation_id = signal_data.get("task_correlation_id")

            _remove_des_task_signal(project_id=project_id, step_id=step_id)

            # Delegate to same SubagentStopService
            from des.ports.driver_ports.subagent_stop_port import SubagentStopContext

            stop_hook_active = translated["stop_hook_active"]
            service = create_subagent_stop_service()
            decision = service.validate(
                SubagentStopContext(
                    execution_log_path=execution_log_path,
                    project_id=project_id,
                    step_id=step_id,
                    stop_hook_active=stop_hook_active,
                    cwd=cwd,
                    task_start_time=task_start_time,
                ),
                hook_id=hook_id,
            )

            if decision.action == "allow":
                print(json.dumps({"decision": "allow"}))
                exit_code = 0
                return exit_code

            # Build block notification (same format as Claude Code adapter)
            reason = decision.reason or "Validation failed"
            recovery_suggestions = decision.recovery_suggestions or []
            recovery_steps = "\n".join(
                [f"  {i + 1}. {s}" for i, s in enumerate(recovery_suggestions)]
            )
            notification = (
                f"STOP HOOK VALIDATION FAILED\n\n"
                f"Step: {project_id}/{step_id}\n"
                f"Execution Log: {execution_log_path}\n"
                f"Status: FAILED\n"
                f"Error: {reason}\n\n"
                f"RECOVERY REQUIRED:\n{recovery_steps}"
            )
            response = {"decision": "block", "reason": notification}
            print(json.dumps(response))
            exit_code = 0  # Exit 0 so OpenCode processes the JSON
            return exit_code

    except Exception as e:
        stderr_capture = stderr_buffer.getvalue()[:_STDERR_CAPTURE_MAX_CHARS]
        _log_hook_error("opencode_stop", e, stderr_capture)
        print(f"OpenCode stop hook error: {e!s}", file=sys.stderr)
        exit_code = 1
        return exit_code
    finally:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        decision_str = _EXIT_CODE_TO_DECISION.get(exit_code, "error")
        _log_hook_completed(
            hook_id=hook_id,
            handler="opencode_stop",
            exit_code=exit_code,
            decision=decision_str,
            duration_ms=duration_ms,
            task_correlation_id=task_correlation_id,
        )


# ---------------------------------------------------------------------------
# Handler: PostToolUse (tool.execute.after → failure notification)
# ---------------------------------------------------------------------------


def handle_post_tool_use() -> int:
    """Handle post-tool-use: notify of sub-agent failures.

    OpenCode plugin calls this after a Task-type tool completes.
    Translates OpenCode's {tool, args, sessionID} to check completion status.

    Returns:
        0 always (PostToolUse should never block)
    """
    hook_id = str(uuid.uuid4())
    start_ns = time.perf_counter_ns()
    exit_code = 0
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_buffer):
            stdin_result = _read_and_parse_stdin(
                "opencode_post_tool_use", json_error_fallback="allow"
            )

            if stdin_result.is_empty:
                print(json.dumps({}))
                return 0

            if stdin_result.parse_error:
                print(json.dumps({}))
                return 0

            hook_input = stdin_result.hook_input

            # Translate OpenCode format
            args = hook_input.get("args", {})
            prompt = args.get("prompt", "")
            is_des_task = "DES-VALIDATION" in prompt

            _log_hook_invoked(
                "opencode_post_tool_use",
                {
                    "tool": hook_input.get("tool"),
                    "is_des_task": is_des_task,
                },
                hook_id=hook_id,
            )

            # Delegate to PostToolUseService
            from des.adapters.driven.logging.jsonl_audit_log_reader import (
                JsonlAuditLogReader,
            )
            from des.application.post_tool_use_service import PostToolUseService

            reader = JsonlAuditLogReader()
            service = PostToolUseService(audit_reader=reader)
            additional_context = service.check_completion_status(
                is_des_task=is_des_task,
            )

            if additional_context:
                response = {"additionalContext": additional_context}
            else:
                response = {}

            print(json.dumps(response))
            return 0

    except Exception as e:
        stderr_capture = stderr_buffer.getvalue()[:_STDERR_CAPTURE_MAX_CHARS]
        _log_hook_error("opencode_post_tool_use", e, stderr_capture)
        print(json.dumps({}))
        return 0
    finally:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        decision_str = _EXIT_CODE_TO_DECISION.get(exit_code, "error")
        _log_hook_completed(
            hook_id=hook_id,
            handler="opencode_post_tool_use",
            exit_code=exit_code,
            decision=decision_str,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Hook adapter entry point - routes command to appropriate handler."""
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "Missing command argument (pre-tool-use, stop, or post-tool-use)",
                }
            )
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == "pre-tool-use":
        exit_code = handle_pre_tool_use()
    elif command == "stop":
        exit_code = handle_stop()
    elif command == "post-tool-use":
        exit_code = handle_post_tool_use()
    else:
        print(json.dumps({"status": "error", "reason": f"Unknown command: {command}"}))
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
