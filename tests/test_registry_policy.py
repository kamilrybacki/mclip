"""Integration tests for policy persistence in the Registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from mclip.registry import Registry
from mclip.schema import (
    AbstractRule,
    CLITool,
    DeterministicRule,
    DeterministicRuleKind,
    Policy,
)


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    reg = Registry(tmp_path / "test.db")
    yield reg
    reg.close()


@pytest.fixture
def sample_tool() -> CLITool:
    return CLITool(
        name="git",
        path="/usr/bin/git",
        description="git",
        introspection_sources=["help"],
    )


@pytest.fixture
def sample_policy() -> Policy:
    return Policy(
        cli_name="git",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target="push",
                description="no pushing",
            ),
            DeterministicRule(
                kind=DeterministicRuleKind.deny_flag,
                target="--force",
            ),
        ],
        abstract_rules=[
            AbstractRule(description="Be careful."),
        ],
    )


class TestPolicyPersistence:
    def test_set_and_get_policy(
        self, registry: Registry, sample_tool: CLITool, sample_policy: Policy
    ):
        registry.register(sample_tool)
        registry.set_policy(sample_policy)

        loaded = registry.get_policy("git")
        assert loaded is not None
        assert loaded.cli_name == "git"
        assert len(loaded.deterministic_rules) == 2
        assert len(loaded.abstract_rules) == 1
        assert loaded.deterministic_rules[0].target == "push"

    def test_get_nonexistent_policy(self, registry: Registry):
        assert registry.get_policy("nonexistent") is None

    def test_set_policy_upsert(
        self, registry: Registry, sample_tool: CLITool, sample_policy: Policy
    ):
        registry.register(sample_tool)
        registry.set_policy(sample_policy)

        # Update with new rules
        updated = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="reset",
                    description="no reset",
                ),
            ],
            abstract_rules=[],
        )
        registry.set_policy(updated)

        loaded = registry.get_policy("git")
        assert loaded is not None
        assert len(loaded.deterministic_rules) == 1
        assert loaded.deterministic_rules[0].target == "reset"
        assert loaded.abstract_rules == []

    def test_remove_policy(
        self, registry: Registry, sample_tool: CLITool, sample_policy: Policy
    ):
        registry.register(sample_tool)
        registry.set_policy(sample_policy)
        assert registry.get_policy("git") is not None

        removed = registry.remove_policy("git")
        assert removed is True
        assert registry.get_policy("git") is None

    def test_remove_nonexistent_policy(self, registry: Registry):
        assert registry.remove_policy("nosuch") is False

    def test_remove_policy_twice(
        self, registry: Registry, sample_tool: CLITool, sample_policy: Policy
    ):
        registry.register(sample_tool)
        registry.set_policy(sample_policy)
        assert registry.remove_policy("git") is True
        assert registry.remove_policy("git") is False

    def test_policy_survives_reconnect(
        self, tmp_path: Path, sample_tool: CLITool, sample_policy: Policy
    ):
        """Policy should survive closing and re-opening the database."""
        db_path = tmp_path / "persist.db"

        reg1 = Registry(db_path)
        reg1.register(sample_tool)
        reg1.set_policy(sample_policy)
        reg1.close()

        reg2 = Registry(db_path)
        loaded = reg2.get_policy("git")
        assert loaded is not None
        assert loaded.cli_name == "git"
        assert len(loaded.deterministic_rules) == 2
        reg2.close()

    def test_multiple_tools_separate_policies(self, registry: Registry):
        """Each tool gets its own independent policy."""
        t1 = CLITool(name="git", path="/usr/bin/git", description="git", introspection_sources=[])
        t2 = CLITool(name="docker", path="/usr/bin/docker", description="docker", introspection_sources=[])
        registry.register(t1)
        registry.register(t2)

        p1 = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(kind=DeterministicRuleKind.deny_command, target="push"),
            ],
            abstract_rules=[],
        )
        p2 = Policy(
            cli_name="docker",
            deterministic_rules=[
                DeterministicRule(kind=DeterministicRuleKind.deny_command, target="rm"),
            ],
            abstract_rules=[AbstractRule(description="docker advisory")],
        )
        registry.set_policy(p1)
        registry.set_policy(p2)

        loaded1 = registry.get_policy("git")
        loaded2 = registry.get_policy("docker")
        assert loaded1 is not None
        assert loaded2 is not None
        assert loaded1.deterministic_rules[0].target == "push"
        assert loaded2.deterministic_rules[0].target == "rm"
        assert len(loaded2.abstract_rules) == 1

    def test_removing_tool_does_not_orphan_policy_with_fk(self, registry: Registry):
        """Removing a tool via registry.remove should also remove its policy
        if foreign keys are enforced."""
        tool = CLITool(name="test", path="/usr/bin/test", description="test", introspection_sources=[])
        registry.register(tool)
        policy = Policy(
            cli_name="test",
            deterministic_rules=[],
            abstract_rules=[AbstractRule(description="note")],
        )
        registry.set_policy(policy)

        # Enable FK enforcement (SQLite requires explicit pragma)
        registry._conn.execute("PRAGMA foreign_keys = ON")
        registry.remove("test")

        # Policy should be gone due to ON DELETE CASCADE
        assert registry.get_policy("test") is None


class TestPolicyJsonIntegrity:
    """Verify that complex rules survive JSON serialization in SQLite."""

    def test_special_characters_in_pattern(self, registry: Registry):
        tool = CLITool(name="x", path="/bin/x", description="x", introspection_sources=[])
        registry.register(tool)

        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_pattern,
                    target=r"^(rm|del)\s+(-rf|-fr)\s+/",
                    description="Block recursive force delete at root",
                ),
            ],
            abstract_rules=[
                AbstractRule(description='Quote test: "hello" and \'world\''),
            ],
        )
        registry.set_policy(policy)
        loaded = registry.get_policy("x")
        assert loaded is not None
        assert loaded.deterministic_rules[0].target == r"^(rm|del)\s+(-rf|-fr)\s+/"
        assert "\"hello\"" in loaded.abstract_rules[0].description

    def test_unicode_in_rules(self, registry: Registry):
        tool = CLITool(name="u", path="/bin/u", description="u", introspection_sources=[])
        registry.register(tool)

        policy = Policy(
            cli_name="u",
            deterministic_rules=[],
            abstract_rules=[
                AbstractRule(description="Não modifique armazenamento remoto. 远程存储"),
            ],
        )
        registry.set_policy(policy)
        loaded = registry.get_policy("u")
        assert loaded is not None
        assert "远程存储" in loaded.abstract_rules[0].description
