"""Parser for ``--help`` output of CLI tools.

Handles common help output patterns from argparse, click, cobra, clap,
and similar CLI frameworks. This is the primary introspection source
and produces the most reliable results for the widest range of tools.

The parser extracts:

- **Description** — text before the first section header
- **Usage line** — the ``usage:`` line
- **Flags/options** — from ``Options:`` sections or indented flag lines
- **Subcommand names** — from ``Commands:`` sections or category-based listings
- **Positional arguments** — from ``Arguments:`` sections
"""

from __future__ import annotations

import re
import subprocess

from mclip.schema import Argument, Command, Flag


def run_help(binary: str, subcommand: list[str] | None = None, timeout: int = 10) -> str | None:
    """Run ``<binary> [subcommand...] --help`` and return the output.

    Tries ``--help`` first, then ``-h`` as a fallback (some tools like
    git subcommands use ``-h`` for short help while ``--help`` opens a
    man page). Output is validated with :func:`_looks_like_help` to skip
    error messages.

    :param binary: The CLI binary name or path.
    :param subcommand: Optional subcommand path, e.g. ``["get", "pods"]``.
    :param timeout: Maximum time in seconds to wait for the process.
    :returns: The help text, or ``None`` if unavailable.
    :rtype: str | None
    """
    for flag in ["--help", "-h"]:
        cmd = [binary, *(subcommand or []), flag]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            output = result.stdout or result.stderr
            if output and output.strip():
                text = output.strip()
                # Skip outputs that don't look like help text (e.g. man page errors)
                if _looks_like_help(text):
                    return text
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            continue
    return None


def _looks_like_help(text: str) -> bool:
    """Check whether text looks like CLI help output.

    Uses a heuristic: the text must contain at least one common
    help-output indicator such as ``usage:``, ``options:``, or
    indented flag patterns.

    :param text: The text to check.
    :returns: ``True`` if the text appears to be help output.
    :rtype: bool
    """
    lower = text.lower()
    indicators = ["usage:", "options:", "commands:", "flags:", "  -", "  --", "arguments:"]
    return any(ind in lower for ind in indicators)


def parse_help_output(text: str) -> tuple[str, list[Flag], list[Argument], list[str], str]:
    """Parse a ``--help`` output string into structured components.

    :param text: Raw help output text.
    :returns: A tuple of ``(description, flags, arguments,
        subcommand_names, usage_line)``.
    :rtype: tuple[str, list[Flag], list[Argument], list[str], str]
    """
    description = _extract_description(text)
    flags = _extract_flags(text)
    arguments = _extract_arguments(text)
    subcommand_names = _extract_subcommand_names(text)
    usage = _extract_usage(text)
    return description, flags, arguments, subcommand_names, usage


def _extract_description(text: str) -> str:
    """Extract the description from help output.

    The description is typically the text appearing before the first
    section header (``Usage:``, ``Options:``, ``Commands:``, etc.).

    :param text: Raw help output text.
    :returns: The extracted description, or an empty string.
    :rtype: str
    """
    lines = text.split("\n")
    desc_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if desc_lines:
                break
            continue
        # Stop at section headers like "Usage:", "Options:", "Commands:"
        if re.match(r"^(usage|options|flags|commands|arguments|positional|subcommands)\s*:", stripped, re.IGNORECASE):
            break
        desc_lines.append(stripped)
    return " ".join(desc_lines)


def _extract_usage(text: str) -> str:
    """Extract the usage line from help output.

    :param text: Raw help output text.
    :returns: The usage string, or an empty string if not found.
    :rtype: str
    """
    match = re.search(r"(?i)^usage:\s*(.+?)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


# Regex for flag lines like:
#   -o, --output <FILE>    Output file path
#   --verbose              Enable verbose mode
#   -n NUM                 Number of items
#   -v, --[no-]verbose     be more verbose
_FLAG_RE = re.compile(
    r"^\s+"
    r"(?:(-\w),?\s+)?"  # optional short flag
    r"(--(?:\[no-\])?[\w][\w-]*)"  # long flag, possibly with [no-] prefix
    r"(?:[=\s]+[<\[]([\w.:-]+)[>\]]|\s+([\w.:-]+))?"  # optional value placeholder
    r"\s{2,}(.+)$"  # description (separated by 2+ spaces)
)

# Alternate pattern for short-only flags: -v, -h
_SHORT_ONLY_FLAG_RE = re.compile(
    r"^\s+(-\w)"
    r"(?:\s+[<\[]([\w.:-]+)[>\]]|\s+([\w.:-]+))?"
    r"\s{2,}(.+)$"
)


def _extract_flags(text: str) -> list[Flag]:
    """Extract flags and options from help text.

    Scans both explicit ``Options:`` sections and any indented flag-like
    lines throughout the output. This dual approach handles tools that
    list flags outside a formal section (e.g. ``git`` subcommands).

    :param text: Raw help output text.
    :returns: List of discovered flags.
    :rtype: list[Flag]
    """
    flags: list[Flag] = []
    seen_names: set[str] = set()
    in_options_section = False

    for line in text.split("\n"):
        stripped = line.strip().lower()
        if re.match(r"^(options|flags|global options|optional arguments|general options)\s*:", stripped):
            in_options_section = True
            continue
        if in_options_section and stripped and not stripped.startswith("-") and not line.startswith(" "):
            in_options_section = False
            continue

        # Try to match flag patterns in options sections or anywhere with indentation
        if in_options_section or line.startswith("  "):
            match = _FLAG_RE.match(line)
            if match:
                short, long, val1, val2, desc = match.groups()
                if long not in seen_names:
                    value_name = val1 or val2
                    flags.append(Flag(
                        name=long,
                        short=short,
                        description=(desc or "").strip(),
                        takes_value=value_name is not None,
                        required="required" in (desc or "").lower(),
                    ))
                    seen_names.add(long)
                continue

            if in_options_section:
                match = _SHORT_ONLY_FLAG_RE.match(line)
                if match:
                    short, val1, val2, desc = match.groups()
                    if short not in seen_names:
                        value_name = val1 or val2
                        flags.append(Flag(
                            name=short,
                            short=short,
                            description=(desc or "").strip(),
                            takes_value=value_name is not None,
                        ))
                        seen_names.add(short)

    return flags


# Pattern for subcommand listings:
#   get         Get resources
#   describe    Describe resources
_SUBCOMMAND_RE = re.compile(r"^\s{2,}([\w][\w-]*)\s{2,}(.+)$")


def _extract_subcommand_names(text: str) -> list[str]:
    """Extract subcommand names from help text.

    Handles two common formats:

    1. **Explicit section header** — ``Commands:`` / ``Available commands:``
       followed by indented entries.
    2. **Category-based** (e.g. ``git``) — category descriptions followed
       by indented ``cmd  Description`` lines.

    :param text: Raw help output text.
    :returns: List of subcommand names discovered.
    :rtype: list[str]
    """
    names: list[str] = []
    in_commands_section = False
    past_usage = False

    for line in text.split("\n"):
        stripped = line.strip().lower()

        # Track when we're past the usage block
        if re.match(r"^(usage)\s*:", stripped):
            past_usage = True
            continue

        # Explicit commands section header
        if re.match(r"^(commands|available commands|subcommands)\s*:", stripped):
            in_commands_section = True
            continue

        # End of explicit section on a non-indented, non-empty line that isn't a command
        if in_commands_section and stripped and not line.startswith(" "):
            in_commands_section = False
            continue

        # Try to match indented command entries
        if in_commands_section or past_usage:
            match = _SUBCOMMAND_RE.match(line)
            if match:
                name = match.group(1)
                # Skip help aliases, section dividers, and category-like headers
                if name.lower() not in ("help",):
                    names.append(name)

    return names


def _extract_arguments(text: str) -> list[Argument]:
    """Extract positional arguments from help text.

    Looks for ``Positional arguments:`` or ``Arguments:`` sections and
    parses indented entries with the same pattern as subcommands.

    :param text: Raw help output text.
    :returns: List of discovered positional arguments.
    :rtype: list[Argument]
    """
    args: list[Argument] = []
    in_args_section = False

    for line in text.split("\n"):
        stripped = line.strip().lower()
        if re.match(r"^(positional arguments|arguments)\s*:", stripped):
            in_args_section = True
            continue
        if in_args_section and stripped and not line.startswith(" "):
            in_args_section = False
            continue

        if not in_args_section:
            continue

        match = _SUBCOMMAND_RE.match(line)  # same indent pattern
        if match:
            name, desc = match.group(1), match.group(2)
            required = "optional" not in desc.lower()
            args.append(Argument(name=name, description=desc.strip(), required=required))

    return args


def build_command_tree(
    binary: str,
    max_depth: int = 3,
    _depth: int = 0,
    _prefix: list[str] | None = None,
) -> tuple[str, list[Flag], list[Command], str]:
    """Recursively build a command tree by invoking ``--help`` on each subcommand.

    Starting from the top-level binary, this function discovers subcommands
    and recurses into each one up to ``max_depth`` levels deep, collecting
    flags, arguments, and nested subcommands at each level.

    :param binary: The CLI binary name.
    :param max_depth: Maximum recursion depth for subcommand discovery.
    :param _depth: Current recursion depth (internal use).
    :param _prefix: Current subcommand path prefix (internal use).
    :returns: A tuple of ``(description, global_flags, commands, raw_help)``.
    :rtype: tuple[str, list[Flag], list[Command], str]
    """
    prefix = _prefix or []
    raw = run_help(binary, prefix if prefix else None)
    if not raw:
        return "", [], [], ""

    description, flags, arguments, subcommand_names, usage = parse_help_output(raw)

    commands: list[Command] = []
    if _depth < max_depth and subcommand_names:
        for sub_name in subcommand_names:
            sub_path = prefix + [sub_name]
            sub_raw = run_help(binary, sub_path)
            if not sub_raw:
                commands.append(Command(name=sub_name))
                continue

            sub_desc, sub_flags, sub_args, sub_sub_names, sub_usage = parse_help_output(sub_raw)

            # Recurse one more level for subcommands
            sub_commands: list[Command] = []
            if _depth + 1 < max_depth and sub_sub_names:
                for subsub in sub_sub_names:
                    subsub_raw = run_help(binary, sub_path + [subsub])
                    if subsub_raw:
                        ss_desc, ss_flags, ss_args, _, ss_usage = parse_help_output(subsub_raw)
                        sub_commands.append(Command(
                            name=subsub,
                            description=ss_desc,
                            flags=ss_flags,
                            arguments=ss_args,
                            usage=ss_usage,
                        ))
                    else:
                        sub_commands.append(Command(name=subsub))

            commands.append(Command(
                name=sub_name,
                description=sub_desc,
                flags=sub_flags,
                arguments=sub_args,
                subcommands=sub_commands,
                usage=sub_usage,
            ))

    return description, flags, commands, raw
