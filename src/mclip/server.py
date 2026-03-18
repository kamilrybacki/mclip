"""mclip MCP server — exposes CLI tools to agents via the Model Context Protocol."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mclip.executor import ExecutionError, execute
from mclip.introspect import introspect_cli
from mclip.registry import Registry

mcp = FastMCP(
    "mclip",
    instructions=(
        "mclip consolidates CLI tools into MCP. Use `register_cli` to add a tool, "
        "`inspect_cli` to explore its capabilities, and `run_command` to execute commands. "
        "All registered tools persist across sessions."
    ),
)

_registry: Registry | None = None


def _get_registry() -> Registry:
    global _registry
    if _registry is None:
        db_path = os.environ.get("MCLIP_DB_PATH")
        _registry = Registry(db_path) if db_path else Registry()
    return _registry


@mcp.tool()
def register_cli(
    binary_name: str,
    max_depth: int = 2,
    use_help: bool = True,
    use_man: bool = True,
    use_completions: bool = True,
) -> str:
    """Register a CLI tool by introspecting its help, man pages, and shell completions.

    This discovers the tool's commands, subcommands, flags, and arguments,
    building a structured schema that can be queried with inspect_cli and
    used to validate commands run via run_command.

    Args:
        binary_name: Name of the CLI binary (must be on PATH), e.g. "kubectl", "docker", "git".
        max_depth: How many levels of subcommands to recurse into (default 2).
        use_help: Introspect via --help (default True).
        use_man: Introspect via man pages (default True).
        use_completions: Introspect via shell completion scripts (default True).
    """
    try:
        tool = introspect_cli(
            binary_name,
            max_depth=max_depth,
            use_help=use_help,
            use_man=use_man,
            use_completions=use_completions,
        )
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc)})

    registry = _get_registry()
    registry.register(tool)

    summary = {
        "status": "registered",
        "name": tool.name,
        "path": tool.path,
        "version": tool.version,
        "description": tool.description,
        "sources": tool.introspection_sources,
        "commands_found": len(tool.commands),
        "global_flags_found": len(tool.global_flags),
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def list_clis() -> str:
    """List all registered CLI tools with their paths and registration timestamps."""
    registry = _get_registry()
    tools = registry.list_tools()
    if not tools:
        return json.dumps({"message": "No CLI tools registered yet. Use register_cli to add one."})
    return json.dumps(tools, indent=2)


@mcp.tool()
def inspect_cli(
    binary_name: str,
    command_path: str = "",
    show_raw_help: bool = False,
    show_raw_man: bool = False,
) -> str:
    """Inspect a registered CLI tool's full command schema.

    Returns the structured tree of commands, flags, and arguments discovered
    during introspection. Use command_path to drill into a specific subcommand.

    Args:
        binary_name: Name of the registered CLI tool.
        command_path: Dot-separated path to a subcommand, e.g. "get.pods" (optional).
        show_raw_help: Include the raw --help output in the response.
        show_raw_man: Include the raw man page in the response.
    """
    registry = _get_registry()
    tool = registry.get(binary_name)
    if not tool:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    if command_path:
        # Navigate to the specific subcommand
        parts = command_path.split(".")
        current_commands = tool.commands
        target = None
        for part in parts:
            found = None
            for cmd in current_commands:
                if cmd.name == part:
                    found = cmd
                    break
            if not found:
                return json.dumps({
                    "error": f"Subcommand '{part}' not found in path '{command_path}'",
                    "available": [c.name for c in current_commands],
                })
            target = found
            current_commands = found.subcommands

        result = target.model_dump()
    else:
        result = tool.model_dump(exclude={"raw_help", "raw_man"})
        if show_raw_help:
            result["raw_help"] = tool.raw_help
        if show_raw_man:
            result["raw_man"] = tool.raw_man

    return json.dumps(result, indent=2)


@mcp.tool()
def run_command(
    binary_name: str,
    args: list[str],
    timeout: int = 30,
    stdin: str | None = None,
) -> str:
    """Execute a command against a registered CLI tool.

    The binary must be registered via register_cli first. Arguments are validated
    against the tool's schema to prevent shell injection.

    Args:
        binary_name: Name of the registered CLI tool.
        args: List of arguments to pass, e.g. ["get", "pods", "-n", "default", "-o", "json"].
        timeout: Maximum execution time in seconds (default 30).
        stdin: Optional string to pipe to the command's stdin.
    """
    registry = _get_registry()
    tool = registry.get(binary_name)
    if not tool:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    try:
        result = execute(tool, args, timeout=timeout, stdin=stdin)
    except ExecutionError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps(result.to_dict(), indent=2)


@mcp.tool()
def refresh_cli(
    binary_name: str,
    max_depth: int = 2,
) -> str:
    """Re-introspect an already registered CLI tool to update its schema.

    Useful after a tool has been upgraded or when you suspect the cached
    schema is stale.

    Args:
        binary_name: Name of the registered CLI tool to refresh.
        max_depth: Subcommand recursion depth (default 2).
    """
    registry = _get_registry()
    existing = registry.get(binary_name)
    if not existing:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    return register_cli(binary_name, max_depth=max_depth)


@mcp.tool()
def remove_cli(binary_name: str) -> str:
    """Remove a CLI tool from the registry.

    Args:
        binary_name: Name of the registered CLI tool to remove.
    """
    registry = _get_registry()
    removed = registry.remove(binary_name)
    if removed:
        return json.dumps({"status": "removed", "name": binary_name})
    return json.dumps({"error": f"'{binary_name}' is not registered."})


def main() -> None:
    """Entry point for the mclip MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
