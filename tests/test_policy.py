"""Unit tests for mclip.policy — deterministic rule evaluation and verdicts."""

from __future__ import annotations

import pytest

from mclip.policy import PolicyVerdict, check_policy
from mclip.schema import (
    AbstractRule,
    DeterministicRule,
    DeterministicRuleKind,
    Policy,
)


# =========================================================================
# PolicyVerdict.to_dict
# =========================================================================


class TestPolicyVerdictSerialization:
    def test_allowed_minimal(self):
        v = PolicyVerdict(allowed=True)
        d = v.to_dict()
        assert d == {"allowed": True}
        assert "denied_reasons" not in d
        assert "advisory" not in d

    def test_denied_includes_reasons(self):
        v = PolicyVerdict(allowed=False, denied_reasons=["reason1", "reason2"])
        d = v.to_dict()
        assert d["allowed"] is False
        assert d["denied_reasons"] == ["reason1", "reason2"]

    def test_advisory_included_when_present(self):
        v = PolicyVerdict(allowed=True, advisory=["be careful"])
        d = v.to_dict()
        assert d["advisory"] == ["be careful"]

    def test_both_denied_and_advisory(self):
        v = PolicyVerdict(
            allowed=False,
            denied_reasons=["blocked"],
            advisory=["note"],
        )
        d = v.to_dict()
        assert d["allowed"] is False
        assert "blocked" in d["denied_reasons"]
        assert "note" in d["advisory"]


# =========================================================================
# deny_command rules
# =========================================================================


class TestDenyCommand:
    def test_exact_command_match(self, deny_push_policy: Policy):
        verdict = check_policy(deny_push_policy, ["push"])
        assert not verdict.allowed
        assert any("push" in r for r in verdict.denied_reasons)

    def test_command_with_trailing_args(self, deny_push_policy: Policy):
        verdict = check_policy(deny_push_policy, ["push", "origin", "main"])
        assert not verdict.allowed

    def test_unrelated_command_allowed(self, deny_push_policy: Policy):
        verdict = check_policy(deny_push_policy, ["status"])
        assert verdict.allowed

    def test_subcommand_path_blocked(self, mixed_policy: Policy):
        verdict = check_policy(mixed_policy, ["remote", "add", "origin", "url"])
        assert not verdict.allowed
        assert any("remote.add" in r for r in verdict.denied_reasons)

    def test_sibling_subcommand_allowed(self, mixed_policy: Policy):
        """remote.show should not be blocked by deny_command on remote.add."""
        verdict = check_policy(mixed_policy, ["remote", "show", "origin"])
        assert verdict.allowed or all(
            "remote.add" not in r for r in verdict.denied_reasons
        )

    def test_parent_command_does_not_block_children_unless_prefix(self):
        """Denying 'remote' blocks remote.add, remote.show, etc."""
        policy = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="remote",
                    description="All remote ops blocked",
                ),
            ],
            abstract_rules=[],
        )
        # "remote" alone
        v1 = check_policy(policy, ["remote"])
        assert not v1.allowed

        # "remote add" — starts with "remote."
        v2 = check_policy(policy, ["remote", "add", "origin"])
        assert not v2.allowed

    def test_empty_args(self, deny_push_policy: Policy):
        """Empty args should never match any deny_command."""
        verdict = check_policy(deny_push_policy, [])
        assert verdict.allowed

    def test_description_in_reason(self):
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="deploy",
                    description="Deployments frozen",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["deploy"])
        assert not v.allowed
        assert "Deployments frozen" in v.denied_reasons[0]

    def test_no_description_fallback(self):
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="deploy",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["deploy"])
        assert not v.allowed
        assert "is not allowed" in v.denied_reasons[0]


# =========================================================================
# deny_flag rules
# =========================================================================


class TestDenyFlag:
    def test_exact_flag_match(self, deny_force_flag_policy: Policy):
        verdict = check_policy(deny_force_flag_policy, ["push", "--force"])
        assert not verdict.allowed

    def test_flag_with_value_form(self, deny_force_flag_policy: Policy):
        """--force=true should match --force."""
        verdict = check_policy(deny_force_flag_policy, ["push", "--force=true"])
        assert not verdict.allowed

    def test_similar_flag_not_blocked(self, deny_force_flag_policy: Policy):
        """--force-with-lease should NOT be blocked by a rule on --force."""
        verdict = check_policy(
            deny_force_flag_policy, ["push", "--force-with-lease"]
        )
        assert verdict.allowed

    def test_flag_anywhere_in_args(self, deny_force_flag_policy: Policy):
        verdict = check_policy(
            deny_force_flag_policy, ["push", "origin", "--force", "main"]
        )
        assert not verdict.allowed

    def test_short_flag_not_matched_by_long_rule(self):
        """A rule on --force should not match -f."""
        policy = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_flag,
                    target="--force",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["push", "-f"])
        assert v.allowed

    def test_short_flag_rule(self):
        """Explicitly denying -f should block -f."""
        policy = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_flag,
                    target="-f",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["push", "-f"])
        assert not v.allowed

    def test_no_flags_present(self, deny_force_flag_policy: Policy):
        verdict = check_policy(deny_force_flag_policy, ["push", "origin"])
        assert verdict.allowed


# =========================================================================
# deny_pattern rules
# =========================================================================


class TestDenyPattern:
    def test_regex_matches_argument(self, deny_pattern_policy: Policy):
        verdict = check_policy(deny_pattern_policy, ["add", "/etc/passwd"])
        assert not verdict.allowed

    def test_regex_no_match(self, deny_pattern_policy: Policy):
        verdict = check_policy(deny_pattern_policy, ["add", "/home/user/file"])
        assert verdict.allowed

    def test_partial_regex_match(self):
        """Pattern uses search(), so partial match should trigger."""
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_pattern,
                    target="password",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["echo", "my_password_is_secret"])
        assert not v.allowed

    def test_invalid_regex_skipped(self):
        """An invalid regex pattern should be silently skipped, not crash."""
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_pattern,
                    target="[invalid",
                    description="bad regex",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["anything"])
        assert v.allowed

    def test_complex_regex(self):
        """Test a regex with alternation and anchoring."""
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_pattern,
                    target=r"^(production|staging)$",
                    description="Cannot target prod/staging",
                ),
            ],
            abstract_rules=[],
        )
        assert not check_policy(policy, ["deploy", "production"]).allowed
        assert not check_policy(policy, ["deploy", "staging"]).allowed
        assert check_policy(policy, ["deploy", "development"]).allowed
        assert check_policy(policy, ["deploy", "production-backup"]).allowed


# =========================================================================
# Abstract rules (advisory)
# =========================================================================


class TestAbstractRules:
    def test_advisory_present_when_allowed(self, abstract_only_policy: Policy):
        verdict = check_policy(abstract_only_policy, ["push"])
        assert verdict.allowed
        assert len(verdict.advisory) == 1
        assert "destructive" in verdict.advisory[0]

    def test_advisory_present_when_denied(self, mixed_policy: Policy):
        verdict = check_policy(mixed_policy, ["push"])
        assert not verdict.allowed
        assert len(verdict.advisory) == 2

    def test_no_advisory_when_empty(self, deny_push_policy: Policy):
        verdict = check_policy(deny_push_policy, ["push"])
        assert verdict.advisory == []


# =========================================================================
# Multiple rules interaction
# =========================================================================


class TestMultipleRules:
    def test_multiple_violations_all_reported(self, mixed_policy: Policy):
        """push --force should trigger both deny_command and deny_flag."""
        verdict = check_policy(mixed_policy, ["push", "--force"])
        assert not verdict.allowed
        assert len(verdict.denied_reasons) == 2

    def test_one_rule_fires_rest_dont(self, mixed_policy: Policy):
        """log --oneline triggers nothing."""
        verdict = check_policy(mixed_policy, ["log", "--oneline"])
        assert verdict.allowed

    def test_empty_policy_allows_everything(self, empty_policy: Policy):
        verdict = check_policy(empty_policy, ["push", "--force", "/etc/passwd"])
        assert verdict.allowed
        assert verdict.denied_reasons == []
        assert verdict.advisory == []


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_args_with_only_flags(self):
        """When args are all flags, command_path is empty — deny_command shouldn't match."""
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="push",
                ),
            ],
            abstract_rules=[],
        )
        v = check_policy(policy, ["--verbose", "--dry-run"])
        assert v.allowed

    def test_deny_command_does_not_substring_match(self):
        """Denying 'push' should not block 'pushd' or 'pusher'."""
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="push",
                ),
            ],
            abstract_rules=[],
        )
        assert check_policy(policy, ["pushing"]).allowed

    def test_many_rules_performance(self):
        """Smoke test: 1000 rules should still evaluate quickly."""
        rules = [
            DeterministicRule(
                kind=DeterministicRuleKind.deny_command,
                target=f"cmd{i}",
            )
            for i in range(1000)
        ]
        policy = Policy(cli_name="x", deterministic_rules=rules, abstract_rules=[])
        v = check_policy(policy, ["cmd999"])
        assert not v.allowed
        v2 = check_policy(policy, ["safe_cmd"])
        assert v2.allowed
