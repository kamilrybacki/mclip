"""Command executor — runs validated CLI commands and captures output.

Provides safe command execution for registered CLI tools. All arguments are
validated against a blocklist of dangerous shell characters before execution
to prevent injection attacks. Commands are run as subprocesses with configurable
timeouts.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from mclip.schema import CLITool


@dataclass
class ExecutionResult:
    """Result of a CLI command execution.

    :param command: The full command string as executed.
    :param exit_code: Process exit code (``-1`` for internal errors like timeouts).
    :param stdout: Captured standard output.
    :param stderr: Captured standard error.
    """

    command: str
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        """Serialize the result to a plain dictionary.

        :returns: Dictionary with ``command``, ``exit_code``, ``stdout``,
            and ``stderr`` keys.
        :rtype: dict
        """
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class ExecutionError(Exception):
    """Raised when command validation or execution fails.

    This is raised *before* the subprocess is spawned, e.g. when
    arguments contain disallowed shell characters.
    """


def validate_command(tool: CLITool, args: list[str]) -> list[str]:
    """Validate arguments and build the full command line.

    Checks that no arguments contain shell metacharacters that could
    enable injection attacks. The command is constructed as a list
    (not a shell string) so ``subprocess.run`` invokes it directly.

    :param tool: The registered CLI tool providing the binary path.
    :param args: Arguments to pass to the binary.
    :returns: The full command as a list: ``[binary_path, *args]``.
    :rtype: list[str]
    :raises ExecutionError: If any argument contains a disallowed character.
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

    Validates arguments via :func:`validate_command`, then spawns the
    process with captured stdout/stderr. The subprocess is invoked
    directly (no shell) for security.

    :param tool: The registered CLI tool to invoke.
    :param args: Arguments to pass (subcommands, flags, positional args).
    :param timeout: Maximum execution time in seconds.
    :param stdin: Optional string to pipe to the command's stdin.
    :returns: The execution result with captured output.
    :rtype: ExecutionResult
    :raises ExecutionError: If argument validation fails.
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
