"""Small, deterministic FX strategy library for research."""
from backtest import Candle
def _ema(values,period):
    if not values:return 0.0
    a=2/(period+1);x=values[0]
    for v in values[1:]:x=a*v+(1-a)*x
    return x
def momentum_ema(fast=10,slow=30):
    def signal(candles:list[Candle]):
        if len(candles)<slow:return None
        closes=[c.close for c in candles];f=_ema(closes[-slow:],fast);s=_ema(closes[-slow:],slow)
        return "buy" if f>s else "sell" if f<s else None
    return signal
def mean_reversion(period=20,z=1.5):
    def signal(candles:list[Candle]):
        if len(candles)<period:return None
        xs=[c.close for c in candles[-period:]];m=sum(xs)/period;sd=(sum((x-m)**2 for x in xs)/period)**0.5
        if not sd:return None
        score=(xs[-1]-m)/sd
        return "buy" if score<=-z else "sell" if score>=z else "flat"
    return signal
def breakout(period=20):
    def signal(candles:list[Candle]):
        if len(candles)<=period:return None
        prior=candles[-period-1:-1];hi=max(c.high for c in prior);lo=min(c.low for c in prior)
        return "buy" if candles[-1].close>hi else "sell" if candles[-1].close<lo else None
    return signal


def default_parameter_grids():
    """Small, auditable research grids for baseline strategy families."""
    return {
        "ema": {
            "fast": [5, 10, 15, 20],
            "slow": [30, 50, 75, 100],
        },
        "mean_reversion": {
            "period": [10, 20, 30, 50],
            "z": [1.0, 1.5, 2.0],
        },
        "breakout": {
            "period": [10, 20, 30, 50],
        },
    }


def default_strategy_candidates():
    """Return deterministic candidate factories with invalid EMA pairs removed."""
    from research_selection import grid_candidates

    grids = default_parameter_grids()
    ema_grid = {
        "fast": [x for x in grids["ema"]["fast"]],
        "slow": [x for x in grids["ema"]["slow"]],
    }
    candidates = []
    for name, factory in grid_candidates("ema", momentum_ema, ema_grid):
        params = dict(part.split("=") for part in name[4:-1].split(","))
        if int(params["fast"]) < int(params["slow"]):
            candidates.append((name, factory))
    candidates.extend(grid_candidates("mean_reversion", mean_reversion, grids["mean_reversion"]))
    candidates.extend(grid_candidates("breakout", breakout, grids["breakout"]))
    return candidates
