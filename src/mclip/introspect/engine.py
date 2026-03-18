"""Introspection engine — orchestrates help, man, and completions parsers to build a CLITool."""

from __future__ import annotations

import shutil

from mclip.introspect.completions import parse_completions
from mclip.introspect.help import build_command_tree, run_help
from mclip.introspect.man import enrich_from_man
from mclip.schema import CLITool, Command, Flag


def _get_version(binary: str) -> str | None:
    """Try to get the tool version via common patterns."""
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
    """Merge two flag lists, preferring primary entries but adding new ones from secondary."""
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
    """Merge command lists, preferring primary but enriching with secondary."""
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

    Combines data from --help, man pages, and shell completions into a
    unified CLITool schema. Sources are merged with --help taking priority,
    enriched by man pages and completions.

    Args:
        binary_name: The CLI tool name (must be on PATH).
        max_depth: Maximum subcommand recursion depth for --help introspection.
        use_help: Whether to introspect via --help.
        use_man: Whether to introspect via man pages.
        use_completions: Whether to introspect via shell completions.

    Returns:
        A fully populated CLITool schema.

    Raises:
        FileNotFoundError: If the binary is not found on PATH.
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
