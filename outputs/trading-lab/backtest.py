"""Deterministic FX backtesting engine using OHLC candles.
Signals are supplied by a pure strategy function; execution remains paper-only.
"""
from dataclasses import dataclass
from typing import Callable
@dataclass(frozen=True)
class Candle:
    timestamp:float
    open:float
    high:float
    low:float
    close:float
@dataclass
class Trade:
    side:str
    entry_time:float
    entry_price:float
    exit_time:float
    exit_price:float
    pnl:float
class FXBacktester:
    def __init__(self,starting_cash=10000.0,spread_bps=1.0,slippage_bps=0.5):
        self.starting_cash=float(starting_cash);self.spread_bps=float(spread_bps);self.slippage_bps=float(slippage_bps)
    def _exec(self,price,side,opening):
        half=self.spread_bps/20000;slip=self.slippage_bps/10000
        if opening:
            return price*(1+half+slip) if side=="buy" else price*(1-half-slip)
        return price*(1-half-slip) if side=="buy" else price*(1+half+slip)
    def run(self,candles:list[Candle],signal:Callable[[list[Candle]],str|None]):
        cash=self.starting_cash;position=None;trades=[];history=[]
        for i,c in enumerate(candles):
            action=signal(candles[:i+1])
            if position is None and action in ("buy","sell"):
                position={"side":action,"entry_time":c.timestamp,"entry_price":self._exec(c.close,action,True)}
            elif position is not None and (action==("sell" if position["side"]=="buy" else "buy") or action=="flat"):
                exit_price=self._exec(c.close,position["side"],False)
                direction=1 if position["side"]=="buy" else -1
                pnl=(exit_price-position["entry_price"])*direction*(500/position["entry_price"])
                cash+=pnl
                trades.append(Trade(position["side"],position["entry_time"],position["entry_price"],c.timestamp,exit_price,pnl))
                position=None
            history.append({"timestamp":c.timestamp,"equity":cash,"position":position["side"] if position else None})
        if position is not None:
            c=candles[-1];exit_price=self._exec(c.close,position["side"],False);direction=1 if position["side"]=="buy" else -1
            pnl=(exit_price-position["entry_price"])*direction*(500/position["entry_price"]);cash+=pnl
            trades.append(Trade(position["side"],position["entry_time"],position["entry_price"],c.timestamp,exit_price,pnl))
        wins=[t.pnl for t in trades if t.pnl>0];losses=[t.pnl for t in trades if t.pnl<0]
        peak=self.starting_cash;max_dd=0.0
        for h in history:
            peak=max(peak,h["equity"]);max_dd=max(max_dd,peak-h["equity"])
        return {"starting_cash":self.starting_cash,"ending_cash":cash,"return_pct":(cash/self.starting_cash-1)*100,"trades":[t.__dict__ for t in trades],"win_rate":(len(wins)/len(trades)*100 if trades else 0.0),"max_drawdown":max_dd,"history":history}
