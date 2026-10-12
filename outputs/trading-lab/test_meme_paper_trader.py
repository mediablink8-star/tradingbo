import os
import tempfile
import unittest
from meme_paper_trader import MemePaperTrader


def candidate(address="MINT1", **overrides):
    row = {
        "decision": "WATCH", "token_address": address, "symbol": "TEST",
        "score": 88, "liquidity_usd": 50000, "volume_24h_usd": 100000,
        "transactions_24h": 300, "buy_ratio": 0.62,
        "price_change_1h_pct": 6, "price_usd": 0.01,
    }
    row.update(overrides)
    return row


def safe_result(**overrides):
    result = {"status": "CHECKS_COMPLETE", "mint_authority_active": False,
              "freeze_authority_active": False, "highest_finding_severity": "info",
              "top_20_token_accounts_supply_pct": 40}
    result.update(overrides)
    return result


class MemePaperTraderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.temp.name, "paper.sqlite")
        self.now = [1_800_000_000.0]
        self.prices = {"MINT1": 0.01, "MINT2": 0.02}
        self.trader = MemePaperTrader(
            self.db, clock=lambda: self.now[0], initial_cash=1000,
            position_usd=50, fee_bps=30, slippage_bps=50,
        )

    def tearDown(self):
        self.temp.cleanup()

    def price(self, address):
        return self.prices.get(address)

    def test_score_rejection_records_actual_score_and_threshold(self):
        result = self.trader.run_cycle(
            [candidate(score=61.4)], lambda _: safe_result(), self.price)
        decision = result["decisions"][0]
        self.assertEqual(decision["reason"], "score_below_entry_threshold")
        self.assertEqual(decision["score"], 61.4)
        self.assertEqual(decision["min_score"], 70.0)
        event = self.trader.status()["events"][0]
        self.assertEqual(event["details"]["score"], 61.4)
        self.assertEqual(event["details"]["min_score"], 70.0)
        self.assertEqual(self.trader.status()["open_positions_count"], 0)

    def test_score_between_70_and_75_can_pass_paper_score_gate(self):
        result = self.trader.run_cycle(
            [candidate(score=71.4)], lambda _: safe_result(), self.price)
        self.assertEqual(result["decisions"][0]["action"], "OPEN")
        self.assertEqual(result["decisions"][0]["score"], 71.4)
        self.assertEqual(self.trader.status()["open_positions_count"], 1)

    def test_momentum_rejection_records_actual_change_and_limit(self):
        result = self.trader.run_cycle(
            [candidate("CHASE", price_change_1h_pct=30)],
            lambda _: safe_result(), self.price)
        decision = result["decisions"][0]
        self.assertEqual(decision["reason"], "momentum_chase_filter")
        self.assertEqual(decision["price_change_1h_pct"], 30.0)
        self.assertEqual(decision["max_entry_change_1h_pct"], self.trader.max_entry_change_1h_pct)
        event = self.trader.status()["events"][0]
        self.assertEqual(event["details"]["price_change_1h_pct"], 30.0)
        self.assertEqual(event["details"]["max_entry_change_1h_pct"], self.trader.max_entry_change_1h_pct)
        self.assertEqual(self.trader.status()["open_positions_count"], 0)

    def test_opens_paper_position_after_market_and_safety_gates(self):
        result = self.trader.run_cycle([candidate()], lambda _: safe_result(), self.price)
        self.assertEqual(result["decisions"][0]["action"], "OPEN")
        status = self.trader.status()
        self.assertEqual(status["open_positions_count"], 1)
        self.assertLess(status["cash_usd"], 950)
        self.assertFalse(status["execution_enabled"])
        self.assertEqual(status["mode"], "autonomous_paper_trading")

    def test_incomplete_security_check_fails_closed_and_records_errors(self):
        safety = {
            "status": "INCOMPLETE",
            "errors": ["mint_account_check_failed:TimeoutError", "supply_check_failed:HTTPError"],
        }
        result = self.trader.run_cycle(
            [candidate()], lambda _: safety, self.price)
        decision = result["decisions"][0]
        self.assertEqual(decision["reason"], "security_check_incomplete")
        self.assertEqual(decision["safety_status"], "INCOMPLETE")
        self.assertEqual(decision["safety_errors"], safety["errors"])
        event = self.trader.status()["events"][0]
        self.assertEqual(event["details"]["safety_errors"], safety["errors"])
        self.assertEqual(self.trader.status()["open_positions_count"], 0)

    def test_active_authority_and_high_concentration_are_rejected(self):
        for safety, reason in [
            (safe_result(mint_authority_active=True), "active_or_unknown_token_authority"),
            (safe_result(top_20_token_accounts_supply_pct=90, highest_finding_severity="high"), "high_severity_security_finding"),
        ]:
            with self.subTest(reason=reason):
                t = MemePaperTrader(os.path.join(self.temp.name, reason + ".sqlite"),
                                    clock=lambda: self.now[0])
                result = t.run_cycle([candidate()], lambda _, s=safety: s, self.price)
                self.assertEqual(result["decisions"][0]["reason"], reason)
                self.assertEqual(t.status()["open_positions_count"], 0)

    def test_market_filters_block_low_score_and_extreme_pump(self):
        result = self.trader.run_cycle(
            [candidate("LOW", score=60), candidate("PUMP", price_change_1h_pct=50)],
            lambda _: safe_result(), self.price)
        self.assertEqual(len(result["decisions"]), 2)
        self.assertTrue(all(d["action"] == "REJECT" for d in result["decisions"]))
        self.assertEqual(self.trader.status()["open_positions_count"], 0)

    def test_stop_loss_closes_position_and_records_cost_adjusted_pnl(self):
        self.trader.run_cycle([candidate()], lambda _: safe_result(), self.price)
        self.prices["MINT1"] = 0.0087
        result = self.trader.tick(self.price)
        self.assertEqual(result["decisions"][0]["reason"], "STOP_LOSS")
        status = self.trader.status()
        self.assertEqual(status["open_positions_count"], 0)
        closed = next(p for p in status["positions"] if p["status"] == "CLOSED")
        self.assertLess(closed["realized_pnl"], 0)
        self.assertFalse(status["execution_enabled"])

    def test_take_profit_closes_position(self):
        self.trader.run_cycle([candidate()], lambda _: safe_result(), self.price)
        self.prices["MINT1"] = 0.0121
        result = self.trader.tick(self.price)
        self.assertEqual(result["decisions"][0]["reason"], "TAKE_PROFIT")

    def test_position_limit_and_duplicate_guard(self):
        self.trader.max_positions = 1
        self.trader.run_cycle([candidate()], lambda _: safe_result(), self.price)
        result = self.trader.run_cycle(
            [candidate(), candidate("MINT2")], lambda _: safe_result(), self.price)
        reasons = [d.get("reason") for d in result["decisions"]]
        self.assertIn("position_already_open", reasons)
        self.assertIn("max_open_positions_reached", reasons)
        self.assertEqual(self.trader.status()["open_positions_count"], 1)

    def test_state_survives_restart(self):
        self.trader.run_cycle([candidate()], lambda _: safe_result(), self.price)
        restarted = MemePaperTrader(self.db, clock=lambda: self.now[0])
        self.assertEqual(restarted.status()["open_positions_count"], 1)
        self.assertLess(restarted.status()["cash_usd"], 1000)

    def test_max_hold_time_closes_position(self):
        t = MemePaperTrader(self.db, clock=lambda: self.now[0], max_hold_seconds=60)
        t.run_cycle([candidate()], lambda _: safe_result(), self.price)
        self.now[0] += 61
        result = t.tick(self.price)
        self.assertEqual(result["decisions"][0]["reason"], "MAX_HOLD_TIME")


if __name__ == "__main__":
    unittest.main()
