"""Parser for man pages — extracts richer descriptions, examples, and environment variables."""

from __future__ import annotations

import re
import subprocess

from mclip.schema import Command, Flag


def get_man_page(tool_name: str, timeout: int = 10) -> str | None:
    """Fetch the man page for a tool as plain text, or None if unavailable."""
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
    """Split a man page into named sections."""
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
    """Get a description from the man page NAME or DESCRIPTION section."""
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
    """Extract flags from the OPTIONS section of a man page."""
    options_text = sections.get("OPTIONS", "")
    if not options_text:
        return []

    flags: list[Flag] = []

    # Man page options are typically formatted as:
    #   -f, --flag [value]
    #       Description text that may span
    #       multiple lines.
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
    """Extract subcommand information from COMMANDS or SUBCOMMANDS sections."""
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
    """Fetch and parse a man page, returning (raw_text, description, flags, commands).

    Returns (None, "", [], []) if the man page is unavailable.
    """
    raw = get_man_page(tool_name)
    if not raw:
        return None, "", [], []

    sections = parse_man_sections(raw)
    description = extract_description_from_man(sections)
    flags = extract_flags_from_man(sections)
    commands = extract_subcommands_from_man(sections)
    return raw, description, flags, commands
