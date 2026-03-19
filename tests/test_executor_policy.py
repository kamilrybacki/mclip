"""Integration tests for executor + policy enforcement."""

from __future__ import annotations

import pytest

from mclip.executor import ExecutionError, ExecutionResult, execute
from mclip.schema import (
    AbstractRule,
    CLITool,
    DeterministicRule,
    DeterministicRuleKind,
    Policy,
)


@pytest.fixture
def echo_tool() -> CLITool:
    return CLITool(
        name="echo",
        path="/usr/bin/echo",
        description="echo",
        introspection_sources=["help"],
    )


@pytest.fixture
def blocking_policy() -> Policy:
    return Policy(
        cli_name="echo",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target="forbidden",
                description="This command is forbidden",
            ),
            DeterministicRule(
                kind=DeterministicRuleKind.deny_flag,
                target="--dangerous",
                description="Dangerous flag",
            ),
        ],
        abstract_rules=[],
    )


@pytest.fixture
def advisory_policy() -> Policy:
    return Policy(
        cli_name="echo",
        deterministic_rules=[],
        abstract_rules=[
            AbstractRule(description="Handle with care."),
            AbstractRule(description="Avoid large outputs."),
        ],
    )


@pytest.fixture
def combined_policy() -> Policy:
    return Policy(
        cli_name="echo",
        deterministic_rules=[
            DeterministicRule(
                kind=DeterministicRuleKind.deny_pattern,
                target=r"secret",
                description="No secrets in args",
            ),
        ],
        abstract_rules=[
            AbstractRule(description="Think before you echo."),
        ],
    )


class TestExecutorPolicyBlocking:
    """Deterministic rules should raise ExecutionError before subprocess spawn."""

    def test_deny_command_blocks_execution(
        self, echo_tool: CLITool, blocking_policy: Policy
    ):
        with pytest.raises(ExecutionError, match="Policy violation"):
            execute(echo_tool, ["forbidden", "arg"], policy=blocking_policy)

    def test_deny_flag_blocks_execution(
        self, echo_tool: CLITool, blocking_policy: Policy
    ):
        with pytest.raises(ExecutionError, match="Dangerous flag"):
            execute(echo_tool, ["hello", "--dangerous"], policy=blocking_policy)

    def test_deny_pattern_blocks_execution(
        self, echo_tool: CLITool, combined_policy: Policy
    ):
        with pytest.raises(ExecutionError, match="No secrets"):
            execute(echo_tool, ["my_secret_value"], policy=combined_policy)

    def test_allowed_command_executes(
        self, echo_tool: CLITool, blocking_policy: Policy
    ):
        result = execute(echo_tool, ["hello", "world"], policy=blocking_policy)
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    def test_no_policy_allows_everything(self, echo_tool: CLITool):
        result = execute(echo_tool, ["forbidden"], policy=None)
        assert result.exit_code == 0
        assert "forbidden" in result.stdout


class TestExecutorPolicyAdvisory:
    """Abstract rules should appear in stderr but not block execution."""

    def test_advisory_appended_to_stderr(
        self, echo_tool: CLITool, advisory_policy: Policy
    ):
        result = execute(echo_tool, ["hello"], policy=advisory_policy)
        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert "[mclip policy advisory]" in result.stderr
        assert "Handle with care." in result.stderr
        assert "Avoid large outputs." in result.stderr

    def test_advisory_appended_after_real_stderr(self, echo_tool: CLITool):
        """When the command itself writes to stderr, advisory is appended."""
        # /usr/bin/echo won't write to stderr normally, so use a tool that does.
        false_tool = CLITool(
            name="cat",
            path="/bin/cat",
            description="cat",
            introspection_sources=[],
        )
        policy = Policy(
            cli_name="cat",
            deterministic_rules=[],
            abstract_rules=[AbstractRule(description="Advisory note.")],
        )
        # cat a nonexistent file to produce stderr
        result = execute(false_tool, ["/nonexistent_file_xyz"], policy=policy, timeout=5)
        assert result.exit_code != 0
        assert "No such file" in result.stderr
        assert "Advisory note." in result.stderr

    def test_no_advisory_when_no_abstract_rules(
        self, echo_tool: CLITool, blocking_policy: Policy
    ):
        result = execute(echo_tool, ["safe"], policy=blocking_policy)
        assert "[mclip policy advisory]" not in result.stderr


class TestExecutorPolicyCombined:
    """Combined deterministic + advisory rules."""

    def test_blocked_never_reaches_advisory(
        self, echo_tool: CLITool, combined_policy: Policy
    ):
        """If deterministic rule blocks, advisory is irrelevant (error raised)."""
        with pytest.raises(ExecutionError):
            execute(echo_tool, ["secret_value"], policy=combined_policy)

    def test_allowed_gets_advisory(
        self, echo_tool: CLITool, combined_policy: Policy
    ):
        result = execute(echo_tool, ["safe_value"], policy=combined_policy)
        assert result.exit_code == 0
        assert "Think before you echo." in result.stderr

    def test_execution_result_to_dict_includes_advisory(
        self, echo_tool: CLITool, advisory_policy: Policy
    ):
        result = execute(echo_tool, ["test"], policy=advisory_policy)
        d = result.to_dict()
        assert "advisory" in d["stderr"].lower()
