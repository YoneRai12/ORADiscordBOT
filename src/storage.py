"""SQLite-backed storage helpers for the ORA bot."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  discord_user_id TEXT PRIMARY KEY,
  google_sub TEXT,
  privacy TEXT NOT NULL DEFAULT 'private',
  speak_search_progress INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_states (
  state TEXT PRIMARY KEY,
  discord_user_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  discord_user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  source_url TEXT,
  created_at INTEGER NOT NULL
);
"""


class Store:
    """Async wrapper around the SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Initialise tables and run lightweight migrations."""

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
            try:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN speak_search_progress INTEGER NOT NULL DEFAULT 0"
                )
                await db.commit()
            except aiosqlite.OperationalError:
                # Column already exists; ignore.
                await db.rollback()

    async def ensure_user(
        self,
        discord_user_id: int,
        privacy_default: str,
        speak_search_default: int,
    ) -> None:
        """Ensure the user row exists with default privacy and speak settings."""

        now = int(time.time())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                (
                    "INSERT INTO users(discord_user_id, privacy, speak_search_progress, created_at) "
                    "VALUES(?, ?, ?, ?) ON CONFLICT(discord_user_id) DO NOTHING"
                ),
                (str(discord_user_id), privacy_default, speak_search_default, now),
            )
            await db.commit()

    async def set_privacy(self, discord_user_id: int, mode: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE users SET privacy=? WHERE discord_user_id=?",
                (mode, str(discord_user_id)),
            )
            await db.commit()

    async def get_privacy(self, discord_user_id: int) -> str:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT privacy FROM users WHERE discord_user_id=?",
                (str(discord_user_id),),
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else "private"

    async def upsert_google_sub(self, discord_user_id: int, google_sub: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                (
                    "INSERT INTO users(discord_user_id, google_sub, privacy, speak_search_progress, created_at) "
                    "VALUES(?, ?, 'private', 0, ?) "
                    "ON CONFLICT(discord_user_id) DO UPDATE SET google_sub=excluded.google_sub"
                ),
                (str(discord_user_id), google_sub, int(time.time())),
            )
            await db.commit()

    async def get_google_sub(self, discord_user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT google_sub FROM users WHERE discord_user_id=?",
                (str(discord_user_id),),
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row and row[0] else None

    async def start_login_state(self, state: str, discord_user_id: int, ttl_sec: int = 900) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                (
                    "INSERT OR REPLACE INTO login_states(state, discord_user_id, expires_at) "
                    "VALUES(?, ?, ?)"
                ),
                (state, str(discord_user_id), int(time.time()) + ttl_sec),
            )
            await db.commit()

    async def consume_login_state(self, state: str) -> Optional[str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT discord_user_id, expires_at FROM login_states WHERE state=?",
                (state,),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            return None

        discord_user_id, expires_at = row
        if int(time.time()) > int(expires_at):
            async with aiosqlite.connect(self._db_path) as cleanup:
                await cleanup.execute("DELETE FROM login_states WHERE state=?", (state,))
                await cleanup.commit()
            return None

        async with aiosqlite.connect(self._db_path) as cleanup:
            await cleanup.execute("DELETE FROM login_states WHERE state=?", (state,))
            await cleanup.commit()
        return str(discord_user_id)

    async def add_dataset(
        self, discord_user_id: int, name: str, source_url: Optional[str]
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                (
                    "INSERT INTO datasets(discord_user_id, name, source_url, created_at) "
                    "VALUES(?, ?, ?, ?)"
                ),
                (str(discord_user_id), name, source_url, int(time.time())),
            )
            await db.commit()
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    async def list_datasets(
        self, discord_user_id: int, limit: int = 10
    ) -> Sequence[Tuple[int, str, Optional[str], int]]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                (
                    "SELECT id, name, source_url, created_at FROM datasets "
                    "WHERE discord_user_id=? ORDER BY id DESC LIMIT ?"
                ),
                (str(discord_user_id), limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(int(r[0]), str(r[1]), r[2], int(r[3])) for r in rows]

    async def set_search_progress_flag(self, discord_user_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE users SET speak_search_progress=? WHERE discord_user_id=?",
                (1 if enabled else 0, str(discord_user_id)),
            )
            await db.commit()

    async def get_search_progress_flag(self, discord_user_id: int) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT speak_search_progress FROM users WHERE discord_user_id=?",
                (str(discord_user_id),),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
