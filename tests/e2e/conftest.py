"""Shared fixtures for E2E testcontainers tests.

Provides:
- ``require_docker``: pytest mark that skips when Docker is unavailable
- ``_exec``: helper to run a command in a DockerContainer and return (exit_code, output)
- ``_exec_ok``: run a command and assert exit 0

All E2E test modules import from here to avoid duplicating the docker-availability
guard and the exec helper in every file.

Note: test_fresh_install.py predates this module and defines its own local versions
of ``_is_docker_available``, ``requires_docker``, ``_exec``, and ``_exec_ok``.
Those local definitions remain unchanged for backwards-compatibility.  New E2E
test modules should import the shared fixtures from this file.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Docker availability — evaluated once per session
# ---------------------------------------------------------------------------


def _is_docker_available() -> bool:
    """Return True if the Docker daemon is reachable."""
    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


_DOCKER_AVAILABLE: bool = _is_docker_available()


#: Pytest mark: skip if Docker daemon is not reachable.
require_docker = pytest.mark.skipif(
    not _DOCKER_AVAILABLE,
    reason="Docker daemon not available — skipping E2E container test",
)


# ---------------------------------------------------------------------------
# Container exec helpers
# ---------------------------------------------------------------------------


def exec_in_container(
    container,
    command: str | list[str],
    environment: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run *command* inside *container* and return ``(exit_code, output)``.

    When *environment* is provided the call falls through to the docker-py
    ``exec_run`` API (the testcontainers ``exec()`` shim does not accept an
    environment dict).  Otherwise the lighter ``container.exec()`` wrapper is
    used.

    Args:
        container: A running ``testcontainers.core.container.DockerContainer``.
        command: Command string or list of strings to execute.
        environment: Optional mapping of environment variables for the command.

    Returns:
        ``(exit_code, decoded_output)`` tuple.
    """
    if environment:
        raw = container.get_wrapped_container().exec_run(
            cmd=command,
            environment=environment,
        )
        exit_code: int = raw.exit_code
        output_bytes = raw.output
    else:
        result = container.exec(command)
        exit_code = result.exit_code
        output_bytes = result.output

    output: str = output_bytes.decode("utf-8", errors="replace") if output_bytes else ""
    return exit_code, output


def exec_ok(container, command: str | list[str]) -> str:
    """Run *command* and assert exit 0; return decoded output.

    Fails the test immediately if the command exits non-zero.
    """
    exit_code, output = exec_in_container(container, command)
    assert exit_code == 0, f"Command {command!r} exited {exit_code}.\nOutput:\n{output}"
    return output


# ---------------------------------------------------------------------------
# OpenCode container fixture — shared between opencode-full-install and
# opencode-subagent-hooks tests (session scope to amortize npm/opencode setup)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def opencode_container():
    """Session-scoped container with OpenCode CLI + nWave installed.

    Mirrors Dockerfile.env-opencode build sequence:
      1. Install nodejs 22 + opencode-ai npm package
      2. Configure OpenCode (~/.config/opencode/opencode.json)
      3. Run scripts/install/install_nwave.py from volume-mounted source

    The container is reused across all tests that only need the
    installer side-effects (skills, agents, commands, manifests).
    Tests that also need OPENAI_API_KEY runtime probing build their
    own image via subprocess since that path requires a different
    pipx + overlay layout.
    """
    from pathlib import Path

    from tests.e2e.conftest import _is_docker_available

    if not _is_docker_available():
        pytest.skip("Docker daemon not available")

    from testcontainers.core.container import (
        DockerContainer,  # type: ignore[import-untyped]
    )

    repo_root = Path(__file__).parent.parent.parent
    container = DockerContainer(image="python:3.12-slim")
    container.with_volume_mapping(str(repo_root), "/src", "ro")
    container.with_env("HOME", "/home/tester")
    container.with_env("DEBIAN_FRONTEND", "noninteractive")
    container._command = "tail -f /dev/null"

    with container:
        setup_script = (
            "set -e && "
            "apt-get update -qq && "
            "apt-get install -y --no-install-recommends git curl -qq && "
            "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1 && "
            "apt-get install -y --no-install-recommends nodejs -qq && "
            "rm -rf /var/lib/apt/lists/* && "
            "npm install -g opencode-ai --silent 2>&1 | tail -5 && "
            "useradd -m tester && "
            "mkdir -p /home/tester/.config/opencode && "
            'echo \'{"model": "openai/gpt-4o-mini"}\' > /home/tester/.config/opencode/opencode.json && '
            "chown -R tester:tester /home/tester"
        )
        code, out = exec_in_container(container, ["bash", "-c", setup_script])
        assert code == 0, (
            f"OpenCode container setup failed (exit {code}).\n{out[-800:]}"
        )

        # Copy repo to writable tester location (install needs to write relative-to-source)
        copy_script = (
            "set -e && "
            "cp -r /src /home/tester/nwave-dev && "
            "chown -R tester:tester /home/tester/nwave-dev"
        )
        code, out = exec_in_container(container, ["bash", "-c", copy_script])
        assert code == 0, f"Repo copy failed (exit {code}).\n{out[-500:]}"

        # Install into a venv owned by tester, then run installer as tester
        install_script = (
            "set -e && "
            "python -m venv /tmp/venv && "
            "/tmp/venv/bin/pip install --quiet pyyaml rich typer pydantic pydantic-settings httpx platformdirs packaging && "
            "chown -R tester:tester /tmp/venv && "
            "su tester -c 'cd /home/tester/nwave-dev && "
            "VIRTUAL_ENV=/tmp/venv PATH=/tmp/venv/bin:$PATH "
            "python scripts/install/install_nwave.py' 2>&1"
        )
        code, out = exec_in_container(container, ["bash", "-c", install_script])
        # Install may exit non-zero if optional plugins fail; outcome is asserted
        # per-test against core markers (mirrors Dockerfile `|| true` pattern).
        container._install_stdout = out  # type: ignore[attr-defined]

        yield container
