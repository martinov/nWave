"""Unit tests for the shared agent_catalog module.

Tests the public/private agent filtering logic that prevents
private agents and skills from leaking into public installations.
"""

from pathlib import Path

import pytest

from scripts.shared.agent_catalog import (
    is_public_agent,
    is_public_skill,
    load_public_agents,
)


# ---------------------------------------------------------------------------
# Real catalog path for integration-style unit tests
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
NWAVE_DIR = PROJECT_ROOT / "nWave"


class TestLoadPublicAgents:
    """Tests for load_public_agents using the real framework-catalog.yaml."""

    def test_returns_nonempty_set_from_real_catalog(self):
        result = load_public_agents(NWAVE_DIR)
        assert len(result) > 0, "Should load at least one public agent"

    def test_excludes_known_private_agents(self):
        result = load_public_agents(NWAVE_DIR)
        private_agents = {
            "workshopper",
            "workshopper-reviewer",
            "tutorialist",
            "tutorialist-reviewer",
            "business-discoverer",
            "business-reviewer",
            "deal-closer",
            "outreach-writer",
            "ux-designer",
        }
        leaked = private_agents & result
        assert leaked == set(), f"Private agents leaked into public set: {leaked}"

    def test_includes_known_public_agents(self):
        result = load_public_agents(NWAVE_DIR)
        expected_public = {
            "software-crafter",
            "product-owner",
            "solution-architect",
            "researcher",
            "platform-architect",
        }
        missing = expected_public - result
        assert missing == set(), f"Expected public agents missing: {missing}"

    def test_returns_empty_set_when_catalog_missing(self, tmp_path):
        result = load_public_agents(tmp_path)
        assert result == set()

    def test_returns_empty_set_when_yaml_invalid(self, tmp_path):
        catalog = tmp_path / "framework-catalog.yaml"
        catalog.write_text("{{invalid yaml: [")
        result = load_public_agents(tmp_path)
        assert result == set()


class TestIsPublicAgent:
    """Tests for is_public_agent file-name matching."""

    @pytest.mark.parametrize(
        "filename",
        [
            "nw-software-crafter.md",
            "nw-product-owner.md",
            "nw-researcher.md",
        ],
    )
    def test_public_agent_returns_true(self, filename):
        public_agents = {"software-crafter", "product-owner", "researcher"}
        assert is_public_agent(filename, public_agents) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "nw-workshopper.md",
            "nw-business-discoverer.md",
            "nw-deal-closer.md",
            "nw-ux-designer.md",
        ],
    )
    def test_private_agent_returns_false(self, filename):
        public_agents = {"software-crafter", "product-owner"}
        assert is_public_agent(filename, public_agents) is False

    def test_reviewer_of_public_agent_returns_true(self):
        public_agents = {"software-crafter"}
        assert is_public_agent("nw-software-crafter-reviewer.md", public_agents) is True

    def test_reviewer_of_private_agent_returns_false(self):
        public_agents = {"software-crafter"}
        assert is_public_agent("nw-workshopper-reviewer.md", public_agents) is False

    def test_empty_public_agents_returns_true_for_all(self):
        assert is_public_agent("nw-workshopper.md", set()) is True
        assert is_public_agent("nw-software-crafter.md", set()) is True


class TestIsPublicSkill:
    """Tests for is_public_skill directory-name matching."""

    @pytest.mark.parametrize(
        "dirname",
        [
            "software-crafter",
            "product-owner",
            "researcher",
        ],
    )
    def test_public_skill_returns_true(self, dirname):
        public_agents = {"software-crafter", "product-owner", "researcher"}
        assert is_public_skill(dirname, public_agents) is True

    @pytest.mark.parametrize(
        "dirname",
        [
            "workshopper",
            "business-discoverer",
            "deal-closer",
        ],
    )
    def test_private_skill_returns_false(self, dirname):
        public_agents = {"software-crafter", "product-owner"}
        assert is_public_skill(dirname, public_agents) is False

    def test_common_always_public(self):
        public_agents = {"software-crafter"}
        assert is_public_skill("common", public_agents) is True

    def test_common_public_even_with_nonempty_set(self):
        # "common" should be public regardless of what's in the set
        public_agents = {"only-one-agent"}
        assert is_public_skill("common", public_agents) is True

    def test_reviewer_skill_inherits_from_base(self):
        public_agents = {"software-crafter"}
        assert is_public_skill("software-crafter-reviewer", public_agents) is True

    def test_reviewer_of_private_skill_returns_false(self):
        public_agents = {"software-crafter"}
        assert is_public_skill("workshopper-reviewer", public_agents) is False

    def test_empty_public_agents_returns_true_for_all(self):
        assert is_public_skill("workshopper", set()) is True
        assert is_public_skill("software-crafter", set()) is True
