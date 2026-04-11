from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class EventRecord:
    cursor: int
    ts_ms: int
    channels: list[str]
    event: dict[str, Any]


@dataclass
class _Subscription:
    id: str
    channels: set[str]
    queue: asyncio.Queue[EventRecord] = field(default_factory=lambda: asyncio.Queue(maxsize=256))

    def matches(self, published_channels: list[str]) -> bool:
        if not self.channels:
            return True
        return any(ch in self.channels for ch in published_channels)


class EventBus:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._subs: dict[str, _Subscription] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                channels TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    async def stop(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def publish(self, channels: list[str], event: dict[str, Any]) -> int:
        if self._conn is None:
            return 0
        ts_ms = int(time.time() * 1000)
        channels_json = json.dumps(channels, ensure_ascii=True)
        payload_json = json.dumps(event, ensure_ascii=True, default=str)
        async with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO app_events(ts_ms, channels, payload) VALUES (?, ?, ?)",
                (ts_ms, channels_json, payload_json),
            )
            self._conn.commit()
            row_id = cursor.lastrowid or 0
        rec = EventRecord(cursor=row_id, ts_ms=ts_ms, channels=channels, event=event)
        for sub in list(self._subs.values()):
            if sub.matches(channels):
                try:
                    sub.queue.put_nowait(rec)
                except asyncio.QueueFull:
                    pass
        return row_id

    async def subscribe(self, channels: list[str]) -> tuple[str, asyncio.Queue[EventRecord]]:
        sub_id = str(uuid.uuid4())
        sub = _Subscription(id=sub_id, channels=set(channels))
        self._subs[sub_id] = sub
        return sub_id, sub.queue

    async def unsubscribe(self, subscription_id: str) -> bool:
        return self._subs.pop(subscription_id, None) is not None

    async def replay(self, channels: list[str], after_cursor: Optional[int], limit: int) -> list[EventRecord]:
        if self._conn is None:
            return []
        q = "SELECT cursor, ts_ms, channels, payload FROM app_events"
        vals: list[Any] = []
        if after_cursor is not None:
            q += " WHERE cursor > ?"
            vals.append(after_cursor)
        q += " ORDER BY cursor ASC LIMIT ?"
        vals.append(max(1, min(limit, 1000)))
        cur = self._conn.execute(q, tuple(vals))
        rows = cur.fetchall()
        channel_set = set(channels)
        result: list[EventRecord] = []
        for row in rows:
            row_channels = json.loads(row[2]) if row[2] else []
            if channel_set and not any(ch in channel_set for ch in row_channels):
                continue
            result.append(
                EventRecord(
                    cursor=int(row[0]),
                    ts_ms=int(row[1]),
                    channels=row_channels,
                    event=json.loads(row[3]) if row[3] else {},
                )
            )
        return result
