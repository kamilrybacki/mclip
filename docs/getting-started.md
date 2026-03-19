# Getting Started

## Installation

Install mclip from the repository:

```bash
pip install -e .
```

This installs the `mclip` console script and all dependencies.

## Configuration

### Claude Code

Add mclip to your MCP server configuration in `settings.json`:

```json
{
  "mcpServers": {
    "mclip": {
      "command": "mclip",
      "args": []
    }
  }
}
```

### MCP CLI

Run directly via the MCP development CLI:

```bash
mcp run mclip
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCLIP_DB_PATH` | `~/.mclip/registry.db` | Path to the SQLite registry database |

## Usage workflow

### 1. Register a CLI tool

```
register_cli("git")
```

This triggers full introspection:

- Runs `git --help` and recursively walks subcommands
- Parses the `git` man page for richer descriptions
- Attempts to fetch shell completion scripts

The result is a structured schema stored in the registry.

### 2. Explore the tool's capabilities

```
inspect_cli("git")
```

Returns the full command tree with flags, arguments, and descriptions. Drill into specific subcommands:

```
inspect_cli("git", command_path="clone")
```

### 3. Execute commands

```
run_command("git", ["status", "--short"])
```

Returns the command output with exit code, stdout, and stderr.

### 4. Manage the registry

```
list_clis()          # See all registered tools
refresh_cli("git")   # Re-introspect after an upgrade
remove_cli("git")    # Remove from registry
```

### 5. Set execution policies

Control what the agent can and cannot do with a registered tool:

```
set_policy("git",
    deterministic_rules=[
        {"kind": "deny_command", "target": "push", "description": "No pushing to remote"},
        {"kind": "deny_flag", "target": "--force", "description": "Force operations are prohibited"}
    ],
    abstract_rules=["Prefer read-only operations when possible."]
)
```

Deterministic rules are enforced automatically — `run_command("git", ["push", "origin"])` will return an error. Abstract rules are surfaced as advisory messages in the command output.

```
get_policy("git")       # View current policy
remove_policy("git")    # Remove all restrictions
```

!!! tip
    See [Policies](policies.md) for comprehensive examples covering `kubectl`, `docker`, `gh`, `aws`, `terraform`, and other popular CLI tools.

## Introspection depth

The `max_depth` parameter controls how many levels of subcommands are introspected:

- `max_depth=1` — top-level commands only (fast)
- `max_depth=2` — one level of subcommands (default, good balance)
- `max_depth=3` — two levels deep (thorough but slower for large CLIs)

!!! tip
    For large CLIs like `kubectl` or `aws`, start with `max_depth=1` for a quick overview, then use `inspect_cli` with `show_raw_help=True` to dive deeper into specific commands.
