"""Persistent, versioned circuit drafts stored beside experiment history."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class CircuitDraftStore:
    """Small SQLite repository for named circuit documents and their revisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS circuit_drafts (
                    draft_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS circuit_draft_versions (
                    draft_id TEXT NOT NULL REFERENCES circuit_drafts(draft_id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    saved_at TEXT NOT NULL,
                    document TEXT NOT NULL,
                    PRIMARY KEY (draft_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_drafts_updated ON circuit_drafts(updated_at DESC);
                """
            )
            connection.execute("PRAGMA foreign_keys = ON")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row, *, include_document: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "draft_id": row["draft_id"],
            "name": row["name"],
            "favorite": bool(row["favorite"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "version": row["version"],
        }
        if include_document:
            result["document"] = json.loads(row["document"])
        return result

    def list(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM circuit_drafts ORDER BY favorite DESC, updated_at DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM circuit_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        return self._row(row, include_document=True) if row else None

    def save(
        self,
        *,
        name: str,
        document: dict[str, Any],
        draft_id: str | None = None,
        favorite: bool = False,
    ) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        serialized = json.dumps(document, sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            existing = connection.execute("SELECT * FROM circuit_drafts WHERE draft_id = ?", (draft_id,)).fetchone() if draft_id else None
            if draft_id and existing is None:
                raise KeyError(draft_id)
            if existing is None:
                draft_id = uuid.uuid4().hex[:12]
                version = 1
                connection.execute(
                    "INSERT INTO circuit_drafts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (draft_id, name, int(favorite), now, now, version, serialized),
                )
                connection.execute(
                    "INSERT INTO circuit_draft_versions VALUES (?, ?, ?, ?)", (draft_id, version, now, serialized)
                )
            else:
                version = int(existing["version"])
                previous = json.dumps(json.loads(existing["document"]), sort_keys=True, separators=(",", ":"))
                if previous != serialized:
                    version += 1
                    connection.execute(
                        "INSERT INTO circuit_draft_versions VALUES (?, ?, ?, ?)", (draft_id, version, now, serialized)
                    )
                connection.execute(
                    "UPDATE circuit_drafts SET name = ?, favorite = ?, updated_at = ?, version = ?, document = ? WHERE draft_id = ?",
                    (name, int(favorite), now, version, serialized, draft_id),
                )
            row = connection.execute("SELECT * FROM circuit_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        return self._row(row, include_document=True)

    def versions(self, draft_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            exists = connection.execute("SELECT 1 FROM circuit_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            if not exists:
                raise KeyError(draft_id)
            rows = connection.execute(
                "SELECT version, saved_at FROM circuit_draft_versions WHERE draft_id = ? ORDER BY version DESC",
                (draft_id,),
            ).fetchall()
        return [{"version": row["version"], "saved_at": row["saved_at"]} for row in rows]

    def restore(self, draft_id: str, version: int) -> dict[str, Any]:
        with self._connection() as connection:
            draft = connection.execute("SELECT * FROM circuit_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            if not draft:
                raise KeyError(draft_id)
            revision = connection.execute(
                "SELECT document FROM circuit_draft_versions WHERE draft_id = ? AND version = ?",
                (draft_id, version),
            ).fetchone()
            if not revision:
                raise KeyError(f"{draft_id}@{version}")
            document = json.loads(revision["document"])
        return self.save(name=draft["name"], document=document, draft_id=draft_id, favorite=bool(draft["favorite"]))

    def delete(self, draft_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM circuit_drafts WHERE draft_id = ?", (draft_id,))
        return cursor.rowcount > 0
