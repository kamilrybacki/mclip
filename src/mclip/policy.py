"""Policy enforcement — evaluates deterministic rules against command invocations.

Provides the :func:`check_policy` function that tests a proposed command
against a :class:`~mclip.schema.Policy`. Deterministic rules are evaluated
here; abstract rules are collected and returned so the caller can surface
them to the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mclip.schema import DeterministicRuleKind, Policy


@dataclass
class PolicyVerdict:
    """Result of evaluating a command against a policy.

    :param allowed: ``True`` if no deterministic rule blocked the command.
    :param denied_reasons: Explanations for each deterministic rule that
        triggered. Empty when ``allowed`` is ``True``.
    :param advisory: Natural-language abstract rules that apply. These are
        informational — the command was not blocked on their account.
    """

    allowed: bool
    denied_reasons: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize the verdict for JSON transport.

        :returns: Dictionary with ``allowed``, ``denied_reasons``, and
            ``advisory`` keys.
        :rtype: dict
        """
        d: dict = {"allowed": self.allowed}
        if self.denied_reasons:
            d["denied_reasons"] = self.denied_reasons
        if self.advisory:
            d["advisory"] = self.advisory
        return d


def check_policy(policy: Policy, args: list[str]) -> PolicyVerdict:
    """Evaluate a command's arguments against a policy.

    Checks each deterministic rule in order. A single match is sufficient
    to deny the command. All abstract rules are always collected into the
    advisory list regardless of the deterministic outcome.

    :param policy: The policy to evaluate against.
    :param args: The argument list that would be passed to the CLI binary
        (e.g. ``["push", "--force", "origin", "main"]``).
    :returns: A verdict indicating whether the command is allowed and any
        advisory messages.
    :rtype: PolicyVerdict
    """
    denied: list[str] = []

    # Build a command path from leading non-flag arguments for deny_command matching.
    # e.g. ["remote", "add", "--verbose", "origin"] → "remote.add"
    command_parts: list[str] = []
    for arg in args:
        if arg.startswith("-"):
            break
        command_parts.append(arg)

    command_path = ".".join(command_parts)

    for rule in policy.deterministic_rules:
        if rule.kind == DeterministicRuleKind.deny_command:
            # Match if the invoked command path starts with or equals the rule target.
            # "push" matches ["push", ...]; "remote.add" matches ["remote", "add", ...].
            if command_path == rule.target or command_path.startswith(rule.target + "."):
                reason = f"Command '{command_path}' denied by rule: {rule.description}" if rule.description else f"Command '{command_path}' is not allowed"
                denied.append(reason)

        elif rule.kind == DeterministicRuleKind.deny_flag:
            target_flag = rule.target
            for arg in args:
                # Match exact flag or flag=value forms (e.g. --force-with-lease matches --force-with-lease)
                if arg == target_flag or arg.startswith(target_flag + "="):
                    reason = f"Flag '{target_flag}' denied by rule: {rule.description}" if rule.description else f"Flag '{target_flag}' is not allowed"
                    denied.append(reason)
                    break

        elif rule.kind == DeterministicRuleKind.deny_pattern:
            try:
                pattern = re.compile(rule.target)
            except re.error:
                # Skip invalid patterns rather than crashing.
                continue
            for arg in args:
                if pattern.search(arg):
                    reason = f"Argument '{arg}' matched denied pattern /{rule.target}/: {rule.description}" if rule.description else f"Argument '{arg}' matched denied pattern /{rule.target}/"
                    denied.append(reason)
                    break

    advisory = [r.description for r in policy.abstract_rules]

    return PolicyVerdict(
        allowed=len(denied) == 0,
        denied_reasons=denied,
        advisory=advisory,
    )
