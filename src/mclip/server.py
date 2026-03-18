"""mclip MCP server — exposes CLI tools to agents via the Model Context Protocol.

This module is the main entry point for the mclip MCP server. It defines
the MCP tools that agents use to register, inspect, and execute CLI tools.

The server uses the **router** pattern: rather than creating one MCP tool per
CLI command, it exposes a small set of meta-tools (``register_cli``,
``inspect_cli``, ``run_command``, etc.) that work with any registered CLI.

Usage::

    # As a console script (installed via pip):
    $ mclip

    # Via the MCP CLI:
    $ mcp run mclip

    # Programmatically:
    >>> from mclip.server import main
    >>> main()
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from mclip.executor import ExecutionError, execute
from mclip.introspect import introspect_cli
from mclip.registry import Registry
from mclip.schema import AbstractRule, DeterministicRule, DeterministicRuleKind, Policy

mcp = FastMCP(
    "mclip",
    instructions=(
        "mclip consolidates CLI tools into MCP. Use `register_cli` to add a tool, "
        "`inspect_cli` to explore its capabilities, and `run_command` to execute commands. "
        "Use `set_policy` to define execution rules — deterministic rules block specific "
        "commands/flags/patterns, abstract rules provide advisory guidelines. "
        "Policies are enforced automatically on `run_command`. "
        "All registered tools and policies persist across sessions."
    ),
)

_registry: Registry | None = None


def _get_registry() -> Registry:
    """Get or initialize the global registry singleton.

    Uses the ``MCLIP_DB_PATH`` environment variable if set, otherwise
    falls back to the default path (``~/.mclip/registry.db``).

    :returns: The shared :class:`~mclip.registry.Registry` instance.
    :rtype: Registry
    """
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
    building a structured schema that can be queried with :func:`inspect_cli`
    and used to validate commands run via :func:`run_command`.

    :param binary_name: Name of the CLI binary (must be on ``PATH``),
        e.g. ``"kubectl"``, ``"docker"``, ``"git"``.
    :param max_depth: How many levels of subcommands to recurse into.
    :param use_help: Whether to introspect via ``--help``.
    :param use_man: Whether to introspect via ``man`` pages.
    :param use_completions: Whether to introspect via shell completion scripts.
    :returns: JSON string with registration summary or error.
    :rtype: str
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
    """List all registered CLI tools with their paths and registration timestamps.

    :returns: JSON array of tool summaries, or a message if none are registered.
    :rtype: str
    """
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
    during introspection. Use ``command_path`` to drill into a specific
    subcommand.

    :param binary_name: Name of the registered CLI tool.
    :param command_path: Dot-separated path to a subcommand
        (e.g. ``"get.pods"``). Empty string returns the full tool schema.
    :param show_raw_help: Include the raw ``--help`` output in the response.
    :param show_raw_man: Include the raw ``man`` page in the response.
    :returns: JSON string with the command schema or error.
    :rtype: str
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

    # Attach policy summary so agents see constraints alongside the schema.
    policy = registry.get_policy(binary_name)
    if policy:
        result["policy"] = policy.model_dump()

    return json.dumps(result, indent=2)


@mcp.tool()
def run_command(
    binary_name: str,
    args: list[str],
    timeout: int = 30,
    stdin: str | None = None,
) -> str:
    """Execute a command against a registered CLI tool.

    The binary must be registered via :func:`register_cli` first. Arguments
    are validated to prevent shell injection before execution.

    :param binary_name: Name of the registered CLI tool.
    :param args: List of arguments to pass, e.g.
        ``["get", "pods", "-n", "default", "-o", "json"]``.
    :param timeout: Maximum execution time in seconds.
    :param stdin: Optional string to pipe to the command's stdin.
    :returns: JSON string with ``command``, ``exit_code``, ``stdout``,
        and ``stderr``.
    :rtype: str
    """
    registry = _get_registry()
    tool = registry.get(binary_name)
    if not tool:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    policy = registry.get_policy(binary_name)

    try:
        result = execute(tool, args, timeout=timeout, stdin=stdin, policy=policy)
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
    schema is stale. Equivalent to calling :func:`register_cli` again.

    :param binary_name: Name of the registered CLI tool to refresh.
    :param max_depth: Subcommand recursion depth.
    :returns: JSON string with updated registration summary or error.
    :rtype: str
    """
    registry = _get_registry()
    existing = registry.get(binary_name)
    if not existing:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    return register_cli(binary_name, max_depth=max_depth)


@mcp.tool()
def remove_cli(binary_name: str) -> str:
    """Remove a CLI tool from the registry.

    :param binary_name: Name of the registered CLI tool to remove.
    :returns: JSON confirmation or error if the tool was not registered.
    :rtype: str
    """
    registry = _get_registry()
    removed = registry.remove(binary_name)
    if removed:
        return json.dumps({"status": "removed", "name": binary_name})
    return json.dumps({"error": f"'{binary_name}' is not registered."})


@mcp.tool()
def set_policy(
    binary_name: str,
    deterministic_rules: list[dict] | None = None,
    abstract_rules: list[str] | None = None,
) -> str:
    """Set or replace the execution policy for a registered CLI tool.

    Policies control what an agent is allowed to do with a tool. Two kinds
    of rules are supported:

    **Deterministic rules** are enforced at execution time and will block
    the command if matched. Each rule is a dict with:

    - ``kind``: one of ``"deny_command"``, ``"deny_flag"``, ``"deny_pattern"``.
    - ``target``: the value to match — a dot-separated command path for
      ``deny_command`` (e.g. ``"push"``, ``"remote.add"``), a flag name for
      ``deny_flag`` (e.g. ``"--force"``), or a regex for ``deny_pattern``.
    - ``description`` (optional): why this rule exists.

    **Abstract rules** are natural-language guidelines surfaced to the agent
    but not enforced programmatically. Each rule is a plain string, e.g.
    ``"Do not modify remote storage via this tool."``.

    :param binary_name: Name of the registered CLI tool.
    :param deterministic_rules: List of deterministic rule dicts.
    :param abstract_rules: List of natural-language advisory strings.
    :returns: JSON string with the stored policy summary or error.
    :rtype: str
    """
    registry = _get_registry()
    tool = registry.get(binary_name)
    if not tool:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    det_rules: list[DeterministicRule] = []
    for r in (deterministic_rules or []):
        try:
            det_rules.append(DeterministicRule(
                kind=DeterministicRuleKind(r["kind"]),
                target=r["target"],
                description=r.get("description", ""),
            ))
        except (KeyError, ValueError) as exc:
            return json.dumps({"error": f"Invalid deterministic rule {r!r}: {exc}"})

    abs_rules = [AbstractRule(description=s) for s in (abstract_rules or [])]

    policy = Policy(
        cli_name=binary_name,
        deterministic_rules=det_rules,
        abstract_rules=abs_rules,
    )
    registry.set_policy(policy)

    return json.dumps({
        "status": "policy_set",
        "cli_name": binary_name,
        "deterministic_rules": len(det_rules),
        "abstract_rules": len(abs_rules),
    }, indent=2)


@mcp.tool()
def get_policy(binary_name: str) -> str:
    """Retrieve the current execution policy for a registered CLI tool.

    Returns the full policy including all deterministic and abstract rules,
    or a message indicating no policy is set.

    :param binary_name: Name of the registered CLI tool.
    :returns: JSON string with the policy or an informational message.
    :rtype: str
    """
    registry = _get_registry()
    tool = registry.get(binary_name)
    if not tool:
        return json.dumps({"error": f"'{binary_name}' is not registered. Use register_cli first."})

    policy = registry.get_policy(binary_name)
    if not policy:
        return json.dumps({"message": f"No policy set for '{binary_name}'. All operations are allowed."})

    return json.dumps(policy.model_dump(), indent=2)


@mcp.tool()
def remove_policy(binary_name: str) -> str:
    """Remove the execution policy for a CLI tool, allowing unrestricted access.

    :param binary_name: Name of the registered CLI tool.
    :returns: JSON confirmation or error if no policy was set.
    :rtype: str
    """
    registry = _get_registry()
    removed = registry.remove_policy(binary_name)
    if removed:
        return json.dumps({"status": "policy_removed", "cli_name": binary_name})
    return json.dumps({"error": f"No policy set for '{binary_name}'."})


def main() -> None:
    """Entry point for the mclip MCP server.

    Starts the FastMCP server using stdio transport. This is the function
    invoked by the ``mclip`` console script.
    """
    mcp.run()


if __name__ == "__main__":
    main()
