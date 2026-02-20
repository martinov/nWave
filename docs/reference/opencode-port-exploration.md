# OpenCode Port Exploration

Feasibility analysis for porting nWave's DES hook system from Claude Code to OpenCode.

## Executive Summary

**Verdict: Feasible with adaptation.** The hexagonal architecture cleanly separates protocol
translation (adapters) from business logic (application services + domain policies). Porting
requires only a new driver adapter -- no changes to the application or domain layers.

A proof-of-concept adapter has been implemented alongside the existing Claude Code adapter,
demonstrating that both CLI tools can share the same DES validation pipeline.

## Architecture

```
┌─────────────────────┐    ┌──────────────────────┐
│  Claude Code CLI     │    │  OpenCode CLI         │
│  (settings.json)     │    │  (TypeScript plugin)  │
└────────┬────────────┘    └────────┬─────────────┘
         │ subprocess               │ subprocess
         ▼                          ▼
┌─────────────────────┐    ┌──────────────────────┐
│ claude_code_hook_    │    │ opencode_hook_        │
│ adapter.py           │    │ adapter.py            │
│ (Protocol: JSON      │    │ (Protocol: JSON       │
│  stdin/stdout +      │    │  stdin/stdout +       │
│  exit codes 0/1/2)   │    │  exit codes 0/1/2)   │
└────────┬────────────┘    └────────┬─────────────┘
         │                          │
         └──────────┬───────────────┘
                    ▼
         ┌──────────────────┐
         │ Application Layer │
         │ PreToolUseService │
         │ SubagentStopSvc   │
         │ PostToolUseSvc    │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │   Domain Layer    │
         │ MaxTurnsPolicy    │
         │ DesEnforcement    │
         │ MarkerParser      │
         │ SessionGuard      │
         └──────────────────┘
```

Both adapters call the same `PreToolUseService`, `SubagentStopService`, and
`PostToolUseService` through the same port interfaces. The adapter is the only
layer that changes.

## Protocol Comparison

### Event Names

| Lifecycle Event | Claude Code | OpenCode |
|----------------|-------------|----------|
| Before tool execution | `PreToolUse` | `tool.execute.before` |
| After tool execution | `PostToolUse` | `tool.execute.after` |
| Agent/session stop | `SubagentStop` | `stop` |
| Before file write | `PreToolUse` (matcher: Write) | `file.edited` (different timing) |

### Input Format

**Claude Code** (`PreToolUse`):
```json
{
  "tool_name": "Task",
  "tool_input": {
    "prompt": "...",
    "max_turns": 10,
    "subagent_type": "Bash"
  }
}
```

**OpenCode** (`tool.execute.before`):
```json
{
  "tool": "Task",
  "args": {
    "prompt": "...",
    "max_turns": 10,
    "subagent_type": "Bash"
  },
  "sessionID": "sess-abc"
}
```

Key differences:
- `tool_name` → `tool`
- `tool_input` → `args`
- OpenCode includes `sessionID`
- OpenCode may use camelCase (`maxTurns`, `subagentType`)

### Stop Event

**Claude Code** (`SubagentStop`) -- fires per-subagent:
```json
{
  "agent_id": "agent-123",
  "agent_type": "Bash",
  "agent_transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/project",
  "stop_hook_active": false
}
```

**OpenCode** (`stop`) -- fires per-session:
```json
{
  "sessionID": "sess-456",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/project"
}
```

Key differences:
- Per-subagent (Claude) vs per-session (OpenCode)
- `agent_transcript_path` → `transcript_path`
- No `agent_type` in OpenCode

### Blocking Mechanism

| Mechanism | Claude Code | OpenCode |
|-----------|------------|----------|
| Allow | Exit code 0 + `{"decision": "allow"}` | Return normally |
| Block | Exit code 2 + `{"decision": "block", "reason": "..."}` | Throw `Error` |
| Error (fail-closed) | Exit code 1 | Throw `Error` |
| Context injection | `{"additionalContext": "..."}` | `console.log()` (no native equivalent) |

### Configuration

**Claude Code** (`~/.claude/settings.json`):
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Task",
      "hooks": [{"type": "command", "command": "python3 -m ... pre-tool-use"}]
    }]
  }
}
```

**OpenCode** (`~/.config/opencode/plugins/nwave-des-plugin.ts`):
```typescript
export const nWaveDES: Plugin = async ({ client, project, $ }) => ({
  event: {
    "tool.execute.before": async (input, output) => { /* ... */ },
    "tool.execute.after": async (input) => { /* ... */ },
    stop: async (input) => { /* ... */ }
  }
})
```

## Gaps and Limitations

### 1. No `additionalContext` Injection
Claude Code supports injecting `additionalContext` into the parent conversation
via `PostToolUse` response. OpenCode has no equivalent mechanism. The PoC logs
context to console, but the orchestrator agent won't see it in-conversation.

**Impact**: Failure notifications from DES subagent stop validation won't be
injected into the parent agent's context. The stop hook can still block, but
the failure details won't flow back to the orchestrator automatically.

**Mitigation**: OpenCode could add a context injection API, or the plugin could
write failure details to a file that the orchestrator reads.

### 2. Session-Level vs Subagent-Level Stop
Claude Code's `SubagentStop` fires once per subagent completion, with
`agent_transcript_path` pointing to that specific subagent's transcript.
OpenCode's `stop` fires once per session.

**Impact**: In multi-step DES workflows where multiple subagents run
sequentially, the Claude Code adapter validates each step individually.
The OpenCode adapter would need to track which steps have been validated
or validate all steps at session end.

**Mitigation**: The PoC handles this by extracting DES context from whatever
transcript is available. For full multi-step support, the plugin would need
to track subagent boundaries.

### 3. PreWrite/PreEdit Guard
The Claude Code adapter has a `PreWrite`/`PreEdit` handler that guards source
file writes during deliver sessions. OpenCode's `file.edited` event fires
*after* the edit, not before.

**Impact**: Cannot prevent unauthorized source writes proactively. Can only
detect and report them after the fact.

**Mitigation**: OpenCode's `tool.execute.before` could intercept Write/Edit
tools before execution, providing equivalent pre-write guarding.

### 4. TypeScript Plugin Requirement
OpenCode plugins must be TypeScript/JavaScript. The nWave DES services are
Python. The PoC uses subprocess calls, adding latency (~100-200ms per hook
invocation due to Python startup).

**Impact**: Hook latency is higher than Claude Code's direct subprocess approach
(which also has Python startup, but avoids the extra TypeScript → subprocess hop).

**Mitigation**: For performance-critical deployments, core validation logic
could be ported to TypeScript, or a long-running Python server could be used
instead of subprocess-per-invocation.

## Files Created

| File | Purpose |
|------|---------|
| `src/des/adapters/drivers/hooks/opencode_hook_adapter.py` | Python adapter translating OpenCode protocol → DES services |
| `src/des/adapters/drivers/hooks/opencode_plugin.ts` | TypeScript plugin for OpenCode's plugin system |
| `scripts/install/install_opencode_hooks.py` | Installer script for OpenCode plugin |
| `tests/des/unit/adapters/drivers/hooks/test_opencode_hook_adapter.py` | Unit tests (23 passing) |

## Conclusion

The port is architecturally clean thanks to hexagonal architecture. The main
effort is protocol translation in the adapter layer. The three gaps identified
(no context injection, session-level stop, no pre-write guard) are addressable
but require either OpenCode API additions or workaround patterns.

Recommended next steps:
1. Test with actual OpenCode CLI to validate plugin loading and event formats
2. File OpenCode feature request for `additionalContext` injection
3. Implement `tool.execute.before` interception for Write/Edit tools
4. Consider long-running Python server to reduce hook latency
