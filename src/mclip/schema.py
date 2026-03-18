"""Schema models for CLI tool introspection results.

Defines the Pydantic data models that represent a CLI tool's structure
after introspection. The hierarchy is::

    CLITool
    ├── global_flags: list[Flag]
    └── commands: list[Command]
        ├── flags: list[Flag]
        ├── arguments: list[Argument]
        └── subcommands: list[Command]

All models serialize cleanly to JSON for MCP transport and SQLite storage.
"""

from __future__ import annotations

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
