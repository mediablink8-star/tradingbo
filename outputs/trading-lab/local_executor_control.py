"""Durable, authenticated control state for a future local FX executor.

This module intentionally has no broker adapter and cannot place orders. It
provides a local-only, fail-closed kill switch plus a signed command ledger so
the eventual IB Gateway adapter has a safe control boundary to build on.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


class CommandRejected(ValueError):
    """A signed executor control command failed validation."""


class LocalExecutorControl:
    """Persist replay-resistant, operator-authenticated control transitions."""

    def __init__(self, database: str | Path, secret: str | bytes,
                 *, max_clock_skew_seconds: float = 30.0):
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(secret_bytes) < 32:
            raise ValueError("executor command secret must be at least 32 bytes")
        if not math.isfinite(max_clock_skew_seconds) or max_clock_skew_seconds <= 0:
            raise ValueError("max clock skew must be positive")
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._secret = secret_bytes
        self.max_clock_skew_seconds = float(max_clock_skew_seconds)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS executor_control (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                kill_switch INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL,
                reason TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS executor_commands (
                command_id TEXT PRIMARY KEY,
                nonce TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                issued_at REAL NOT NULL,
                received_at REAL NOT NULL,
                payload_sha256 TEXT NOT NULL,
                result TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS executor_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at REAL NOT NULL,
                event TEXT NOT NULL,
                command_id TEXT,
                detail TEXT NOT NULL
            )""")
            db.execute(
                "INSERT OR IGNORE INTO executor_control(singleton,kill_switch,updated_at,reason) "
                "VALUES(1,1,?,?)", (time.time(), "executor starts fail-closed")
            )
            # A process restart must never restore an armed state.
            db.execute(
                "UPDATE executor_control SET kill_switch=1, updated_at=?, "
                "reason='process restarted; disarmed by default' WHERE singleton=1",
                (time.time(),),
            )
            db.execute(
                "INSERT INTO executor_audit(at,event,detail) VALUES(?,?,?)",
                (time.time(), "startup_disarmed", "No broker adapter is installed; entries are disabled."),
            )
            db.commit()

    @staticmethod
    def canonical_body(body: Mapping[str, Any]) -> bytes:
        if not isinstance(body, Mapping):
            raise CommandRejected("command body must be a JSON object")
        try:
            return json.dumps(body, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CommandRejected("command body must contain finite JSON values") from exc

    @staticmethod
    def signing_message(issued_at: str, nonce: str, body: Mapping[str, Any]) -> bytes:
        return issued_at.encode("ascii") + b"." + nonce.encode("ascii") + b"." + LocalExecutorControl.canonical_body(body)

    def sign(self, issued_at: str, nonce: str, body: Mapping[str, Any]) -> str:
        """Create a command signature for local integration tests and clients."""
        return hmac.new(self._secret, self.signing_message(issued_at, nonce, body),
                        hashlib.sha256).hexdigest()

    def apply_command(self, body: Mapping[str, Any], *, issued_at: str,
                      nonce: str, signature: str, now: float | None = None) -> dict[str, Any]:
        stamp = time.time() if now is None else float(now)
        if not math.isfinite(stamp):
            raise CommandRejected("invalid receiver timestamp")
        if not nonce or len(nonce) > 128 or any(c.isspace() for c in nonce):
            raise CommandRejected("invalid command nonce")
        try:
            issued = float(issued_at)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CommandRejected("invalid command timestamp") from exc
        if not math.isfinite(issued) or abs(stamp - issued) > self.max_clock_skew_seconds:
            raise CommandRejected("command expired or clock skew exceeds policy")
        command_id = str(body.get("command_id") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if not command_id or len(command_id) > 128:
            raise CommandRejected("command_id is required")
        if action not in {"disarm", "kill"}:
            raise CommandRejected("only disarm and kill commands are supported; broker execution is unavailable")
        canonical = self.canonical_body(body)
        expected = hmac.new(self._secret, self.signing_message(str(issued_at), nonce, body),
                             hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(signature or "")):
            raise CommandRejected("invalid command signature")
        digest = hashlib.sha256(canonical).hexdigest()
        with self._lock, closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO executor_commands(command_id,nonce,action,issued_at,received_at,payload_sha256,result) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (command_id, nonce, action, issued, stamp, digest, "accepted_disarmed"),
                )
                db.execute(
                    "UPDATE executor_control SET kill_switch=1,updated_at=?,reason=? WHERE singleton=1",
                    (stamp, "operator kill command" if action == "kill" else "operator disarm command"),
                )
                db.execute(
                    "INSERT INTO executor_audit(at,event,command_id,detail) VALUES(?,?,?,?)",
                    (stamp, action, command_id, digest),
                )
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise CommandRejected("command id or nonce has already been used") from exc
        return {"ok": True, "command_id": command_id, "kill_switch": True,
                "entries_permitted": False, "result": "accepted_disarmed"}

    def status(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            row = db.execute("SELECT kill_switch,updated_at,reason FROM executor_control WHERE singleton=1").fetchone()
            latest = db.execute("SELECT event,at FROM executor_audit ORDER BY id DESC LIMIT 1").fetchone()
        return {"service": "local-executor-control", "broker_adapter": "not_installed",
                "broker_connected": False, "live_order_submission": False,
                "kill_switch": bool(row["kill_switch"]), "entries_permitted": False,
                "updated_at": row["updated_at"], "reason": row["reason"],
                "last_audit_event": latest["event"] if latest else None,
                "last_audit_at": latest["at"] if latest else None}
