"""Tests for OpenCode hook adapter protocol translation.

The OpenCode adapter bridges OpenCode's plugin protocol to the same DES
application services used by the Claude Code adapter.

Key differences tested:
1. OpenCode sends {tool, args, sessionID} vs Claude Code's {tool_name, tool_input}
2. OpenCode's "stop" hook vs Claude Code's "subagent-stop"
3. Field translation (camelCase → snake_case, different nesting)
"""

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from des.adapters.drivers.hooks.opencode_hook_adapter import (
    _translate_pre_tool_use_input,
    _translate_stop_input,
    handle_post_tool_use,
    handle_pre_tool_use,
    handle_stop,
)


# ---------------------------------------------------------------------------
# Translation unit tests
# ---------------------------------------------------------------------------


class TestTranslatePreToolUseInput:
    """Tests for OpenCode → DES field translation (PreToolUse)."""

    def test_translates_standard_opencode_format(self):
        hook_input = {
            "tool": "Task",
            "args": {
                "prompt": "<!-- DES-VALIDATION: required -->\nDo something",
                "max_turns": 10,
                "subagent_type": "Bash",
            },
            "sessionID": "sess-123",
        }

        result = _translate_pre_tool_use_input(hook_input)

        assert result["prompt"] == "<!-- DES-VALIDATION: required -->\nDo something"
        assert result["max_turns"] == 10
        assert result["subagent_type"] == "Bash"

    def test_handles_camelcase_field_names(self):
        hook_input = {
            "tool": "Task",
            "args": {
                "prompt": "test",
                "maxTurns": 5,
                "subagentType": "Explore",
            },
        }

        result = _translate_pre_tool_use_input(hook_input)

        assert result["max_turns"] == 5
        assert result["subagent_type"] == "Explore"

    def test_handles_missing_optional_fields(self):
        hook_input = {
            "tool": "Task",
            "args": {"prompt": "test"},
        }

        result = _translate_pre_tool_use_input(hook_input)

        assert result["prompt"] == "test"
        assert result["max_turns"] is None
        assert result["subagent_type"] == ""

    def test_handles_empty_args(self):
        hook_input = {"tool": "Task"}

        result = _translate_pre_tool_use_input(hook_input)

        assert result["prompt"] == ""
        assert result["max_turns"] is None
        assert result["subagent_type"] == ""

    def test_snake_case_takes_precedence_over_camel_case(self):
        hook_input = {
            "tool": "Task",
            "args": {
                "prompt": "test",
                "max_turns": 10,
                "maxTurns": 5,  # Should be ignored (snake_case wins via `or`)
            },
        }

        result = _translate_pre_tool_use_input(hook_input)

        assert result["max_turns"] == 10


class TestTranslateStopInput:
    """Tests for OpenCode → DES field translation (stop hook)."""

    def test_translates_standard_stop_format(self):
        hook_input = {
            "sessionID": "sess-456",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/home/user/project",
            "stop_hook_active": True,
        }

        result = _translate_stop_input(hook_input)

        assert result["agent_transcript_path"] == "/tmp/transcript.jsonl"
        assert result["cwd"] == "/home/user/project"
        assert result["stop_hook_active"] is True
        assert result["session_id"] == "sess-456"

    def test_handles_directory_field_fallback(self):
        """OpenCode may send 'directory' instead of 'cwd'."""
        hook_input = {
            "sessionID": "sess-789",
            "transcript_path": "/tmp/t.jsonl",
            "directory": "/home/user/other",
        }

        result = _translate_stop_input(hook_input)

        assert result["cwd"] == "/home/user/other"

    def test_handles_session_id_variations(self):
        """OpenCode may use sessionID or session_id."""
        hook_input_camel = {"sessionID": "camel-id"}
        hook_input_snake = {"session_id": "snake-id"}

        assert _translate_stop_input(hook_input_camel)["session_id"] == "camel-id"
        assert _translate_stop_input(hook_input_snake)["session_id"] == "snake-id"

    def test_handles_missing_fields(self):
        hook_input = {}

        result = _translate_stop_input(hook_input)

        assert result["agent_transcript_path"] == ""
        assert result["cwd"] == ""
        assert result["stop_hook_active"] is False
        assert result["session_id"] == ""


# ---------------------------------------------------------------------------
# Handler integration tests (stdin/stdout protocol)
# ---------------------------------------------------------------------------


class TestHandlePreToolUseProtocol:
    """Tests for PreToolUse handler stdin/stdout protocol."""

    def test_empty_stdin_returns_allow(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO(""))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_pre_tool_use()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response["decision"] == "allow"

    def test_invalid_json_returns_error(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("not-json{"))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_pre_tool_use()

        assert exit_code == 1
        response = json.loads(captured.getvalue())
        assert response["status"] == "error"

    @patch("des.adapters.drivers.hooks.opencode_hook_adapter.create_pre_tool_use_service")
    def test_allow_decision_returns_exit_0(self, mock_service_factory, monkeypatch):
        from des.ports.driver_ports.pre_tool_use_port import HookDecision

        mock_service = MagicMock()
        mock_service.validate.return_value = HookDecision.allow()
        mock_service_factory.return_value = mock_service

        opencode_input = json.dumps(
            {
                "tool": "Task",
                "args": {"prompt": "Do something", "max_turns": 5},
                "sessionID": "s1",
            }
        )
        monkeypatch.setattr("sys.stdin", StringIO(opencode_input))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_pre_tool_use()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response["decision"] == "allow"

    @patch("des.adapters.drivers.hooks.opencode_hook_adapter.create_pre_tool_use_service")
    def test_block_decision_returns_exit_2(self, mock_service_factory, monkeypatch):
        from des.ports.driver_ports.pre_tool_use_port import HookDecision

        mock_service = MagicMock()
        mock_service.validate.return_value = HookDecision.block(
            reason="Missing DES markers",
            recovery_suggestions=["Add DES-VALIDATION marker"],
        )
        mock_service_factory.return_value = mock_service

        opencode_input = json.dumps(
            {
                "tool": "Task",
                "args": {"prompt": "Do something"},
                "sessionID": "s1",
            }
        )
        monkeypatch.setattr("sys.stdin", StringIO(opencode_input))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_pre_tool_use()

        assert exit_code == 2
        response = json.loads(captured.getvalue())
        assert response["decision"] == "block"
        assert "Missing DES markers" in response["reason"]
        assert "Add DES-VALIDATION marker" in response["reason"]

    @patch("des.adapters.drivers.hooks.opencode_hook_adapter.create_pre_tool_use_service")
    def test_opencode_args_translated_to_pre_tool_use_input(
        self, mock_service_factory, monkeypatch
    ):
        """Verify OpenCode's {tool, args} format is correctly translated."""
        from des.ports.driver_ports.pre_tool_use_port import HookDecision

        mock_service = MagicMock()
        mock_service.validate.return_value = HookDecision.allow()
        mock_service_factory.return_value = mock_service

        opencode_input = json.dumps(
            {
                "tool": "Task",
                "args": {
                    "prompt": "Implement feature X",
                    "max_turns": 15,
                    "subagent_type": "general-purpose",
                },
                "sessionID": "sess-abc",
            }
        )
        monkeypatch.setattr("sys.stdin", StringIO(opencode_input))
        monkeypatch.setattr("sys.stdout", StringIO())

        handle_pre_tool_use()

        # Verify the service received correctly translated input
        call_args = mock_service.validate.call_args
        input_data = call_args[0][0]
        assert input_data.prompt == "Implement feature X"
        assert input_data.max_turns == 15
        assert input_data.subagent_type == "general-purpose"


class TestHandlePostToolUseProtocol:
    """Tests for PostToolUse handler stdin/stdout protocol."""

    def test_empty_stdin_returns_empty_json(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO(""))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_post_tool_use()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response == {}

    def test_invalid_json_fails_open(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("{bad"))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_post_tool_use()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response == {}

    def test_always_returns_exit_0(self, monkeypatch):
        """PostToolUse should never block, always exit 0."""
        opencode_input = json.dumps(
            {
                "tool": "Task",
                "args": {"prompt": "test"},
                "sessionID": "s1",
            }
        )
        monkeypatch.setattr("sys.stdin", StringIO(opencode_input))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_post_tool_use()

        assert exit_code == 0


class TestHandleStopProtocol:
    """Tests for Stop handler stdin/stdout protocol."""

    def test_empty_stdin_returns_allow(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO(""))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_stop()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response["decision"] == "allow"

    def test_invalid_json_returns_error(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("invalid"))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_stop()

        assert exit_code == 1
        response = json.loads(captured.getvalue())
        assert response["status"] == "error"

    @patch(
        "des.adapters.drivers.hooks.claude_code_hook_adapter.extract_des_context_from_transcript"
    )
    def test_non_des_session_allows_through(self, mock_extract, monkeypatch):
        """Sessions without DES markers should be allowed."""
        mock_extract.return_value = None

        stop_input = json.dumps(
            {
                "sessionID": "sess-1",
                "transcript_path": "/tmp/transcript.jsonl",
                "cwd": "/home/user/project",
            }
        )
        monkeypatch.setattr("sys.stdin", StringIO(stop_input))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_stop()

        assert exit_code == 0
        response = json.loads(captured.getvalue())
        assert response["decision"] == "allow"

    def test_missing_transcript_allows_through(self, monkeypatch):
        """No transcript path means non-DES — allow."""
        stop_input = json.dumps({"sessionID": "sess-1"})
        monkeypatch.setattr("sys.stdin", StringIO(stop_input))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        exit_code = handle_stop()

        assert exit_code == 0


# ---------------------------------------------------------------------------
# Protocol comparison: OpenCode vs Claude Code
# ---------------------------------------------------------------------------


class TestProtocolFormatDifferences:
    """Document and verify the key protocol differences between adapters."""

    def test_opencode_uses_tool_and_args_not_tool_name_and_tool_input(self):
        """OpenCode: {tool, args}, Claude Code: {tool_name, tool_input}."""
        opencode_format = {
            "tool": "Task",
            "args": {"prompt": "test", "max_turns": 5},
            "sessionID": "s1",
        }

        claude_format = {
            "tool_name": "Task",
            "tool_input": {"prompt": "test", "max_turns": 5},
        }

        # Both translate to the same PreToolUseInput
        oc_result = _translate_pre_tool_use_input(opencode_format)
        assert oc_result["prompt"] == "test"
        assert oc_result["max_turns"] == 5

        # Claude Code's adapter reads tool_input directly, not through translation
        cc_tool_input = claude_format["tool_input"]
        assert cc_tool_input["prompt"] == "test"
        assert cc_tool_input["max_turns"] == 5

    def test_opencode_stop_vs_claude_subagent_stop(self):
        """OpenCode 'stop' is session-level; Claude 'subagent-stop' is per-agent."""
        opencode_stop = {
            "sessionID": "sess-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
        }

        claude_subagent_stop = {
            "agent_id": "agent-1",
            "agent_type": "Bash",
            "agent_transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
        }

        # Both ultimately need: transcript path + cwd
        oc = _translate_stop_input(opencode_stop)
        assert oc["agent_transcript_path"] == "/tmp/t.jsonl"
        assert oc["cwd"] == "/project"

        # Claude Code reads these directly from hook_input
        assert claude_subagent_stop["agent_transcript_path"] == "/tmp/t.jsonl"
        assert claude_subagent_stop["cwd"] == "/project"
