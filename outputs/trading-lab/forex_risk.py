"""Deterministic FX risk controls."""
from dataclasses import dataclass
import math,time
@dataclass(frozen=True)
class RiskConfig:
    starting_cash:float=10000.0
    max_trade_notional:float=1000.0
    max_exposure:float=3000.0
    max_positions:int=3
    max_daily_loss:float=200.0
    stop_loss_pct:float=0.01
    take_profit_pct:float=0.02
    max_position_age:float=86400.0
    max_leverage:float=1.0
class FXRisk:
    def __init__(self,config=None):self.config=config or RiskConfig()
    def validate_entry(self,cash,exposure,positions,notional):
        c=self.config
        if not math.isfinite(notional) or not 0<notional<=c.max_trade_notional:raise ValueError("Trade exceeds the FX per-trade notional limit.")
        if len(positions)>=c.max_positions:raise ValueError("Maximum open FX positions reached.")
        if exposure+notional>c.max_exposure:raise ValueError("Maximum FX exposure reached.")
        if not math.isfinite(cash) or cash<0 or notional>cash*c.max_leverage:raise ValueError("Insufficient cash under the configured leverage limit.")
    def validate_daily_loss(self,daily_pnl):
        if not math.isfinite(daily_pnl) or daily_pnl<=-self.config.max_daily_loss:raise ValueError("Daily FX loss limit reached; trading is halted.")
    def exits(self,p,price,now=None):
        now=time.time() if now is None else now
        change=(float(price)/float(p["entry_price"])-1)*(1 if p["side"]=="buy" else -1);c=self.config
        return change<=-c.stop_loss_pct or change>=c.take_profit_pct or now-float(p["opened"])>=c.max_position_age
