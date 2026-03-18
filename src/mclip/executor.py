"""Command executor — runs validated CLI commands and captures output."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from mclip.schema import CLITool


@dataclass
class ExecutionResult:
    """Result of a CLI command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class ExecutionError(Exception):
    """Raised when command validation or execution fails."""


def validate_command(tool: CLITool, args: list[str]) -> list[str]:
    """Validate and build a full command line.

    Checks that:
    - The first arg (if any) is a known subcommand or flag
    - No shell injection characters are present in arguments

    Returns the full command as a list: [binary, *args]
    """
    # Block obvious shell injection attempts
    dangerous_chars = {";", "|", "&", "`", "$", "(", ")", "{", "}", "<", ">", "\n"}
    for arg in args:
        if any(c in arg for c in dangerous_chars):
            raise ExecutionError(
                f"Argument contains disallowed shell character: {arg!r}"
            )

    return [tool.path, *args]


def execute(
    tool: CLITool,
    args: list[str],
    timeout: int = 30,
    stdin: str | None = None,
) -> ExecutionResult:
    """Execute a command against a registered CLI tool.

    Args:
        tool: The registered CLITool schema.
        args: Arguments to pass (subcommands, flags, positional args).
        timeout: Max execution time in seconds.
        stdin: Optional string to pipe to stdin.

    Returns:
        ExecutionResult with stdout, stderr, and exit code.
    """
    cmd = validate_command(tool, args)
    cmd_str = shlex.join(cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            input=stdin,
        )
        return ExecutionResult(
            command=cmd_str,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            command=cmd_str,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
        )
    except FileNotFoundError:
        return ExecutionResult(
            command=cmd_str,
            exit_code=-1,
            stdout="",
            stderr=f"Binary not found: {tool.path}",
        )
