# Architecture

## Overview

mclip follows the **router pattern**: instead of creating one MCP tool per CLI command (which would explode for tools like `kubectl` with 50+ commands), it exposes a small set of meta-tools that work with any registered CLI.

```
MCP Client (Agent)
       │ MCP protocol (stdio)
       ▼
┌─────────────────────────────────┐
│         mclip MCP Server        │
│                                 │
│  Registry ◄── Introspect Engine │
│  (SQLite)     ├── --help parser │
│               ├── man parser    │
│               └── completions   │
│                                 │
│  Executor ──► system CLIs       │
└─────────────────────────────────┘
```

## Components

### Schema (`mclip.schema`)

Pydantic models that represent the introspected structure of a CLI tool:

- **`CLITool`** — top-level model with metadata, global flags, and command tree
- **`Command`** — a command node with flags, arguments, and nested subcommands
- **`Flag`** — a CLI flag/option with name, short form, description, and value info
- **`Argument`** — a positional argument

### Introspection Engine (`mclip.introspect`)

Orchestrates three parsers and merges their results:

| Source | Priority | Strengths |
|--------|----------|-----------|
| `--help` | Primary | Most universal, recursive subcommand walking |
| `man` pages | Secondary | Richer descriptions, multi-line flag docs |
| Shell completions | Tertiary | Precise machine-readable structure |

The merge strategy:

1. `--help` data forms the base schema
2. `man` page data fills in missing descriptions and adds new flags
3. Shell completions add any flags/commands not found by the other two

### Registry (`mclip.registry`)

SQLite-backed persistence layer. Each tool is stored as a JSON-serialized `CLITool` in a single table:

```sql
CREATE TABLE cli_tools (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

### Executor (`mclip.executor`)

Safe command execution:

1. **Validation** — arguments are checked for shell metacharacters (`;`, `|`, `&`, `` ` ``, `$`, etc.)
2. **Execution** — subprocess is spawned directly (no shell) with configurable timeout
3. **Capture** — stdout, stderr, and exit code are returned

### Server (`mclip.server`)

FastMCP server exposing six tools. See [MCP Tools](tools.md) for details.

## Data flow

```
register_cli("git")
       │
       ▼
┌─────────────────┐
│ Introspect Engine│
│                  │
│  1. git --help   │──► parse_help_output() ──► Commands, Flags
│  2. git -h       │    (recursive walk)
│  3. man git      │──► parse_man_sections() ──► Description, Flags
│  4. git          │──► get_completion_script()──► Commands, Flags
│     completion   │
│                  │
│  merge all ──────│──► CLITool schema
└────────┬─────────┘
         │
         ▼
┌─────────────────┐
│    Registry      │
│  (SQLite DB)     │
│                  │
│  store/update    │
└─────────────────┘
```

## Design decisions

### Why router pattern over flat tools?

Large CLIs like `aws` have 200+ services, each with dozens of commands. Creating one MCP tool per command would overwhelm tool discovery. The router pattern keeps the tool count fixed at 6 regardless of how many CLIs are registered.

### Why SQLite over JSON files?

- Atomic writes (no corruption on crash)
- Efficient single-key lookups
- Zero-dependency (Python stdlib)
- Easy to inspect with standard tools

### Why three introspection sources?

No single source is complete:

- `--help` is universal but terse
- `man` pages have rich descriptions but aren't always installed
- Shell completions are structured but not all tools provide them

Combining all three maximizes coverage across the CLI ecosystem.
