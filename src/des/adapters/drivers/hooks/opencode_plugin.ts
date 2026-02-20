/**
 * nWave DES Plugin for OpenCode
 *
 * Bridges OpenCode's plugin hook system to nWave's DES validation services
 * by calling the Python opencode_hook_adapter via subprocess.
 *
 * Install: Copy to ~/.config/opencode/plugins/ or .opencode/plugins/
 *
 * Architecture:
 *   OpenCode Plugin (this file)
 *     → subprocess: python3 -m src.des.adapters.drivers.hooks.opencode_hook_adapter
 *       → DES Application Services (PreToolUseService, SubagentStopService, etc.)
 *         → Domain Policies
 *
 * This is the OpenCode equivalent of the Claude Code settings.json hook configuration.
 * Both adapters call the same application services through the hexagonal architecture.
 */

import type { Plugin } from "@opencode-ai/plugin";

// Resolve the nWave project root from environment or default paths
const NWAVE_ROOT =
  process.env.NWAVE_ROOT || process.env.HOME + "/nWave";

const PYTHON_PATH = process.env.NWAVE_PYTHON || "python3";

interface AdapterResponse {
  decision?: "allow" | "block";
  status?: "error";
  reason?: string;
  additionalContext?: string;
}

/**
 * Call the Python hook adapter via subprocess.
 *
 * @param command - The adapter command (pre-tool-use, stop, post-tool-use)
 * @param input - JSON input to send on stdin
 * @returns Parsed JSON response from the adapter
 */
async function callAdapter(
  command: string,
  input: Record<string, unknown>,
  $: any
): Promise<AdapterResponse> {
  const adapterModule =
    "src.des.adapters.drivers.hooks.opencode_hook_adapter";
  const cmd = `cd ${NWAVE_ROOT} && PYTHONPATH=${NWAVE_ROOT} ${PYTHON_PATH} -m ${adapterModule} ${command}`;

  try {
    const proc = Bun.spawn(["bash", "-c", cmd], {
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
      cwd: NWAVE_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: NWAVE_ROOT,
      },
    });

    // Write JSON input to stdin
    const writer = proc.stdin.getWriter();
    writer.write(new TextEncoder().encode(JSON.stringify(input)));
    writer.close();

    // Wait for process to complete
    const exitCode = await proc.exited;
    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();

    if (stderr) {
      console.error(`[nWave DES] ${command} stderr: ${stderr}`);
    }

    // Parse response
    let response: AdapterResponse = {};
    if (stdout.trim()) {
      try {
        response = JSON.parse(stdout.trim());
      } catch {
        console.error(`[nWave DES] Failed to parse adapter response: ${stdout}`);
      }
    }

    // Handle exit codes: 1 = error (fail-closed), 2 = block
    if (exitCode === 1) {
      throw new Error(
        response.reason || `DES adapter error (exit code 1): ${stderr}`
      );
    }
    if (exitCode === 2) {
      throw new Error(
        response.reason || "DES validation failed (exit code 2)"
      );
    }

    return response;
  } catch (error) {
    if (error instanceof Error && error.message.includes("DES")) {
      throw error; // Re-throw DES errors
    }
    console.error(`[nWave DES] Adapter call failed: ${error}`);
    throw error;
  }
}

/**
 * nWave DES Plugin for OpenCode.
 *
 * Hooks into tool execution lifecycle to enforce DES validation:
 * - tool.execute.before: Validates Task tool prompts contain required DES markers
 * - tool.execute.after: Checks for subagent completion failures
 * - stop: Validates step completion when agent session ends
 */
export const nWaveDES: Plugin = async ({ client, project, $, directory }) => {
  console.log("[nWave DES] Plugin loaded for project:", directory);

  return {
    event: {
      /**
       * Pre-tool-use validation (equivalent to Claude Code's PreToolUse hook).
       *
       * Fires before any tool execution. We only intercept Task-type tools
       * to validate DES markers in the prompt.
       *
       * Throwing an Error blocks the tool execution — this is how OpenCode
       * handles the "block" decision (unlike Claude Code's exit code 2).
       */
      "tool.execute.before": async (input, output) => {
        // Only intercept Task tool (skip other tools like bash, edit, etc.)
        if (input.tool !== "Task") {
          return;
        }

        const response = await callAdapter(
          "pre-tool-use",
          {
            tool: input.tool,
            args: input.args,
            sessionID: input.sessionID,
          },
          $
        );

        if (response.decision === "block") {
          throw new Error(
            response.reason || "DES validation blocked this Task"
          );
        }
      },

      /**
       * Post-tool-use notification (equivalent to Claude Code's PostToolUse hook).
       *
       * Fires after any tool execution completes. Checks for DES subagent
       * completion failures and injects context if needed.
       *
       * This hook never blocks (fail-open), matching Claude Code behavior.
       */
      "tool.execute.after": async (input) => {
        if (input.tool !== "Task") {
          return;
        }

        try {
          const response = await callAdapter(
            "post-tool-use",
            {
              tool: input.tool,
              args: input.args,
              sessionID: input.sessionID,
            },
            $
          );

          if (response.additionalContext) {
            // OpenCode doesn't have a direct additionalContext injection mechanism.
            // Log the context for visibility; a future OpenCode API may support this.
            console.log(
              "[nWave DES] Completion context:",
              response.additionalContext
            );
          }
        } catch (error) {
          // PostToolUse is fail-open: never block on errors
          console.error("[nWave DES] PostToolUse error (non-blocking):", error);
        }
      },

      /**
       * Stop hook (equivalent to Claude Code's SubagentStop hook).
       *
       * Fires when the agent session becomes idle or completes.
       * Validates that DES step completion requirements are met.
       *
       * Key difference from Claude Code: OpenCode's stop fires once per session,
       * while Claude Code's SubagentStop fires per-subagent. The adapter handles
       * this by extracting DES context from the session transcript.
       */
      stop: async (input) => {
        try {
          const response = await callAdapter(
            "stop",
            {
              sessionID: input.sessionID || input.session_id,
              transcript_path: (input as any).transcript_path || "",
              cwd: directory,
              stop_hook_active: (input as any).stop_hook_active || false,
            },
            $
          );

          if (response.decision === "block") {
            throw new Error(
              response.reason || "DES stop validation failed"
            );
          }
        } catch (error) {
          if (
            error instanceof Error &&
            error.message.includes("STOP HOOK VALIDATION FAILED")
          ) {
            throw error; // Re-throw DES validation failures
          }
          // Log but don't block on adapter errors
          console.error("[nWave DES] Stop hook error:", error);
        }
      },
    },
  };
};

export default nWaveDES;
