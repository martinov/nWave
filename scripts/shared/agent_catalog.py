"""Shared public/private agent filtering logic.

Used by installer plugins and build scripts to exclude private agents
and their skills from public distributions. The source of truth is
``nWave/framework-catalog.yaml`` where each agent has a ``public`` field.

Backward compatibility: when the catalog file is missing or cannot be parsed,
all functions treat every agent as public (empty set semantics).

**Important**: PyYAML must be installed. If missing, ``load_public_agents``
raises ``RuntimeError`` instead of silently returning an empty set (which
would cause all agents to be treated as public — a security leak).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def load_public_agents(nwave_dir: Path) -> set[str]:
    """Read framework-catalog.yaml and return the set of public agent names.

    An agent is public when its ``public`` field is not ``False``.
    Missing ``public`` field defaults to public.

    Returns an empty set when the catalog file is missing or cannot be
    parsed (backward compatibility -- callers treat empty set as
    "include everything").
    """
    catalog_path = nwave_dir / "framework-catalog.yaml"
    if not catalog_path.exists():
        return set()

    try:
        import yaml
    except ModuleNotFoundError:
        msg = (
            "PyYAML is required for agent filtering but is not installed. "
            "Install it with: pip install pyyaml"
        )
        raise RuntimeError(msg) from None

    try:
        with catalog_path.open(encoding="utf-8") as fh:
            catalog = yaml.safe_load(fh)

        return {
            name
            for name, info in catalog.get("agents", {}).items()
            if info.get("public") is not False
        }
    except Exception:
        return set()


def is_public_agent(agent_file_name: str, public_agents: set[str]) -> bool:
    """Check whether an agent file belongs to a public agent.

    Strips the ``nw-`` prefix and ``.md`` suffix to derive the agent name.
    Reviewer agents (``-reviewer`` suffix) inherit the public status of
    their base agent.

    When *public_agents* is empty (catalog not loaded), returns ``True``
    for every file (backward compatibility).
    """
    if not public_agents:
        return True
    agent_name = agent_file_name.removeprefix("nw-").removesuffix(".md")
    base_name = agent_name.removesuffix("-reviewer")
    return agent_name in public_agents or base_name in public_agents


def is_public_skill(skill_dir_name: str, public_agents: set[str]) -> bool:
    """Check whether a skill directory belongs to a public agent.

    The ``common`` directory is always considered public.
    Reviewer skill directories inherit the public status of their base
    agent.

    When *public_agents* is empty (catalog not loaded), returns ``True``
    for every directory (backward compatibility).
    """
    if not public_agents:
        return True
    if skill_dir_name == "common":
        return True
    base_name = skill_dir_name.removesuffix("-reviewer")
    return skill_dir_name in public_agents or base_name in public_agents
