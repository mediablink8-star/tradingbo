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
