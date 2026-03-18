# MCP Tools

mclip exposes six MCP tools that agents use to register, explore, and execute CLI tools.

## `register_cli`

Register a CLI tool by introspecting its help, man pages, and shell completions.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `binary_name` | `str` | *required* | Binary name on `PATH` (e.g. `"git"`, `"kubectl"`) |
| `max_depth` | `int` | `2` | Subcommand recursion depth |
| `use_help` | `bool` | `True` | Introspect via `--help` |
| `use_man` | `bool` | `True` | Introspect via `man` pages |
| `use_completions` | `bool` | `True` | Introspect via shell completions |

**Returns:** JSON with registration summary including commands/flags found, or error.

**Example:**
```json
{
  "status": "registered",
  "name": "git",
  "path": "/usr/bin/git",
  "version": "git version 2.43.0",
  "commands_found": 22,
  "global_flags_found": 0,
  "sources": ["help", "man"]
}
```

---

## `list_clis`

List all registered CLI tools with their paths and timestamps.

**Parameters:** None.

**Returns:** JSON array of tool summaries.

---

## `inspect_cli`

Inspect a registered CLI tool's full command schema.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `binary_name` | `str` | *required* | Name of the registered CLI tool |
| `command_path` | `str` | `""` | Dot-separated subcommand path (e.g. `"get.pods"`) |
| `show_raw_help` | `bool` | `False` | Include raw `--help` output |
| `show_raw_man` | `bool` | `False` | Include raw `man` page |

**Returns:** JSON with the command tree, flags, and arguments.

!!! tip
    Use `command_path` to drill into specific subcommands without retrieving the entire schema. This is useful for large CLIs where the full schema would be very long.

---

## `run_command`

Execute a command against a registered CLI tool.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `binary_name` | `str` | *required* | Name of the registered CLI tool |
| `args` | `list[str]` | *required* | Arguments to pass to the binary |
| `timeout` | `int` | `30` | Max execution time in seconds |
| `stdin` | `str \| None` | `None` | Optional stdin input |

**Returns:** JSON with `command`, `exit_code`, `stdout`, and `stderr`.

**Example:**
```json
{
  "command": "/usr/bin/git status --short",
  "exit_code": 0,
  "stdout": " M README.md\n?? src/\n",
  "stderr": ""
}
```

!!! warning
    Arguments are validated against a blocklist of shell metacharacters (`;`, `|`, `&`, `` ` ``, `$`, etc.) to prevent injection. Commands are executed directly via `subprocess` without a shell.

---

## `refresh_cli`

Re-introspect an already registered CLI tool to update its schema.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `binary_name` | `str` | *required* | Name of the registered CLI tool |
| `max_depth` | `int` | `2` | Subcommand recursion depth |

**Returns:** Same as `register_cli`.

---

## `remove_cli`

Remove a CLI tool from the registry.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `binary_name` | `str` | *required* | Name of the tool to remove |

**Returns:** JSON confirmation or error.
