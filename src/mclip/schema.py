"""Schema models for CLI tool introspection results and execution policies.

Defines the Pydantic data models that represent a CLI tool's structure
after introspection. The hierarchy is::

    CLITool
    ├── global_flags: list[Flag]
    └── commands: list[Command]
        ├── flags: list[Flag]
        ├── arguments: list[Argument]
        └── subcommands: list[Command]

Policy models control what agents are allowed to do with registered tools::

    Policy
    ├── deterministic_rules: list[DeterministicRule]   # enforced at execution
    └── abstract_rules: list[AbstractRule]             # advisory, surfaced to agent

All models serialize cleanly to JSON for MCP transport and SQLite storage.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Flag(BaseModel):
    """A CLI flag or option (e.g. ``--output``, ``-o``).

    Represents a single flag discovered during introspection, including
    its long and short forms, description, and whether it takes a value.

    :ivar name: Long flag name, e.g. ``'--output'``.
    :ivar short: Short alias, e.g. ``'-o'``. ``None`` if no short form exists.
    :ivar description: Human-readable description from the help text.
    :ivar takes_value: Whether the flag expects an argument value.
    :ivar default: Default value, if discoverable.
    :ivar required: Whether the flag is required.
    :ivar choices: Allowed values if the flag accepts an enumerated set.
    """

    name: str = Field(description="Long flag name, e.g. '--output'")
    short: str | None = Field(default=None, description="Short alias, e.g. '-o'")
    description: str = Field(default="")
    takes_value: bool = Field(default=False, description="Whether the flag expects an argument")
    default: str | None = Field(default=None)
    required: bool = Field(default=False)
    choices: list[str] = Field(default_factory=list, description="Allowed values, if enumerable")


class Argument(BaseModel):
    """A positional CLI argument.

    Represents a required or optional positional argument discovered in
    the help output (e.g. ``FILE``, ``URL``, ``PATTERN``).

    :ivar name: Argument name as shown in the usage string.
    :ivar description: Human-readable description.
    :ivar required: Whether the argument is required.
    :ivar choices: Allowed values if the argument accepts an enumerated set.
    """

    name: str
    description: str = ""
    required: bool = True
    choices: list[str] = Field(default_factory=list)


class Command(BaseModel):
    """A CLI command or subcommand.

    Represents a node in the command tree. Leaf commands have no
    subcommands; branch commands (like ``kubectl get``) contain nested
    :class:`Command` instances.

    :ivar name: Command name (e.g. ``'get'``, ``'clone'``).
    :ivar description: Human-readable description.
    :ivar aliases: Alternative names for this command.
    :ivar flags: Flags specific to this command.
    :ivar arguments: Positional arguments for this command.
    :ivar subcommands: Nested subcommands.
    :ivar usage: Raw usage string from the help output.
    """

    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    arguments: list[Argument] = Field(default_factory=list)
    subcommands: list["Command"] = Field(default_factory=list)
    usage: str = Field(default="", description="Raw usage string from help output")


class CLITool(BaseModel):
    """A registered CLI tool with its full introspected schema.

    This is the top-level model returned by :func:`~mclip.introspect.introspect_cli`
    and stored in the :class:`~mclip.registry.Registry`. It contains the complete
    command tree, global flags, and raw source material.

    :ivar name: Binary name (e.g. ``'kubectl'``, ``'git'``).
    :ivar path: Absolute filesystem path to the binary.
    :ivar version: Version string if discoverable (e.g. ``'git version 2.43.0'``).
    :ivar description: Tool description from help or man page.
    :ivar global_flags: Flags available at the top level of the tool.
    :ivar commands: Top-level commands and their subcommand trees.
    :ivar raw_help: Raw ``--help`` output preserved for reference.
    :ivar raw_man: Raw ``man`` page content, if available.
    :ivar introspection_sources: Which sources contributed data
        (e.g. ``['help', 'man', 'completions']``).
    """

    name: str = Field(description="Binary name, e.g. 'kubectl'")
    path: str = Field(description="Absolute path to the binary")
    version: str | None = Field(default=None)
    description: str = Field(default="")
    global_flags: list[Flag] = Field(default_factory=list)
    commands: list[Command] = Field(default_factory=list)
    raw_help: str = Field(default="", description="Raw --help output for reference")
    raw_man: str = Field(default="", description="Raw man page content, if available")
    introspection_sources: list[str] = Field(
        default_factory=list,
        description="Which sources were used: 'help', 'man', 'completions'",
    )


# ---------------------------------------------------------------------------
# Policy models
# ---------------------------------------------------------------------------


class DeterministicRuleKind(str, Enum):
    """The type of deterministic policy rule.

    Each kind matches against a different aspect of a command invocation:

    - ``deny_command``: blocks a command path (e.g. ``"push"`` or ``"remote.add"``).
    - ``deny_flag``: blocks a specific flag (e.g. ``"--force"``).
    - ``deny_pattern``: blocks any argument matching a regex pattern.
    """

    deny_command = "deny_command"
    deny_flag = "deny_flag"
    deny_pattern = "deny_pattern"


class DeterministicRule(BaseModel):
    """A concrete, programmatically enforced policy rule.

    Deterministic rules are evaluated at execution time and will **block**
    the command if matched, returning an error to the agent.

    :ivar kind: What aspect of the invocation this rule checks.
    :ivar target: The value to match — a command path for ``deny_command``
        (dot-separated, e.g. ``"push"`` or ``"remote.add"``), a flag name
        for ``deny_flag`` (e.g. ``"--force"``), or a Python regex for
        ``deny_pattern`` (matched against each argument).
    :ivar description: Human-readable explanation of *why* this rule exists.
    """

    kind: DeterministicRuleKind = Field(description="What this rule checks")
    target: str = Field(
        description=(
            "Value to match: command path for deny_command, "
            "flag name for deny_flag, regex for deny_pattern"
        )
    )
    description: str = Field(default="", description="Why this rule exists")


class AbstractRule(BaseModel):
    """A natural-language policy guideline surfaced to the agent.

    Abstract rules are **not** enforced programmatically. They are returned
    alongside command results and inspection data so that the agent can
    self-regulate its behavior.

    Examples:

    - ``"Do not modify remote storage via this tool."``
    - ``"Only use read-only sub-commands in production namespaces."``
    - ``"Avoid commands that trigger billing-relevant operations."``

    :ivar description: The natural-language policy statement.
    """

    description: str = Field(description="Natural-language policy statement")


class Policy(BaseModel):
    """Execution policy for a registered CLI tool.

    A policy is a collection of deterministic and abstract rules attached
    to a specific CLI tool. Deterministic rules are enforced automatically;
    abstract rules are advisory.

    :ivar cli_name: The binary name this policy applies to.
    :ivar deterministic_rules: Rules enforced at execution time.
    :ivar abstract_rules: Advisory rules surfaced to the agent.
    """

    cli_name: str = Field(description="Binary name this policy applies to")
    deterministic_rules: list[DeterministicRule] = Field(default_factory=list)
    abstract_rules: list[AbstractRule] = Field(default_factory=list)
