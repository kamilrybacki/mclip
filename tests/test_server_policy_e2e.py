"""End-to-end tests for policy MCP tools in the server.

These tests exercise the full stack: server tool functions → registry → policy
enforcement → executor, using a temporary database and real binaries.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# We call the server tool functions directly (they return JSON strings).
from mclip import server
from mclip.registry import Registry


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path):
    """Replace the global registry with a temp-database-backed one for each test."""
    db_path = tmp_path / "e2e_test.db"
    reg = Registry(db_path)
    with patch.object(server, "_registry", reg):
        # Also patch _get_registry so lazy init doesn't override our reg.
        with patch.object(server, "_get_registry", return_value=reg):
            yield reg
    reg.close()


@pytest.fixture
def registered_echo(isolated_registry: Registry):
    """Register /usr/bin/echo in the test registry."""
    from mclip.schema import CLITool

    tool = CLITool(
        name="echo",
        path="/usr/bin/echo",
        description="echo - display a line of text",
        introspection_sources=["help"],
    )
    isolated_registry.register(tool)
    return tool


# =========================================================================
# set_policy tool
# =========================================================================


class TestSetPolicyTool:
    def test_set_deterministic_rules(self, registered_echo):
        result = json.loads(server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "forbidden", "description": "nope"},
                {"kind": "deny_flag", "target": "--evil"},
            ],
        ))
        assert result["status"] == "policy_set"
        assert result["deterministic_rules"] == 2
        assert result["abstract_rules"] == 0

    def test_set_abstract_rules(self, registered_echo):
        result = json.loads(server.set_policy(
            binary_name="echo",
            abstract_rules=["Be careful.", "No loud echoing."],
        ))
        assert result["status"] == "policy_set"
        assert result["abstract_rules"] == 2

    def test_set_mixed_rules(self, registered_echo):
        result = json.loads(server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_pattern", "target": "secret", "description": "no secrets"},
            ],
            abstract_rules=["Think twice."],
        ))
        assert result["status"] == "policy_set"
        assert result["deterministic_rules"] == 1
        assert result["abstract_rules"] == 1

    def test_set_policy_replaces_existing(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "a"},
                {"kind": "deny_command", "target": "b"},
            ],
        )
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_flag", "target": "--x"},
            ],
        )
        result = json.loads(server.get_policy("echo"))
        assert len(result["deterministic_rules"]) == 1
        assert result["deterministic_rules"][0]["kind"] == "deny_flag"

    def test_set_policy_unregistered_tool(self):
        result = json.loads(server.set_policy(
            binary_name="nonexistent",
            deterministic_rules=[{"kind": "deny_command", "target": "x"}],
        ))
        assert "error" in result

    def test_set_policy_invalid_kind(self, registered_echo):
        result = json.loads(server.set_policy(
            binary_name="echo",
            deterministic_rules=[{"kind": "deny_universe", "target": "x"}],
        ))
        assert "error" in result
        assert "Invalid" in result["error"]

    def test_set_policy_missing_target(self, registered_echo):
        result = json.loads(server.set_policy(
            binary_name="echo",
            deterministic_rules=[{"kind": "deny_command"}],
        ))
        assert "error" in result

    def test_set_empty_policy(self, registered_echo):
        result = json.loads(server.set_policy(binary_name="echo"))
        assert result["status"] == "policy_set"
        assert result["deterministic_rules"] == 0
        assert result["abstract_rules"] == 0


# =========================================================================
# get_policy tool
# =========================================================================


class TestGetPolicyTool:
    def test_get_existing_policy(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "x", "description": "block x"},
            ],
            abstract_rules=["advisory"],
        )
        result = json.loads(server.get_policy("echo"))
        assert result["cli_name"] == "echo"
        assert len(result["deterministic_rules"]) == 1
        assert result["deterministic_rules"][0]["target"] == "x"
        assert result["abstract_rules"][0]["description"] == "advisory"

    def test_get_no_policy(self, registered_echo):
        result = json.loads(server.get_policy("echo"))
        assert "message" in result
        assert "No policy" in result["message"]

    def test_get_policy_unregistered_tool(self):
        result = json.loads(server.get_policy("nonexistent"))
        assert "error" in result


# =========================================================================
# remove_policy tool
# =========================================================================


class TestRemovePolicyTool:
    def test_remove_existing_policy(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[{"kind": "deny_command", "target": "x"}],
        )
        result = json.loads(server.remove_policy("echo"))
        assert result["status"] == "policy_removed"

        # Verify it's gone
        after = json.loads(server.get_policy("echo"))
        assert "message" in after

    def test_remove_nonexistent_policy(self, registered_echo):
        result = json.loads(server.remove_policy("echo"))
        assert "error" in result


# =========================================================================
# run_command with policy enforcement (E2E)
# =========================================================================


class TestRunCommandWithPolicy:
    def test_allowed_command_succeeds(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "forbidden"},
            ],
        )
        result = json.loads(server.run_command("echo", ["hello"]))
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    def test_denied_command_returns_error(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "forbidden", "description": "blocked"},
            ],
        )
        result = json.loads(server.run_command("echo", ["forbidden", "arg"]))
        assert "error" in result
        assert "Policy violation" in result["error"]

    def test_denied_flag_returns_error(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_flag", "target": "--evil", "description": "evil flag"},
            ],
        )
        result = json.loads(server.run_command("echo", ["hello", "--evil"]))
        assert "error" in result
        assert "evil flag" in result["error"]

    def test_denied_pattern_returns_error(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_pattern", "target": "password", "description": "no passwords"},
            ],
        )
        result = json.loads(server.run_command("echo", ["my_password"]))
        assert "error" in result
        assert "no passwords" in result["error"]

    def test_advisory_in_output(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            abstract_rules=["Handle echoes carefully."],
        )
        result = json.loads(server.run_command("echo", ["test"]))
        assert result["exit_code"] == 0
        assert "Handle echoes carefully." in result["stderr"]

    def test_no_policy_allows_all(self, registered_echo):
        result = json.loads(server.run_command("echo", ["anything"]))
        assert result["exit_code"] == 0
        assert "anything" in result["stdout"]

    def test_multiple_violations_in_error(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "bad", "description": "cmd blocked"},
                {"kind": "deny_flag", "target": "--bad", "description": "flag blocked"},
            ],
        )
        result = json.loads(server.run_command("echo", ["bad", "--bad"]))
        assert "error" in result
        assert "cmd blocked" in result["error"]
        assert "flag blocked" in result["error"]


# =========================================================================
# inspect_cli with policy (E2E)
# =========================================================================


class TestInspectCliWithPolicy:
    def test_policy_included_in_inspection(self, registered_echo):
        server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "x", "description": "block x"},
            ],
            abstract_rules=["Be safe."],
        )
        result = json.loads(server.inspect_cli("echo"))
        assert "policy" in result
        assert result["policy"]["cli_name"] == "echo"
        assert len(result["policy"]["deterministic_rules"]) == 1
        assert len(result["policy"]["abstract_rules"]) == 1

    def test_no_policy_key_when_none_set(self, registered_echo):
        result = json.loads(server.inspect_cli("echo"))
        assert "policy" not in result

    def test_policy_visible_after_set_and_inspect_cycle(self, registered_echo):
        # No policy initially
        r1 = json.loads(server.inspect_cli("echo"))
        assert "policy" not in r1

        # Set policy
        server.set_policy(
            binary_name="echo",
            abstract_rules=["Watch out."],
        )

        # Now visible
        r2 = json.loads(server.inspect_cli("echo"))
        assert "policy" in r2
        assert r2["policy"]["abstract_rules"][0]["description"] == "Watch out."

        # Remove policy
        server.remove_policy("echo")

        # Gone again
        r3 = json.loads(server.inspect_cli("echo"))
        assert "policy" not in r3


# =========================================================================
# Full lifecycle E2E
# =========================================================================


class TestFullPolicyLifecycle:
    def test_register_set_policy_run_inspect_remove(self, registered_echo):
        """Full lifecycle: set policy → run allowed → run denied → inspect → remove → run again."""
        # 1. Set restrictive policy
        set_result = json.loads(server.set_policy(
            binary_name="echo",
            deterministic_rules=[
                {"kind": "deny_command", "target": "banned", "description": "banned cmd"},
                {"kind": "deny_flag", "target": "--nope", "description": "nope flag"},
            ],
            abstract_rules=["Use echo responsibly."],
        ))
        assert set_result["status"] == "policy_set"

        # 2. Run allowed command
        ok = json.loads(server.run_command("echo", ["hello"]))
        assert ok["exit_code"] == 0
        assert "Use echo responsibly." in ok["stderr"]

        # 3. Run denied command
        denied = json.loads(server.run_command("echo", ["banned"]))
        assert "error" in denied
        assert "banned cmd" in denied["error"]

        # 4. Run denied flag
        denied_flag = json.loads(server.run_command("echo", ["ok", "--nope"]))
        assert "error" in denied_flag

        # 5. Inspect shows policy
        inspection = json.loads(server.inspect_cli("echo"))
        assert "policy" in inspection
        assert len(inspection["policy"]["deterministic_rules"]) == 2

        # 6. Get policy directly
        policy = json.loads(server.get_policy("echo"))
        assert policy["cli_name"] == "echo"

        # 7. Remove policy
        rm = json.loads(server.remove_policy("echo"))
        assert rm["status"] == "policy_removed"

        # 8. Now the denied command works
        after = json.loads(server.run_command("echo", ["banned"]))
        assert after["exit_code"] == 0
        assert "banned" in after["stdout"]

        # 9. Inspect no longer shows policy
        inspection2 = json.loads(server.inspect_cli("echo"))
        assert "policy" not in inspection2

    def test_policy_across_multiple_tools(self, isolated_registry):
        """Independent policies for different tools."""
        from mclip.schema import CLITool

        echo = CLITool(name="echo", path="/usr/bin/echo", description="echo", introspection_sources=[])
        true_tool = CLITool(name="true", path="/usr/bin/true", description="true", introspection_sources=[])
        isolated_registry.register(echo)
        isolated_registry.register(true_tool)

        server.set_policy(
            binary_name="echo",
            deterministic_rules=[{"kind": "deny_flag", "target": "--no"}],
        )
        server.set_policy(
            binary_name="true",
            abstract_rules=["True is always true."],
        )

        # echo with --no is blocked
        r1 = json.loads(server.run_command("echo", ["--no"]))
        assert "error" in r1

        # true runs fine (only advisory)
        r2 = json.loads(server.run_command("true", []))
        assert r2["exit_code"] == 0
        assert "True is always true." in r2["stderr"]

        # Removing echo's policy doesn't affect true's
        server.remove_policy("echo")
        r3 = json.loads(server.run_command("echo", ["--no"]))
        assert r3["exit_code"] == 0  # No longer blocked

        r4 = json.loads(server.run_command("true", []))
        assert "True is always true." in r4["stderr"]  # Still advisory
