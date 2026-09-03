"""SQLite store-and-forward buffer (WAL) — brief §3.

Řádek = jeden odečet zařízení (payload: dict metrik). Insert v transakci
per poll-cyklus (šetří flash), po ACK serveru se řádky mažou, VACUUM 1×/den.
Dimenzace: 5 zařízení à 30 s ≈ 150–300 MB / měsíc offline.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Buffer:
    def __init__(self, path: str = "/data/buffer.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS rows ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " device_uid TEXT NOT NULL,"
            " ts TEXT NOT NULL,"                 # ISO UTC
            " payload TEXT NOT NULL)")           # JSON {metric: value}
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_rows_ts ON rows (ts)")
        self.db.commit()
        self._last_vacuum = 0.0

    def add_cycle(self, readings: list[tuple[str, str, dict]]) -> None:
        """readings: [(device_uid, iso_ts, metrics_dict)] — jedna transakce za cyklus."""
        if not readings:
            return
        with self.db:
            self.db.executemany(
                "INSERT INTO rows (device_uid, ts, payload) VALUES (?, ?, ?)",
                [(d, t, json.dumps(m)) for d, t, m in readings])

    def next_batch(self, limit: int = 1000) -> list[dict]:
        """Dávka k odeslání — NEJNOVĚJŠÍ NAPŘED (§5: dashboard hned žije, grafy
        se plní od přítomnosti dozadu). Server dedupuje, pořadí mu nevadí."""
        cur = self.db.execute(
            "SELECT id, device_uid, ts, payload FROM rows ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
        return [{"_id": r[0], "device_uid": r[1], "ts": r[2], "metrics": json.loads(r[3])}
                for r in cur.fetchall()]

    def ack(self, ids: list[int]) -> None:
        if not ids:
            return
        with self.db:
            self.db.executemany("DELETE FROM rows WHERE id = ?", [(i,) for i in ids])
        if time.monotonic() - self._last_vacuum > 86400:
            self._last_vacuum = time.monotonic()
            try:
                self.db.execute("VACUUM")
            except sqlite3.OperationalError:
                pass

    def stats(self) -> dict:
        n = self.db.execute("SELECT count(*) FROM rows").fetchone()[0]
        oldest = self.db.execute("SELECT min(ts) FROM rows").fetchone()[0]
        return {"rows": n, "oldest_ts": oldest}
