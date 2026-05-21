"""SQLite-backed local cache for transfer history/state."""
from __future__ import annotations
import sqlite3
import threading
import json
from pathlib import Path
from typing import Any


class LocalCache:
    def __init__(self, db_path: str | None = None):
        root = Path.home() / ".nss3ui"
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path or str(root / "cache.db")
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=5)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS transfers (
                    id TEXT PRIMARY KEY,
                    direction TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL,
                    bytes_done INTEGER NOT NULL,
                    speed REAL NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL,
                    resume_state TEXT NOT NULL DEFAULT '{}',
                    updated_at INTEGER NOT NULL
                )
                """
            )
            try:
                con.execute("ALTER TABLE transfers ADD COLUMN resume_state TEXT NOT NULL DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass

    def upsert_transfer(self, row: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as con:
                con.execute(
                    """
                    INSERT INTO transfers(
                        id, direction, filename, bucket, key_name, local_path,
                        total_bytes, bytes_done, speed, status, error, updated_at
                        , resume_state
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), ?)
                    ON CONFLICT(id) DO UPDATE SET
                        direction=excluded.direction,
                        filename=excluded.filename,
                        bucket=excluded.bucket,
                        key_name=excluded.key_name,
                        local_path=excluded.local_path,
                        total_bytes=excluded.total_bytes,
                        bytes_done=excluded.bytes_done,
                        speed=excluded.speed,
                        status=excluded.status,
                        error=excluded.error,
                        resume_state=excluded.resume_state,
                        updated_at=strftime('%s','now')
                    """,
                    (
                        row["id"],
                        row["direction"],
                        row["filename"],
                        row["bucket"],
                        row["key_name"],
                        row["local_path"],
                        row["total_bytes"],
                        row["bytes_done"],
                        row["speed"],
                        row["status"],
                        row["error"],
                        json.dumps(row.get("resume_state", {})),
                    ),
                )

    def load_transfers(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT id, direction, filename, bucket, key_name, local_path,
                       total_bytes, bytes_done, speed, status, error, resume_state
                FROM transfers
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            cols = [c[0] for c in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                try:
                    d["resume_state"] = json.loads(d.get("resume_state") or "{}")
                except Exception:
                    d["resume_state"] = {}
                out.append(d)
            return out

    def delete_transfers_by_status(self, statuses: list[str]) -> None:
        if not statuses:
            return
        placeholders = ",".join(["?"] * len(statuses))
        with self._lock:
            with self._connect() as con:
                con.execute(
                    f"DELETE FROM transfers WHERE status IN ({placeholders})",
                    tuple(statuses),
                )

    def delete_transfer_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        with self._lock:
            with self._connect() as con:
                con.execute(
                    f"DELETE FROM transfers WHERE id IN ({placeholders})",
                    tuple(ids),
                )
