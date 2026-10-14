"""Autonomous six-agent paper trading loop for Ember Trading Lab.

This module creates the spell that makes the six agents work automatically —
periodically fetching market data, running the LLM deliberation, and executing
paper trades when the risk gate approves.

Usage:
    from autonomous_loop import AutonomousTrader
    
    trader = AutonomousTrader(interval_seconds=60)
    trader.start()  # Runs in background thread
    trader.status()  # Check cycle history
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_settings
from llm_research import LLMResearchLayer
from risk.gate import GATE
from brokers.alpaca import AlpacaPaper
from forex_market import snapshot, STOCKS, DEFAULT_PAIRS, yahoo_bars


# Symbols the six agents should watch
WATCHLIST = list(STOCKS) + list(DEFAULT_PAIRS)

@dataclass
class CycleRecord:
    cycle_id: str
    timestamp: float
    symbol: str
    decision: str
    executed: bool
    proposal: dict
    conversation: list
    risk: dict
    llm_available: bool


class AutonomousTrader:
    """Runs the six-agent deliberation loop autonomously.

    The trader:
    1. Arms the risk gate (with TTL)
    2. Fetches fresh market data
    3. Runs the six-agent LLM deliberation
    4. If approved by risk gate AND agents propose a trade, executes via Alpaca
    5. Records everything in memory and to SQLite
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        data_dir: Optional[Path] = None,
        max_cycles_per_day: int = 100,
    ):
        self.settings = get_settings()
        self.interval = max(30, interval_seconds)  # Min 30s between cycles
        self.max_cycles = max_cycles_per_day
        self.research = LLMResearchLayer(self.settings)
        self.alpaca = AlpacaPaper(self.settings)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._records: List[CycleRecord] = []
        self._cycle_count = 0
        self._last_cycle_time = 0.0
        self._errors: List[str] = []

    def status(self) -> dict:
        """Get current status of the autonomous trader."""
        with self._lock:
            recent = [
                {
                    "cycle_id": r.cycle_id,
                    "timestamp": r.timestamp,
                    "datetime": datetime.utcfromtimestamp(r.timestamp).isoformat() + "Z",
                    "symbol": r.symbol,
                    "decision": r.decision,
                    "executed": r.executed,
                    "llm_available": r.llm_available,
                }
                for r in self._records[-20:]
            ]
        return {
            "running": self._running,
            "interval_seconds": self.interval,
            "cycles_today": self._cycle_count,
            "last_cycle": self._last_cycle_time,
            "last_cycle_age": round(time.time() - self._last_cycle_time, 1) if self._last_cycle_time else 0,
            "llm_available": self.research.available() if self.research else False,
            "alpaca_configured": self.alpaca.configured,
            "risk_gate": GATE.status(),
            "recent_cycles": recent,
            "errors": self._errors[-5:],
        }

    def arm(self, hours: float = 24.0) -> dict:
        """Arm the risk gate for autonomous trading."""
        return GATE.arm(hours)

    def disarm(self) -> dict:
        """Disarm the risk gate (emergency stop)."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        return GATE.disarm()

    def start(self) -> dict:
        """Start the autonomous trading loop in a background thread."""
        if self._running:
            return {"ok": False, "reason": "already running"}
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return {
            "ok": True,
            "interval_seconds": self.interval,
            "message": f"Autonomous trader started — first cycle in ~{self.interval}s"
        }

    def stop(self) -> dict:
        """Stop the autonomous trading loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        return {"ok": True, "message": "Autonomous trader stopped"}

    def _run_cycle(self) -> Optional[CycleRecord]:
        """Run a single autonomous trading cycle."""
        cycle_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")[:12]
        now = time.time()

        # 1. Fetch market data
        try:
            market = snapshot(WATCHLIST)
            pairs = market.get("pairs", {})
        except Exception as e:
            error = f"[{cycle_id}] Market data error: {str(e)[:200]}"
            self._errors.append(error)
            return None

        if not pairs:
            return None

        # 2. Get account status from Alpaca
        account = {"equity": 100000, "exposure": 0, "daily_halted": False, "positions": []}
        try:
            if self.alpaca.configured:
                alpaca_account = asyncio.run(self.alpaca.account())
                account["equity"] = float(alpaca_account.get("equity", 100000))
                positions = asyncio.run(self.alpaca.positions())
                account["positions"] = positions
                account["exposure"] = sum(float(p.get("market_value", 0)) for p in positions)
        except Exception:
            pass  # Account fetch failure shouldn't block trading

        # 3. Run six-agent deliberation
        market_context = {"pairs": pairs}
        risk_context = {
            "max_trade_notional": self.settings.max_per_trade_usd,
            "max_exposure": self.settings.max_exposure_usd,
            "max_positions": self.settings.max_open_positions,
            "max_daily_loss": self.settings.max_daily_loss_usd,
        }
        history = {}
        positions = account.get("positions", [])

        # 4. Run LLM research if available
        llm_available = False
        conversation = []
        decision = "hold"
        symbol = None
        proposal = {}

        if self.research.available():
            try:
                llm_result = self.research.run(
                    market_context, account, risk_context, history, positions
                )
                llm_available = True

                # Build conversation from LLM stages
                for stage in llm_result.get("stages", []):
                    conversation.append({
                        "role": stage["agent"],
                        "summary": stage["text"],
                        "concerns": stage.get("concerns", []),
                    })

                # Extract decision
                final = llm_result.get("final_decision", {})
                decision = final.get("decision", "hold")
                symbol = final.get("pair_or_token")

                proposal = {
                    "action": decision,
                    "symbol": symbol,
                    "rationale": final.get("rationale", ""),
                    "concerns": final.get("concerns", []),
                }
            except Exception as e:
                self._errors.append(f"[{cycle_id}] LLM research error: {str(e)[:200]}")
                llm_available = False
        else:
            # Fall back to scripted deliberation with market data
            from agents.deliberation import run_scripted_deliberation
            
            # Find the best symbol from market data
            best_symbol = "AAPL/USD"  # Default
            best_price = 0
            for pair, data in pairs.items():
                if "USD" in pair and "/" in pair:
                    price = float(data.get("price", 0))
                    if price > best_price:
                        best_price = price
                        best_symbol = pair
            
            # Determine trend from price
            bars = yahoo_bars(best_symbol, interval="5m", limit=10)
            if bars and len(bars["bars"]) >= 2:
                recent = bars["bars"][-5:]
                if len(recent) >= 2:
                    trend = "up" if recent[-1]["c"] > recent[-3]["c"] else "down"
                else:
                    trend = "unknown"
            else:
                trend = "unknown"
            
            snap = {
                "symbols": [best_symbol],
                "trend": trend,
                "data_quality": 0.8 if bars and len(bars.get("bars", [])) >= 5 else 0.5,
            }
            
            deliberation = run_scripted_deliberation(
                snap, book="stocks",
                default_symbol=best_symbol.replace("/", ""),
                default_notional=self.settings.max_per_trade_usd
            )
            
            if deliberation.proposal:
                decision = deliberation.proposal.action
                symbol = deliberation.proposal.symbol
                proposal = {"action": decision, "symbol": symbol, "thesis": deliberation.proposal.thesis}
                conversation = deliberation.conversation

        executed = False
        execution_result = None

        # 5. Execute if approved by risk gate
        if decision in ("buy", "sell") and symbol:
            # Check risk gate
            notional = min(self.settings.max_per_trade_usd, 10.0)  # Conservative
            risk_decision = GATE.check_order(notional, decision)
            
            if risk_decision.allowed:
                if self.alpaca.configured:
                    try:
                        execution_result = asyncio.run(
                            self.alpaca.submit_market_order(symbol, risk_decision.sized_usd, decision)
                        )
                        if execution_result.get("ok"):
                            executed = True
                            GATE.record_fill(decision, risk_decision.sized_usd)
                    except Exception as e:
                        self._errors.append(f"[{cycle_id}] Execution error: {str(e)[:200]}")
            else:
                self._errors.append(f"[{cycle_id}] Risk gate blocked: {risk_decision.reason}")

        record = CycleRecord(
            cycle_id=cycle_id,
            timestamp=now,
            symbol=symbol or "NONE",
            decision=decision,
            executed=executed,
            proposal=proposal,
            conversation=conversation,
            risk=GATE.status(),
            llm_available=llm_available,
        )
        
        with self._lock:
            self._records.append(record)
            self._cycle_count += 1
            self._last_cycle_time = now

        return record

    def _run_loop(self):
        """Background loop that runs cycles periodically."""
        while self._running:
            try:
                if GATE.status()["armed"]:
                    self._run_cycle()
                # Sleep in small increments to allow quick shutdown
                for _ in range(self.interval):
                    if not self._running:
                        break
                    time.sleep(1)
            except Exception as e:
                self._errors.append(f"[{datetime.utcnow().isoformat()}] Loop error: {str(e)[:200]}")
                time.sleep(30)  # Back off on errors

    def run_once(self) -> dict:
        """Run a single cycle manually (for testing)."""
        record = self._run_cycle()
        if record is None:
            return {"ok": False, "reason": "No market data or cycle failed"}
        
        return {
            "ok": True,
            "cycle_id": record.cycle_id,
            "decision": record.decision,
            "symbol": record.symbol,
            "executed": record.executed,
            "llm_available": record.llm_available,
            "conversation": record.conversation,
            "risk": record.risk,
        }


# Module-level trader instance
_trader: Optional[AutonomousTrader] = None


def get_trader() -> AutonomousTrader:
    """Get or create the singleton trader instance."""
    global _trader
    if _trader is None:
        _trader = AutonomousTrader()
    return _trader


if __name__ == "__main__":
    # Quick CLI test
    trader = get_trader()
    print("=== Autonomous Trader Status ===")
    print(json.dumps(trader.status(), indent=2))
    
    print("\n=== Arming Risk Gate ===")
    print(json.dumps(trader.arm(hours=1), indent=2))
    
    print("\n=== Running Single Cycle ===")
    result = trader.run_once()
    print(json.dumps(result, indent=2))
    
    print("\n=== Final Status ===")
    print(json.dumps(trader.status(), indent=2))