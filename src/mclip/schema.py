"""Schema models for CLI tool introspection results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Flag(BaseModel):
    """A CLI flag/option."""

    name: str = Field(description="Long flag name, e.g. '--output'")
    short: str | None = Field(default=None, description="Short alias, e.g. '-o'")
    description: str = Field(default="")
    takes_value: bool = Field(default=False, description="Whether the flag expects an argument")
    default: str | None = Field(default=None)
    required: bool = Field(default=False)
    choices: list[str] = Field(default_factory=list, description="Allowed values, if enumerable")


class Argument(BaseModel):
    """A positional CLI argument."""

    name: str
    description: str = ""
    required: bool = True
    choices: list[str] = Field(default_factory=list)


class Command(BaseModel):
    """A CLI command or subcommand."""

    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    arguments: list[Argument] = Field(default_factory=list)
    subcommands: list[Command] = Field(default_factory=list)
    usage: str = Field(default="", description="Raw usage string from help output")


class CLITool(BaseModel):
    """A registered CLI tool with its full introspected schema."""

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
