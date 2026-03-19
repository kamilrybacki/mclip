"""Shared fixtures for mclip policy tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mclip.registry import Registry
from mclip.schema import (
    AbstractRule,
    CLITool,
    Command,
    DeterministicRule,
    DeterministicRuleKind,
    Flag,
    Policy,
)


# ---------------------------------------------------------------------------
# Reusable schema fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def echo_tool() -> CLITool:
    """A minimal CLITool pointing at /usr/bin/echo (safe for execution tests)."""
    return CLITool(
        name="echo",
        path="/usr/bin/echo",
        version="1.0",
        description="echo - display a line of text",
        global_flags=[],
        commands=[],
        introspection_sources=["help"],
    )


@pytest.fixture
def git_tool() -> CLITool:
    """A CLITool mimicking git with a realistic command tree (not executed)."""
    return CLITool(
        name="git",
        path="/usr/bin/git",
        version="2.43.0",
        description="the stupid content tracker",
        global_flags=[
            Flag(name="--version"),
            Flag(name="--help"),
        ],
        commands=[
            Command(
                name="push",
                description="Update remote refs along with associated objects",
                flags=[
                    Flag(name="--force", short="-f", description="force push"),
                    Flag(name="--force-with-lease"),
                    Flag(name="--set-upstream", short="-u"),
                ],
            ),
            Command(
                name="pull",
                description="Fetch from and integrate with another repository",
                flags=[Flag(name="--rebase")],
            ),
            Command(
                name="remote",
                description="Manage set of tracked repositories",
                subcommands=[
                    Command(name="add", description="Add a remote"),
                    Command(name="remove", description="Remove a remote"),
                    Command(name="show", description="Show info about a remote"),
                ],
            ),
            Command(name="status", description="Show the working tree status"),
            Command(name="log", description="Show commit logs"),
        ],
        introspection_sources=["help", "man"],
    )


# ---------------------------------------------------------------------------
# Policy fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def deny_push_policy() -> Policy:
    """Policy that blocks 'push' commands."""
    return Policy(
        cli_name="git",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target="push",
                description="Pushing is disabled for safety",
            ),
        ],
        abstract_rules=[],
    )


@pytest.fixture
def deny_force_flag_policy() -> Policy:
    """Policy that blocks the --force flag."""
    return Policy(
        cli_name="git",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_flag,
                target="--force",
                description="Force operations are prohibited",
            ),
        ],
        abstract_rules=[],
    )


@pytest.fixture
def deny_pattern_policy() -> Policy:
    """Policy that blocks arguments matching a dangerous path pattern."""
    return Policy(
        cli_name="git",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_pattern,
                target=r"^/etc/",
                description="Access to /etc/ is forbidden",
            ),
        ],
        abstract_rules=[],
    )


@pytest.fixture
def mixed_policy() -> Policy:
    """Policy with deterministic + abstract rules combined."""
    return Policy(
        cli_name="git",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target="push",
                description="No pushing",
            ),
            DeterministicRule(
                kind=DeterministicRuleKind.deny_flag,
                target="--force",
                description="No force",
            ),
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target="remote.add",
                description="No adding remotes",
            ),
        ],
        abstract_rules=[
            AbstractRule(description="Do not modify remote storage."),
            AbstractRule(description="Prefer read-only operations."),
        ],
    )


@pytest.fixture
def abstract_only_policy() -> Policy:
    """Policy with only abstract (advisory) rules."""
    return Policy(
        cli_name="git",
        deterministic_rules=[],
        abstract_rules=[
            AbstractRule(description="Be careful with destructive operations."),
        ],
    )


@pytest.fixture
def empty_policy() -> Policy:
    """Policy with no rules at all."""
    return Policy(cli_name="git", deterministic_rules=[], abstract_rules=[])


# ---------------------------------------------------------------------------
# Registry fixture (temp database)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_registry(tmp_path: Path) -> Registry:
    """A registry backed by a temporary SQLite database."""
    db_path = tmp_path / "test_registry.db"
    reg = Registry(db_path)
    yield reg
    reg.close()
