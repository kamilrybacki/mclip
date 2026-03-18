# mclip

MCP-CLI Protocol — consolidate any CLI into MCP tools via automatic introspection.

Instead of writing a bespoke MCP server for every CLI tool, mclip lets you **register** any CLI binary and it automatically discovers its commands, flags, and arguments by parsing `--help` output, `man` pages, and shell completion scripts.

## Architecture

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

## Installation

```bash
pip install -e .
```

## Usage

### As an MCP server

Add to your MCP client configuration (e.g. Claude Code `settings.json`):

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

Or run directly via the MCP CLI:

```bash
mcp run mclip
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `register_cli` | Register a CLI by name — triggers introspection via `--help`, `man`, and completions |
| `list_clis` | List all registered CLI tools |
| `inspect_cli` | Return the full command/flag/argument tree for a CLI |
| `run_command` | Execute a command against a registered CLI |
| `refresh_cli` | Re-introspect a CLI after updates |
| `remove_cli` | Remove a CLI from the registry |

### Example workflow (from an agent's perspective)

```
1. register_cli("kubectl")
   → Discovers 50+ commands, 200+ flags from help/man/completions

2. inspect_cli("kubectl", command_path="get")
   → Returns flags like --output, -n, --selector with descriptions

3. run_command("kubectl", ["get", "pods", "-n", "default", "-o", "json"])
   → Returns JSON output of pods
```

## Introspection Sources

mclip combines three sources for maximum coverage:

1. **`--help` / `-h`** — Most universal. Recursively walks subcommands up to a configurable depth.
2. **`man` pages** — Richer descriptions, examples, environment variables.
3. **Shell completions** — Structured command/flag data from Cobra, Click, Clap, and similar frameworks.

Data is merged with `--help` as the primary source, enriched by man and completions.

## Persistence

Registered tools and their schemas are stored in SQLite at `~/.mclip/registry.db`. Override with the `MCLIP_DB_PATH` environment variable.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MCLIP_DB_PATH` | `~/.mclip/registry.db` | Path to the SQLite registry database |

## License

MIT
