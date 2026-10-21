"""Fail-closed control primitives for a future local IBKR executor.

This module deliberately does not connect to IB Gateway or submit orders. It
keeps the hosted dashboard's AI process separate from broker credentials and
defines the local operator lease that a later, reviewed adapter must enforce.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import time
from typing import Optional


@dataclass(frozen=True)
class ExecutorSnapshot:
    connected: bool
    armed_until: float
    kill_switch: bool
    last_heartbeat: float
    reason: str


class LocalExecutorGate:
    """In-memory, fail-closed arm/heartbeat/kill gate for one local process.

    A production adapter must persist and audit these transitions, validate
    broker-side positions/orders, and re-check this gate immediately before
    every submission. This class alone is not an execution system.
    """

    def __init__(self, heartbeat_ttl: float = 30.0, max_arm_seconds: float = 3600.0):
        if heartbeat_ttl <= 0 or max_arm_seconds <= 0:
            raise ValueError("lease durations must be positive")
        self.heartbeat_ttl = float(heartbeat_ttl)
        self.max_arm_seconds = float(max_arm_seconds)
        self._lock = RLock()
        self._connected = False
        self._armed_until = 0.0
        self._kill_switch = True
        self._last_heartbeat = 0.0
        self._reason = "executor starts disarmed"

    def heartbeat(self, connected: bool = True, now: Optional[float] = None) -> ExecutorSnapshot:
        stamp = time() if now is None else float(now)
        with self._lock:
            self._connected = bool(connected)
            self._last_heartbeat = stamp if connected else 0.0
            if not connected:
                self._armed_until = 0.0
                self._kill_switch = True
                self._reason = "broker connection lost; disarmed"
            else:
                self._reason = "heartbeat received"
            return self.snapshot(stamp)

    def arm(self, duration_seconds: float, now: Optional[float] = None) -> ExecutorSnapshot:
        stamp = time() if now is None else float(now)
        duration = float(duration_seconds)
        with self._lock:
            if duration <= 0 or duration > self.max_arm_seconds:
                raise ValueError("arm duration outside configured lease")
            if not self._is_fresh(stamp):
                self._armed_until = 0.0
                self._kill_switch = True
                self._reason = "cannot arm without a fresh broker heartbeat"
                raise RuntimeError(self._reason)
            self._kill_switch = False
            self._armed_until = stamp + duration
            self._reason = "operator armed local executor"
            return self.snapshot(stamp)

    def disarm(self, reason: str = "operator disarmed", now: Optional[float] = None) -> ExecutorSnapshot:
        stamp = time() if now is None else float(now)
        with self._lock:
            self._kill_switch = True
            self._armed_until = 0.0
            self._reason = str(reason)[:200]
            return self.snapshot(stamp)

    def permits_new_entry(self, now: Optional[float] = None) -> bool:
        stamp = time() if now is None else float(now)
        with self._lock:
            return (
                not self._kill_switch
                and self._connected
                and self._is_fresh(stamp)
                and stamp < self._armed_until
            )

    def snapshot(self, now: Optional[float] = None) -> ExecutorSnapshot:
        stamp = time() if now is None else float(now)
        fresh = self._is_fresh(stamp)
        return ExecutorSnapshot(
            connected=self._connected and fresh,
            armed_until=self._armed_until if stamp < self._armed_until else 0.0,
            kill_switch=self._kill_switch or not fresh or stamp >= self._armed_until,
            last_heartbeat=self._last_heartbeat,
            reason=self._reason if fresh else "heartbeat expired; new entries blocked",
        )

    def _is_fresh(self, now: float) -> bool:
        return (
            self._connected
            and self._last_heartbeat > 0
            and 0 <= now - self._last_heartbeat <= self.heartbeat_ttl
        )
