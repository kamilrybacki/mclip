"""Parser for shell completion scripts — extracts structured command/flag info.

Many modern CLIs (cobra, click, clap, etc.) can generate shell completion scripts
that contain precise information about commands, flags, and their arguments.
"""

from __future__ import annotations

import re
import subprocess

from mclip.schema import Command, Flag


def get_completion_script(binary: str, timeout: int = 10) -> str | None:
    """Try to get a bash completion script from the tool.

    Tries common patterns:
      - <binary> completion bash
      - <binary> completions bash
      - <binary> --completion bash
      - <binary> generate-completion bash
    """
    patterns = [
        [binary, "completion", "bash"],
        [binary, "completions", "bash"],
        [binary, "--completion", "bash"],
        [binary, "generate-completion", "bash"],
        [binary, "shell-completion", "bash"],
    ]
    for cmd in patterns:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            continue
    return None


def parse_cobra_completions(script: str) -> tuple[list[Command], list[Flag]]:
    """Parse Cobra-style (Go) bash completion scripts.

    Cobra completions contain blocks like:
        commands=("get" "describe" "apply" "delete")
    and flag definitions like:
        flags+=("--output=")
        two_word_flags+=("-o")
    """
    commands: list[Command] = []
    flags: list[Flag] = []

    # Extract command names from `commands=("cmd1" "cmd2" ...)` blocks
    cmd_pattern = re.compile(r'commands=\(([^)]+)\)')
    for match in cmd_pattern.finditer(script):
        names = re.findall(r'"([\w][\w-]*)"', match.group(1))
        for name in names:
            if name not in [c.name for c in commands]:
                commands.append(Command(name=name))

    # Extract flags from `flags+=("--flag=")` and `flags+=("--flag")`
    flag_pattern = re.compile(r'flags\+=\("(--[\w][\w-]*)(=?)"\)')
    for match in flag_pattern.finditer(script):
        name, has_value = match.groups()
        if name not in [f.name for f in flags]:
            flags.append(Flag(
                name=name,
                takes_value=bool(has_value),
            ))

    # Extract two-word (short) flags
    short_pattern = re.compile(r'two_word_flags\+=\("(-\w)"\)')
    for match in short_pattern.finditer(script):
        short = match.group(1)
        # Try to associate with an existing long flag (heuristic: next long flag)
        # For now, just record it
        found = False
        for flag in flags:
            if flag.short is None and flag.takes_value:
                flag.short = short
                found = True
                break
        if not found:
            flags.append(Flag(name=short, short=short, takes_value=True))

    return commands, flags


def parse_click_completions(script: str) -> tuple[list[Command], list[Flag]]:
    """Parse Click-style (Python) bash completion scripts.

    Click completions use _CLICK_COMPLETE=bash_source pattern and define
    completion entries with COMPREPLY patterns.
    """
    commands: list[Command] = []
    flags: list[Flag] = []

    # Click completions often embed the command list in case statements
    # case "$cur" in  --*) COMPREPLY=($(compgen -W "--flag1 --flag2" ...))
    flag_words = re.compile(r'compgen\s+-W\s+"([^"]+)"')
    for match in flag_words.finditer(script):
        words = match.group(1).split()
        for word in words:
            if word.startswith("--") and word not in [f.name for f in flags]:
                flags.append(Flag(name=word))
            elif not word.startswith("-") and word not in [c.name for c in commands]:
                commands.append(Command(name=word))

    return commands, flags


def parse_completions(binary: str) -> tuple[str | None, list[Command], list[Flag]]:
    """Fetch and parse completion script for a binary.

    Returns (raw_script, commands, flags) or (None, [], []) if unavailable.
    """
    script = get_completion_script(binary)
    if not script:
        return None, [], []

    # Detect completion style and parse accordingly
    if "___" in script or "commands=(" in script:
        # Likely Cobra-style
        commands, flags = parse_cobra_completions(script)
    elif "_COMPLETE" in script or "COMPREPLY" in script:
        # Likely Click or generic bash completion
        commands, flags = parse_click_completions(script)
    else:
        # Unknown format — just return raw
        return script, [], []

    return script, commands, flags
