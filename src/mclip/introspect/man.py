"""Parser for ``man`` pages — extracts richer descriptions, options, and commands.

Man pages provide more detailed descriptions and structured option
documentation than ``--help`` output. This parser fetches the man page
as plain text (stripping terminal formatting), splits it into named
sections, and extracts flags and subcommands from the appropriate sections.

Typical man page sections used:

- **NAME** — tool name and one-line description
- **DESCRIPTION** — detailed description
- **OPTIONS** — flags with multi-line descriptions
- **COMMANDS** / **SUBCOMMANDS** — available subcommands
"""

from __future__ import annotations

import re
import subprocess

from mclip.schema import Command, Flag


def get_man_page(tool_name: str, timeout: int = 10) -> str | None:
    """Fetch the man page for a tool as plain text.

    Invokes ``man --pager=cat`` to get the raw man page output, then
    strips backspace-based bold/underline terminal formatting.

    :param tool_name: Name of the tool to look up.
    :param timeout: Maximum time in seconds to wait for ``man``.
    :returns: Plain-text man page content, or ``None`` if unavailable.
    :rtype: str | None
    """
    try:
        result = subprocess.run(
            ["man", "--pager=cat", tool_name],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"MANWIDTH": "120", "PATH": "/usr/bin:/usr/local/bin:/bin"},
        )
        if result.returncode != 0:
            return None
        # Strip backspace-based bold/underline formatting from man output
        text = re.sub(r".\x08", "", result.stdout)
        return text.strip() if text.strip() else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def parse_man_sections(text: str) -> dict[str, str]:
    """Split a man page into named sections.

    Man page section headers are detected as ALL-CAPS lines at column 0
    (e.g. ``NAME``, ``DESCRIPTION``, ``OPTIONS``).

    :param text: Plain-text man page content.
    :returns: Mapping of section name to section body text.
    :rtype: dict[str, str]
    """
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        # Man section headers are typically ALL CAPS at column 0
        if re.match(r"^[A-Z][A-Z /&-]+$", line.strip()) and len(line.strip()) < 40:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def extract_description_from_man(sections: dict[str, str]) -> str:
    """Extract a description from the ``NAME`` or ``DESCRIPTION`` section.

    Prefers the ``NAME`` section (format: ``tool - description``),
    falling back to the first paragraph of ``DESCRIPTION``.

    :param sections: Parsed man page sections from :func:`parse_man_sections`.
    :returns: The extracted description, or an empty string.
    :rtype: str
    """
    if "NAME" in sections:
        # NAME section is typically "tool - description"
        name_text = sections["NAME"].strip()
        if " - " in name_text:
            return name_text.split(" - ", 1)[1].strip()
        return name_text
    if "DESCRIPTION" in sections:
        # Take the first paragraph
        desc = sections["DESCRIPTION"].strip()
        paragraphs = re.split(r"\n\s*\n", desc)
        return paragraphs[0].strip() if paragraphs else desc
    return ""


def extract_flags_from_man(sections: dict[str, str]) -> list[Flag]:
    """Extract flags from the ``OPTIONS`` section of a man page.

    Parses the typical man page format where flags are indented 3-7
    spaces and their descriptions are indented 8+ spaces on subsequent
    lines::

        -f, --flag [value]
                Description text that may span
                multiple lines.

    :param sections: Parsed man page sections from :func:`parse_man_sections`.
    :returns: List of discovered flags.
    :rtype: list[Flag]
    """
    options_text = sections.get("OPTIONS", "")
    if not options_text:
        return []

    flags: list[Flag] = []

    flag_re = re.compile(
        r"^\s{3,7}"
        r"(?:(-\w),?\s+)?"
        r"(--[\w][\w-]*)"
        r"(?:[=\s]+[<\[]([\w.:-]+)[>\]])?"
    )

    lines = options_text.split("\n")
    i = 0
    while i < len(lines):
        match = flag_re.match(lines[i])
        if match:
            short, long, value = match.groups()
            # Collect description lines (indented more deeply)
            desc_lines: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith("        ") or not lines[i].strip()):
                if lines[i].strip():
                    desc_lines.append(lines[i].strip())
                elif desc_lines:
                    break  # blank line after description
                i += 1

            flags.append(Flag(
                name=long,
                short=short,
                description=" ".join(desc_lines),
                takes_value=value is not None,
            ))
        else:
            i += 1

    return flags


def extract_subcommands_from_man(sections: dict[str, str]) -> list[Command]:
    """Extract subcommands from ``COMMANDS`` or ``SUBCOMMANDS`` sections.

    Looks for indented command entries with descriptions, similar to
    the flag parsing format.

    :param sections: Parsed man page sections from :func:`parse_man_sections`.
    :returns: List of discovered subcommands.
    :rtype: list[Command]
    """
    for key in ("COMMANDS", "SUBCOMMANDS", "AVAILABLE COMMANDS"):
        if key in sections:
            text = sections[key]
            break
    else:
        return []

    commands: list[Command] = []
    cmd_re = re.compile(r"^\s{3,7}([\w][\w-]*)\s*$|^\s{3,7}([\w][\w-]*)\s{2,}(.+)$")

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        match = cmd_re.match(lines[i])
        if match:
            name = match.group(1) or match.group(2)
            inline_desc = match.group(3) or ""
            desc_lines = [inline_desc] if inline_desc else []
            i += 1
            while i < len(lines) and lines[i].startswith("        ") and lines[i].strip():
                desc_lines.append(lines[i].strip())
                i += 1
            commands.append(Command(name=name, description=" ".join(desc_lines).strip()))
        else:
            i += 1

    return commands


def enrich_from_man(
    tool_name: str,
) -> tuple[str | None, str, list[Flag], list[Command]]:
    """Fetch and parse a man page for a tool.

    This is the main entry point for man page introspection. It fetches
    the man page, parses it into sections, and extracts the description,
    flags, and subcommands.

    :param tool_name: Name of the tool to look up.
    :returns: A tuple of ``(raw_text, description, flags, commands)``.
        Returns ``(None, "", [], [])`` if the man page is unavailable.
    :rtype: tuple[str | None, str, list[Flag], list[Command]]
    """
    raw = get_man_page(tool_name)
    if not raw:
        return None, "", [], []

    sections = parse_man_sections(raw)
    description = extract_description_from_man(sections)
    flags = extract_flags_from_man(sections)
    commands = extract_subcommands_from_man(sections)
    return raw, description, flags, commands
