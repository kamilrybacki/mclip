"""Unit tests for policy-related schema models — serialization & validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mclip.schema import (
    AbstractRule,
    DeterministicRule,
    DeterministicRuleKind,
    Policy,
)


class TestDeterministicRuleKind:
    def test_enum_values(self):
        assert DeterministicRuleKind.deny_command.value == "deny_command"
        assert DeterministicRuleKind.deny_flag.value == "deny_flag"
        assert DeterministicRuleKind.deny_pattern.value == "deny_pattern"

    def test_from_string(self):
        assert DeterministicRuleKind("deny_command") == DeterministicRuleKind.deny_command

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            DeterministicRuleKind("deny_everything")


class TestDeterministicRule:
    def test_basic_creation(self):
        rule = DeterministicRule(
            kind=DeterministicRuleKind.deny_command,
            target="push",
            description="no pushing",
        )
        assert rule.kind == DeterministicRuleKind.deny_command
        assert rule.target == "push"
        assert rule.description == "no pushing"

    def test_default_description(self):
        rule = DeterministicRule(
            kind=DeterministicRuleKind.deny_flag,
            target="--force",
        )
        assert rule.description == ""

    def test_json_round_trip(self):
        rule = DeterministicRule(
            kind=DeterministicRuleKind.deny_pattern,
            target=r"^/etc/",
            description="block /etc",
        )
        data = json.loads(rule.model_dump_json())
        restored = DeterministicRule.model_validate(data)
        assert restored == rule

    def test_missing_kind_raises(self):
        with pytest.raises(ValidationError):
            DeterministicRule(target="push")  # type: ignore[call-arg]

    def test_missing_target_raises(self):
        with pytest.raises(ValidationError):
            DeterministicRule(kind=DeterministicRuleKind.deny_command)  # type: ignore[call-arg]


class TestAbstractRule:
    def test_basic_creation(self):
        rule = AbstractRule(description="Be careful")
        assert rule.description == "Be careful"

    def test_json_round_trip(self):
        rule = AbstractRule(description="Do not modify remote storage.")
        data = json.loads(rule.model_dump_json())
        restored = AbstractRule.model_validate(data)
        assert restored == rule

    def test_missing_description_raises(self):
        with pytest.raises(ValidationError):
            AbstractRule()  # type: ignore[call-arg]


class TestPolicy:
    def test_basic_creation(self):
        policy = Policy(
            cli_name="git",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="push",
                ),
            ],
            abstract_rules=[
                AbstractRule(description="advisory msg"),
            ],
        )
        assert policy.cli_name == "git"
        assert len(policy.deterministic_rules) == 1
        assert len(policy.abstract_rules) == 1

    def test_empty_rules(self):
        policy = Policy(cli_name="test")
        assert policy.deterministic_rules == []
        assert policy.abstract_rules == []

    def test_json_round_trip(self):
        policy = Policy(
            cli_name="kubectl",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_command,
                    target="delete",
                    description="no deletions",
                ),
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_flag,
                    target="--all-namespaces",
                ),
            ],
            abstract_rules=[
                AbstractRule(description="Prefer read-only operations."),
            ],
        )
        json_str = policy.model_dump_json()
        restored = Policy.model_validate_json(json_str)
        assert restored == policy
        assert restored.deterministic_rules[0].kind == DeterministicRuleKind.deny_command

    def test_model_dump_structure(self):
        policy = Policy(
            cli_name="x",
            deterministic_rules=[
                DeterministicRule(
                    kind=DeterministicRuleKind.deny_flag,
                    target="--rm",
                ),
            ],
            abstract_rules=[
                AbstractRule(description="advisory"),
            ],
        )
        d = policy.model_dump()
        assert d["cli_name"] == "x"
        assert d["deterministic_rules"][0]["kind"] == "deny_flag"
        assert d["deterministic_rules"][0]["target"] == "--rm"
        assert d["abstract_rules"][0]["description"] == "advisory"
