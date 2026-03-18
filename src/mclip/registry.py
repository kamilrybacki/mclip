"""Persistent CLI registry backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mclip.schema import CLITool

DEFAULT_DB_PATH = Path.home() / ".mclip" / "registry.db"


class Registry:
    """Persistent store for registered CLI tools and their introspected schemas."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cli_tools (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def register(self, tool: CLITool) -> None:
        """Register or update a CLI tool in the registry."""
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
        """Retrieve a registered CLI tool by name."""
        row = self._conn.execute(
            "SELECT schema_json FROM cli_tools WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        return CLITool.model_validate_json(row["schema_json"])

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with summary info."""
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
        """Remove a CLI tool from the registry. Returns True if it existed."""
        cursor = self._conn.execute("DELETE FROM cli_tools WHERE name = ?", (name,))
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        self._conn.close()
