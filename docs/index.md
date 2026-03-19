# mclip

**MCP-CLI Protocol** — consolidate any CLI into MCP tools via automatic introspection.

## What is mclip?

mclip is an MCP server that acts as a **universal CLI adapter**. Instead of writing a bespoke MCP server for every CLI tool (`kubectl`, `docker`, `aws`, `git`, `terraform`, etc.), mclip lets you **register** any CLI binary and it automatically discovers its commands, flags, and arguments.

## How it works

1. **Register** a CLI tool by name (e.g. `git`, `kubectl`)
2. mclip **introspects** the tool using three sources:
    - `--help` / `-h` output (recursive subcommand walking)
    - `man` pages (richer descriptions)
    - Shell completion scripts (Cobra, Click, etc.)
3. The discovered schema is **persisted** in a local SQLite database
4. Agents can **inspect** the schema and **execute** commands via MCP tools

## Quick example

From an agent's perspective:

```
1. register_cli("kubectl")
   → Discovers 50+ commands, 200+ flags from help/man/completions

2. inspect_cli("kubectl", command_path="get")
   → Returns flags like --output, -n, --selector with descriptions

3. run_command("kubectl", ["get", "pods", "-n", "default", "-o", "json"])
   → Returns JSON output of pods
```

## Key features

- **Zero configuration** — just register a CLI by name
- **Three introspection sources** — `--help`, `man`, shell completions
- **Persistent registry** — schemas survive across server restarts
- **Safe execution** — argument validation prevents shell injection
- **Execution policies** — deterministic rules block dangerous commands/flags, abstract rules provide advisory guardrails
- **Router pattern** — one set of meta-tools works with any CLI, avoiding tool explosion
