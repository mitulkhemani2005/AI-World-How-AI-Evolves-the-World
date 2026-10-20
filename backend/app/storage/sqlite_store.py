"""Small SQLite snapshot store; it preserves a world across API restarts."""

from __future__ import annotations

import json
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
                "(singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1), payload TEXT NOT NULL, random_state TEXT)"
            )
            # Older saved worlds predate persisted random state; add it in place without resetting them.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(world_snapshot)")}
            if "random_state" not in columns:
                connection.execute("ALTER TABLE world_snapshot ADD COLUMN random_state TEXT")

    def load(self) -> WorldState | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM world_snapshot WHERE singleton_id = 1"
            ).fetchone()
        return WorldState.model_validate_json(row[0]) if row else None

    def load_random_state(self) -> object | None:
        """Return the JSON-encoded PRNG state used to continue a world after restart."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT random_state FROM world_snapshot WHERE singleton_id = 1"
            ).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save(self, state: WorldState, random_state: object | None = None) -> None:
        """Save the world and random stream together as one SQLite snapshot."""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO world_snapshot(singleton_id, payload, random_state) VALUES(1, ?, ?) "
                    "ON CONFLICT(singleton_id) DO UPDATE SET payload = excluded.payload, "
                    "random_state = excluded.random_state",
                    (state.model_dump_json(), json.dumps(random_state)),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection
