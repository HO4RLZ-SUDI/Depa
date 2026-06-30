# ElderCare AI — local data store + optional cloud mirror (Data Analytics backbone).
#
# Every event (fall, SOS, vitals, medication, inactivity) is written to a local
# SQLite file first — that guarantees zero data loss with no network. If a cloud
# endpoint is configured it is mirrored asynchronously; a cloud failure never
# blocks care logic.

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import requests

import config


class Database:
    def __init__(self, path: str = config.DB_PATH):
        # check_same_thread=False: several worker threads write here; we guard
        # every access with a single lock so writes stay serialized and safe.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL,
                    kind       TEXT NOT NULL,     -- fall|sos|inactivity|temp|med|med_missed|info
                    severity   TEXT NOT NULL,     -- info|warning|critical
                    message    TEXT NOT NULL,
                    data       TEXT,              -- JSON blob
                    acked      INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS vitals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL,
                    temp_c     REAL,
                    humidity   REAL,
                    motion     INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
                CREATE INDEX IF NOT EXISTS idx_vitals_ts ON vitals(ts);
                """
            )
            self._conn.commit()

    # --- writes ----------------------------------------------------------
    def log_event(self, kind: str, severity: str, message: str, data: dict | None = None) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(data or {})
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (ts, kind, severity, message, data) VALUES (?,?,?,?,?)",
                (ts, kind, severity, message, payload),
            )
            self._conn.commit()
            event_id = cur.lastrowid
        self._mirror_to_cloud(
            {"id": event_id, "ts": ts, "kind": kind, "severity": severity,
             "message": message, "data": data or {}}
        )
        return event_id

    def log_vitals(self, temp_c: float, humidity: float, motion: bool):
        ts = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO vitals (ts, temp_c, humidity, motion) VALUES (?,?,?,?)",
                (ts, temp_c, humidity, 1 if motion else 0),
            )
            self._conn.commit()

    def ack_event(self, event_id: int):
        with self._lock:
            self._conn.execute("UPDATE events SET acked = 1 WHERE id = ?", (event_id,))
            self._conn.commit()

    # --- reads (for the dashboard + analytics) ---------------------------
    def recent_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, kind, severity, message, data, acked "
                "FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "ts": r[1], "kind": r[2], "severity": r[3],
             "message": r[4], "data": json.loads(r[5] or "{}"), "acked": bool(r[6])}
            for r in rows
        ]

    def last_motion_time(self) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ts FROM vitals WHERE motion = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def events_since(self, since: datetime, kind: str | None = None,
                     unacked_only: bool = False) -> list[dict]:
        q = "SELECT id, ts, kind, severity, message, acked FROM events WHERE ts >= ?"
        args: list = [since.isoformat(timespec="seconds")]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        if unacked_only:
            q += " AND acked = 0"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [{"id": r[0], "ts": r[1], "kind": r[2], "severity": r[3],
                 "message": r[4], "acked": bool(r[5])} for r in rows]

    def ack_all_unacked(self) -> int:
        """Mark every un-acknowledged event as acked; returns rows affected."""
        with self._lock:
            cur = self._conn.execute("UPDATE events SET acked = 1 WHERE acked = 0")
            self._conn.commit()
            return cur.rowcount

    def latest_vitals(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ts, temp_c, humidity, motion FROM vitals ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"ts": row[0], "temp_c": row[1], "humidity": row[2], "motion": bool(row[3])}

    # --- cloud mirror ----------------------------------------------------
    def _mirror_to_cloud(self, record: dict):
        if not config.CLOUD_SYNC_URL:
            return
        threading.Thread(target=self._cloud_post, args=(record,), daemon=True).start()

    def _cloud_post(self, record: dict):
        try:
            headers = {"Content-Type": "application/json"}
            if config.CLOUD_SYNC_TOKEN:
                headers["Authorization"] = f"Bearer {config.CLOUD_SYNC_TOKEN}"
            requests.post(config.CLOUD_SYNC_URL, json=record, headers=headers, timeout=8)
        except Exception as exc:  # cloud is best-effort; never crash care logic
            print(f"[db] cloud sync failed (non-fatal): {exc}")
