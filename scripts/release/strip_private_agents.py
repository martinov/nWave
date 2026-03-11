"""Strip private agents and skills from a target directory.

Reads framework-catalog.yaml to find agents with ``public: false``,
then removes their agent files and skill directories from the target
tree.  Designed to run after rsync in the release-prod pipeline so
that the public repository never receives private content.

Usage::

    python scripts/release/strip_private_agents.py <target-dir>

``<target-dir>`` is the root of the rsynced public repo clone
(contains ``nWave/`` subdirectory).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml


def _load_private_agents(catalog_path: Path) -> set[str]:
    """Return agent names where ``public`` is explicitly ``false``."""
    with catalog_path.open(encoding="utf-8") as fh:
        catalog = yaml.safe_load(fh)

    private: set[str] = set()
    for name, info in catalog.get("agents", {}).items():
        if info.get("public") is False:
            private.add(name)
    return private


def _strip_catalog(catalog_path: Path, private_agents: set[str]) -> int:
    """Remove private agent entries from the catalog YAML.

    Also strips their command entries if present.  Returns the number
    of entries removed.
    """
    with catalog_path.open(encoding="utf-8") as fh:
        catalog = yaml.safe_load(fh)

    count = 0

    # Strip from agents section
    agents = catalog.get("agents", {})
    for name in list(agents):
        if name in private_agents:
            del agents[name]
            count += 1

    # Strip from commands section (commands referencing private agents)
    commands = catalog.get("commands", {})
    for cmd_name in list(commands):
        cmd = commands[cmd_name]
        cmd_agents = cmd.get("agents", [])
        if any(a in private_agents for a in cmd_agents):
            # If ALL agents are private, remove the command entirely
            if all(a in private_agents for a in cmd_agents):
                del commands[cmd_name]
                count += 1
            else:
                # Remove only the private agents from the list
                cmd["agents"] = [a for a in cmd_agents if a not in private_agents]

    with catalog_path.open("w", encoding="utf-8") as fh:
        yaml.dump(catalog, fh, default_flow_style=False, sort_keys=False)

    return count


def _strip_reference_docs(target_dir: Path, private_agents: set[str]) -> list[str]:
    """Remove generated reference docs for private agents.

    Deletes individual agent doc files and scrubs index files
    (``docs/reference/agents/index.md``, ``docs/reference/skills/index.md``).
    """
    removed: list[str] = []
    ref_agents_dir = target_dir / "docs" / "reference" / "agents"
    ref_skills_index = target_dir / "docs" / "reference" / "skills" / "index.md"

    # Build set of all names to match (agent + reviewer variants)
    private_names: set[str] = set()
    for name in private_agents:
        private_names.add(name)
        private_names.add(f"{name}-reviewer")

    # Delete individual agent reference files
    if ref_agents_dir.exists():
        for name in sorted(private_names):
            doc_file = ref_agents_dir / f"nw-{name}.md"
            if doc_file.exists():
                doc_file.unlink()
                removed.append(str(doc_file.relative_to(target_dir)))

        # Scrub agent index: remove lines referencing private agents
        agent_index = ref_agents_dir / "index.md"
        if agent_index.exists():
            _scrub_index_file(agent_index, private_names)
            removed.append(f"scrubbed {agent_index.relative_to(target_dir)}")

    # Scrub skills index: remove sections for private agents
    if ref_skills_index.exists():
        _scrub_index_file(ref_skills_index, private_names)
        removed.append(f"scrubbed {ref_skills_index.relative_to(target_dir)}")

    # Scrub public reviewer docs that link to private skill paths
    if ref_agents_dir.exists():
        for reviewer_doc in sorted(ref_agents_dir.glob("nw-*-reviewer.md")):
            _scrub_private_links(reviewer_doc, private_names)

    return removed


def _scrub_index_file(index_path: Path, private_names: set[str]) -> None:
    """Remove lines from an index file that reference private agents."""
    content = index_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    filtered: list[str] = []
    skip_section = False

    for line in lines:
        # Detect markdown section headers for private agents (skills index)
        stripped = line.strip()
        if stripped.startswith("##") and any(
            f"nw-{name}" in stripped for name in private_names
        ):
            skip_section = True
            continue

        # End section skip on next header
        if skip_section and stripped.startswith("##"):
            skip_section = False

        if skip_section:
            continue

        # Filter table rows and list items referencing private agents
        if any(f"nw-{name}" in line or f"/{name}" in line for name in private_names):
            continue

        filtered.append(line)

    index_path.write_text("".join(filtered), encoding="utf-8")


def _scrub_private_links(doc_path: Path, private_names: set[str]) -> None:
    """Remove lines containing links to private skill directories."""
    content = doc_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    filtered = [
        line
        for line in lines
        if not any(f"skills/{name}/" in line for name in private_names)
    ]
    if len(filtered) != len(lines):
        doc_path.write_text("".join(filtered), encoding="utf-8")


def strip(target_dir: Path) -> dict[str, list[str]]:
    """Remove private agent files and skill dirs from *target_dir*.

    Returns a dict with ``agents``, ``skills``, ``docs``, and ``catalog``
    keys listing removed paths (relative to *target_dir*).
    """
    catalog_path = target_dir / "nWave" / "framework-catalog.yaml"
    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        sys.exit(1)

    private_agents = _load_private_agents(catalog_path)
    if not private_agents:
        print("No private agents found — nothing to strip.")
        return {"agents": [], "skills": [], "docs": [], "catalog": []}

    removed: dict[str, list[str]] = {
        "agents": [],
        "skills": [],
        "docs": [],
        "catalog": [],
    }

    agents_dir = target_dir / "nWave" / "agents"
    skills_dir = target_dir / "nWave" / "skills"

    for agent_name in sorted(private_agents):
        # Agent file: nw-{name}.md
        agent_file = agents_dir / f"nw-{agent_name}.md"
        if agent_file.exists():
            agent_file.unlink()
            removed["agents"].append(str(agent_file.relative_to(target_dir)))

        # Reviewer agent file: nw-{name}-reviewer.md
        reviewer_file = agents_dir / f"nw-{agent_name}-reviewer.md"
        if reviewer_file.exists():
            reviewer_file.unlink()
            removed["agents"].append(str(reviewer_file.relative_to(target_dir)))

        # Skill directory: {name}/
        skill_dir = skills_dir / agent_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            removed["skills"].append(str(skill_dir.relative_to(target_dir)))

        # Reviewer skill directory: {name}-reviewer/ (rare but possible)
        reviewer_skill = skills_dir / f"{agent_name}-reviewer"
        if reviewer_skill.exists():
            shutil.rmtree(reviewer_skill)
            removed["skills"].append(str(reviewer_skill.relative_to(target_dir)))

    # Strip reference documentation
    removed["docs"] = _strip_reference_docs(target_dir, private_agents)

    # Strip catalog entries
    catalog_count = _strip_catalog(catalog_path, private_agents)
    if catalog_count:
        removed["catalog"].append(
            f"{catalog_count} entries from framework-catalog.yaml"
        )

    # Summary
    total = (
        len(removed["agents"])
        + len(removed["skills"])
        + len(removed["docs"])
        + catalog_count
    )
    print(f"Stripped {total} private items:")
    for category, paths in removed.items():
        for p in paths:
            print(f"  [{category}] {p}")

    return removed


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <target-dir>", file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"ERROR: not a directory: {target}", file=sys.stderr)
        sys.exit(1)

    strip(target)


if __name__ == "__main__":
    main()
