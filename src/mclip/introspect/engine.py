"""Introspection engine — orchestrates help, man, and completions parsers.

This module is the main entry point for CLI introspection. It coordinates
the three parsers (:mod:`~mclip.introspect.help`, :mod:`~mclip.introspect.man`,
:mod:`~mclip.introspect.completions`) and merges their results into a single
:class:`~mclip.schema.CLITool` schema.

The merging strategy prioritizes ``--help`` data as the primary source,
then enriches with ``man`` page data (richer descriptions) and shell
completions (precise flag/command structure).
"""

from __future__ import annotations

import shutil

from mclip.introspect.completions import parse_completions
from mclip.introspect.help import build_command_tree, run_help
from mclip.introspect.man import enrich_from_man
from mclip.schema import CLITool, Command, Flag


def _get_version(binary: str) -> str | None:
    """Attempt to retrieve the version string of a CLI tool.

    Tries common version flags in order: ``--version``, ``-V``,
    ``version``, ``-v``. Returns the first line of output that
    looks like a version string.

    :param binary: The binary name to query.
    :returns: Version string, or ``None`` if undiscoverable.
    :rtype: str | None
    """
    import subprocess

    for flag in ["--version", "-V", "version", "-v"]:
        try:
            result = subprocess.run(
                [binary, flag], capture_output=True, text=True, timeout=5
            )
            output = (result.stdout or result.stderr or "").strip()
            if output and len(output) < 200 and not output.startswith("usage"):
                return output.split("\n")[0]
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            continue
    return None


def _merge_flags(primary: list[Flag], secondary: list[Flag]) -> list[Flag]:
    """Merge two flag lists, preferring primary entries.

    Flags from ``secondary`` are appended if their name is not already
    present in ``primary``. If a flag exists in both, missing fields
    (description, short form) are filled from ``secondary``.

    :param primary: The authoritative flag list (e.g. from ``--help``).
    :param secondary: The supplementary flag list (e.g. from ``man``).
    :returns: Merged flag list.
    :rtype: list[Flag]
    """
    seen = {f.name for f in primary}
    merged = list(primary)
    for flag in secondary:
        if flag.name not in seen:
            merged.append(flag)
            seen.add(flag.name)
        else:
            # Enrich existing flag with missing data from secondary
            for existing in merged:
                if existing.name == flag.name:
                    if not existing.description and flag.description:
                        existing.description = flag.description
                    if not existing.short and flag.short:
                        existing.short = flag.short
                    if not existing.takes_value and flag.takes_value:
                        existing.takes_value = flag.takes_value
                    break
    return merged


def _merge_commands(primary: list[Command], secondary: list[Command]) -> list[Command]:
    """Merge two command lists, preferring primary entries.

    Commands from ``secondary`` are appended if not already present.
    Existing commands are enriched with descriptions and flags from
    ``secondary`` when the primary entry lacks them.

    :param primary: The authoritative command list.
    :param secondary: The supplementary command list.
    :returns: Merged command list.
    :rtype: list[Command]
    """
    seen = {c.name for c in primary}
    merged = list(primary)
    for cmd in secondary:
        if cmd.name not in seen:
            merged.append(cmd)
            seen.add(cmd.name)
        else:
            for existing in merged:
                if existing.name == cmd.name:
                    if not existing.description and cmd.description:
                        existing.description = cmd.description
                    if not existing.flags and cmd.flags:
                        existing.flags = cmd.flags
                    break
    return merged


def introspect_cli(
    binary_name: str,
    max_depth: int = 2,
    use_help: bool = True,
    use_man: bool = True,
    use_completions: bool = True,
) -> CLITool:
    """Perform full introspection of a CLI tool.

    Combines data from ``--help``, ``man`` pages, and shell completions
    into a unified :class:`~mclip.schema.CLITool` schema. Sources are
    merged with ``--help`` taking priority, enriched by ``man`` pages
    and completions.

    :param binary_name: The CLI tool name (must be on ``PATH``).
    :param max_depth: Maximum subcommand recursion depth for
        ``--help`` introspection.
    :param use_help: Whether to introspect via ``--help``.
    :param use_man: Whether to introspect via ``man`` pages.
    :param use_completions: Whether to introspect via shell completions.
    :returns: A fully populated CLI tool schema.
    :rtype: CLITool
    :raises FileNotFoundError: If the binary is not found on ``PATH``.

    Example::

        tool = introspect_cli("git", max_depth=2)
        print(f"Found {len(tool.commands)} commands")
    """
    path = shutil.which(binary_name)
    if not path:
        raise FileNotFoundError(f"Binary '{binary_name}' not found on PATH")

    sources: list[str] = []
    description = ""
    global_flags: list[Flag] = []
    commands: list[Command] = []
    raw_help = ""
    raw_man = ""

    # 1. --help introspection (primary source)
    if use_help:
        help_desc, help_flags, help_commands, help_raw = build_command_tree(
            binary_name, max_depth=max_depth
        )
        if help_raw:
            sources.append("help")
            description = help_desc
            global_flags = help_flags
            commands = help_commands
            raw_help = help_raw

    # 2. Man page enrichment
    if use_man:
        man_raw, man_desc, man_flags, man_commands = enrich_from_man(binary_name)
        if man_raw:
            sources.append("man")
            raw_man = man_raw
            if not description:
                description = man_desc
            global_flags = _merge_flags(global_flags, man_flags)
            commands = _merge_commands(commands, man_commands)

    # 3. Shell completions enrichment
    if use_completions:
        comp_raw, comp_commands, comp_flags = parse_completions(binary_name)
        if comp_raw:
            sources.append("completions")
            global_flags = _merge_flags(global_flags, comp_flags)
            commands = _merge_commands(commands, comp_commands)

    version = _get_version(binary_name)

    return CLITool(
        name=binary_name,
        path=path,
        version=version,
        description=description,
        global_flags=global_flags,
        commands=commands,
        raw_help=raw_help,
        raw_man=raw_man,
        introspection_sources=sources,
    )
