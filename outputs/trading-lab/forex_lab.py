"""Forex dashboard orchestration with fail-closed quote checks and paper exits."""
import datetime
import time

from forex_market import DEFAULT_PAIRS, snapshot
from forex_paper import ForexPaperBroker
from forex_risk import FXRisk, RiskConfig

MAX_QUOTE_AGE = 300.0


class ForexLab:
    def __init__(self, path):
        self.broker = ForexPaperBroker(path, FXRisk(RiskConfig()))
        self.pairs = list(DEFAULT_PAIRS)
        self.last = None
        self.error = None
        self.last_exit_events = []

    @staticmethod
    def _provider_date_is_today(value):
        if not value:
            return False
        try:
            # Providers may return either YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.
            provider_day = datetime.datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError):
            return False
        return provider_day == datetime.datetime.now(datetime.timezone.utc).date()

    def _quote_is_current(self, row):
        if not isinstance(row, dict):
            return False
        try:
            observed = float(row.get("observed", 0))
        except (TypeError, ValueError):
            return False
        age = time.time() - observed
        # Allow small clock skew, but never accept a quote timestamp materially
        # in the future or one older than the executable-quote freshness window.
        if not observed or age < -30.0 or age > MAX_QUOTE_AGE:
            return False
        return self._provider_date_is_today(row.get("provider_date"))

    def tick(self):
        try:
            market = snapshot(self.pairs)
            exit_events = []
            # Evaluate stops only with a current provider observation. Daily ECB
            # reference rates are intentionally not treated as executable prices.
            before = self.broker.snapshot(market["pairs"])
            for position in before["positions"]:
                row = market["pairs"].get(position["pair"])
                if not self._quote_is_current(row):
                    continue
                exit_price = float(
                    row["bid"] if position["side"] == "buy" else row["ask"]
                )
                if self.broker.risk.exits(position, exit_price, time.time()):
                    result = self.broker.close(position["id"], exit_price)
                    exit_events.append({
                        "position_id": position["id"],
                        "pair": position["pair"],
                        "reason": "risk_exit",
                        "result": result,
                    })
            account = self.broker.snapshot(market["pairs"])
            self.last_exit_events = exit_events
            self.last = {
                "mode": "forex_paper",
                "market": market,
                "account": account,
                "risk": self.broker.risk.config.__dict__,
                "exit_events": exit_events,
                "timestamp": time.time(),
            }
            self.error = None
            return self.last
        except Exception as exc:
            self.error = str(exc)
            return self.status()

    def status(self):
        market = (self.last or {}).get(
            "market", {"pairs": {}, "source": "No FX observation yet"}
        )
        return {
            "mode": "forex_paper",
            "market": market,
            "account": self.broker.snapshot(market.get("pairs", {})),
            "risk": self.broker.risk.config.__dict__,
            "exit_events": self.last_exit_events,
            "error": self.error,
        }

    def _fresh_quote(self, pair, data=None):
        data = self.tick() if data is None else data
        row = data["market"]["pairs"].get(pair.upper())
        if not row:
            raise ValueError("No current price for that FX pair.")
        if not self._quote_is_current(row):
            raise ValueError(
                "FX quote is stale or not dated today; paper order rejected. "
                "ECB reference rates are for research, not executable quotes."
            )
        return row

    def open(self, pair, side, notional):
        if not isinstance(pair, str):
            raise ValueError("Invalid FX pair.")
        if side not in ("buy", "sell"):
            raise ValueError("Invalid FX side.")
        data = self.tick()
        row = self._fresh_quote(pair, data)
        execution_price = float(row["ask"] if side == "buy" else row["bid"])
        return {
            "ok": True,
            "position": self.broker.open(
                pair.upper(), execution_price, notional, side,
                prices=data["market"]["pairs"],
            ),
            "status": self.status(),
        }

    def close(self, iid):
        data = self.tick()
        position = next(
            (x for x in data["account"]["positions"] if x["id"] == iid),
            None,
        )
        if not position:
            raise ValueError("Unknown FX position; it may already have been closed.")
        row = self._fresh_quote(position["pair"], data)
        execution_price = float(
            row["bid"] if position["side"] == "buy" else row["ask"]
        )
        return {
            "ok": True,
            "result": self.broker.close(iid, execution_price),
            "status": self.status(),
        }
