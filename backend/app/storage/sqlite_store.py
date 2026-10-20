"""Small SQLite snapshot store; it preserves a world across API restarts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.domain import WorldState


class SQLiteWorldStore:
    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS world_snapshot "
                "(singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1), payload TEXT NOT NULL)"
            )

    def load(self) -> WorldState | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM world_snapshot WHERE singleton_id = 1"
            ).fetchone()
        return WorldState.model_validate_json(row[0]) if row else None

    def save(self, state: WorldState) -> None:
        # A single JSON snapshot keeps this first persistence layer easy to inspect and migrate.
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO world_snapshot(singleton_id, payload) VALUES(1, ?) "
                    "ON CONFLICT(singleton_id) DO UPDATE SET payload = excluded.payload",
                    (state.model_dump_json(),),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection
