"""Persistent CLI registry backed by SQLite.

Stores registered :class:`~mclip.schema.CLITool` schemas in a local SQLite
database so they survive across MCP server restarts. The default database
location is ``~/.mclip/registry.db``, overridable via the ``MCLIP_DB_PATH``
environment variable.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mclip.schema import CLITool, Policy

DEFAULT_DB_PATH = Path.home() / ".mclip" / "registry.db"
"""Default path to the SQLite registry database."""


class Registry:
    """Persistent store for registered CLI tools and their introspected schemas.

    Wraps a SQLite database with CRUD operations for :class:`~mclip.schema.CLITool`
    instances. Tools are keyed by binary name and stored as serialized JSON.

    :param db_path: Path to the SQLite database file. Parent directories are
        created automatically if they don't exist.

    Example::

        registry = Registry()
        registry.register(tool)
        loaded = registry.get("git")
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the ``cli_tools`` and ``policies`` tables if they do not already exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cli_tools (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                cli_name TEXT PRIMARY KEY,
                policy_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (cli_name) REFERENCES cli_tools(name) ON DELETE CASCADE
            )
        """)
        self._conn.commit()

    def register(self, tool: CLITool) -> None:
        """Register or update a CLI tool in the registry.

        If a tool with the same name already exists, its schema and
        ``updated_at`` timestamp are replaced.

        :param tool: The introspected CLI tool to store.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO cli_tools (name, path, schema_json, registered_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                path = excluded.path,
                schema_json = excluded.schema_json,
                updated_at = excluded.updated_at
            """,
            (tool.name, tool.path, tool.model_dump_json(), now, now),
        )
        self._conn.commit()

    def get(self, name: str) -> CLITool | None:
        """Retrieve a registered CLI tool by name.

        :param name: Binary name of the tool (e.g. ``'git'``).
        :returns: The stored :class:`~mclip.schema.CLITool`, or ``None``
            if not registered.
        :rtype: CLITool | None
        """
        row = self._conn.execute(
            "SELECT schema_json FROM cli_tools WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        return CLITool.model_validate_json(row["schema_json"])

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with summary information.

        :returns: A list of dicts with keys ``name``, ``path``,
            ``registered_at``, and ``updated_at``.
        :rtype: list[dict[str, str]]
        """
        rows = self._conn.execute(
            "SELECT name, path, registered_at, updated_at FROM cli_tools ORDER BY name"
        ).fetchall()
        return [
            {
                "name": row["name"],
                "path": row["path"],
                "registered_at": row["registered_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def remove(self, name: str) -> bool:
        """Remove a CLI tool from the registry.

        :param name: Binary name of the tool to remove.
        :returns: ``True`` if the tool was found and removed, ``False`` otherwise.
        :rtype: bool
        """
        cursor = self._conn.execute("DELETE FROM cli_tools WHERE name = ?", (name,))
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Policy persistence
    # ------------------------------------------------------------------

    def set_policy(self, policy: Policy) -> None:
        """Create or replace the policy for a CLI tool.

        :param policy: The policy to store. Its ``cli_name`` must match
            a registered tool.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO policies (cli_name, policy_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cli_name) DO UPDATE SET
                policy_json = excluded.policy_json,
                updated_at = excluded.updated_at
            """,
            (policy.cli_name, policy.model_dump_json(), now, now),
        )
        self._conn.commit()

    def get_policy(self, cli_name: str) -> Policy | None:
        """Retrieve the policy for a CLI tool.

        :param cli_name: Binary name of the tool.
        :returns: The stored :class:`~mclip.schema.Policy`, or ``None``
            if no policy is set.
        :rtype: Policy | None
        """
        row = self._conn.execute(
            "SELECT policy_json FROM policies WHERE cli_name = ?", (cli_name,)
        ).fetchone()
        if not row:
            return None
        return Policy.model_validate_json(row["policy_json"])

    def remove_policy(self, cli_name: str) -> bool:
        """Remove the policy for a CLI tool.

        :param cli_name: Binary name of the tool.
        :returns: ``True`` if a policy was found and removed, ``False`` otherwise.
        :rtype: bool
        """
        cursor = self._conn.execute(
            "DELETE FROM policies WHERE cli_name = ?", (cli_name,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
