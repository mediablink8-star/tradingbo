"""Deterministic FX backtesting engine with costs and mark-to-market metrics."""
from dataclasses import dataclass
from typing import Callable
import math,statistics
@dataclass(frozen=True)
class Candle:
    timestamp:float
    open:float
    high:float
    low:float
    close:float
@dataclass
class Trade:
    side:str;entry_time:float;entry_price:float;exit_time:float;exit_price:float;pnl:float
class FXBacktester:
    def __init__(self,starting_cash=10000.0,spread_bps=1.0,slippage_bps=0.5,notional=500.0,periods_per_year=None):
        self.starting_cash=float(starting_cash);self.spread_bps=float(spread_bps);self.slippage_bps=float(slippage_bps);self.notional=float(notional);self.periods_per_year=periods_per_year
    def _exec(self,price,side,opening):
        half=self.spread_bps/20000;slip=self.slippage_bps/10000
        if opening:return price*(1+half+slip) if side=="buy" else price*(1-half-slip)
        return price*(1-half-slip) if side=="buy" else price*(1+half+slip)
    def _unrealized(self,position,mark):
        if not position:return 0.0
        direction=1 if position["side"]=="buy" else -1
        return (mark-position["entry_price"])*direction*(self.notional/position["entry_price"])
    def _annualization(self,candles):
        if self.periods_per_year is not None:return max(float(self.periods_per_year),1.0)
        gaps=[b.timestamp-a.timestamp for a,b in zip(candles,candles[1:]) if b.timestamp>a.timestamp]
        if not gaps:return 252.0
        median_gap=statistics.median(gaps)
        return max(1.0,31536000.0/median_gap)
    def run(self,candles:list[Candle],signal:Callable[[list[Candle]],str|None]):
        empty={"starting_cash":self.starting_cash,"ending_cash":self.starting_cash,"return_pct":0.0,"trades":[],"win_rate":0.0,"profit_factor":0.0,"expectancy":0.0,"sharpe":0.0,"max_drawdown":0.0,"history":[]}
        if not candles:return empty
        cash=self.starting_cash;position=None;trades=[];history=[]
        for i,c in enumerate(candles):
            action=signal(candles[:i+1])
            if position is None and action in ("buy","sell"):
                position={"side":action,"entry_time":c.timestamp,"entry_price":self._exec(c.close,action,True)}
            elif position is not None and (action==("sell" if position["side"]=="buy" else "buy") or action=="flat"):
                exit_price=self._exec(c.close,position["side"],False);direction=1 if position["side"]=="buy" else -1
                pnl=(exit_price-position["entry_price"])*direction*(self.notional/position["entry_price"]);cash+=pnl
                trades.append(Trade(position["side"],position["entry_time"],position["entry_price"],c.timestamp,exit_price,pnl));position=None
            mark=c.close
            history.append({"timestamp":c.timestamp,"equity":cash+self._unrealized(position,mark),"position":position["side"] if position else None})
        if position is not None:
            c=candles[-1];exit_price=self._exec(c.close,position["side"],False);direction=1 if position["side"]=="buy" else -1
            pnl=(exit_price-position["entry_price"])*direction*(self.notional/position["entry_price"]);cash+=pnl
            trades.append(Trade(position["side"],position["entry_time"],position["entry_price"],c.timestamp,exit_price,pnl));history[-1]["equity"]=cash
        wins=[t.pnl for t in trades if t.pnl>0];losses=[t.pnl for t in trades if t.pnl<0]
        returns=[];prev=self.starting_cash
        for h in history:
            returns.append((h["equity"]/prev)-1 if prev else 0);prev=h["equity"]
        mean=statistics.mean(returns) if returns else 0;sd=statistics.stdev(returns) if len(returns)>1 else 0
        sharpe=(mean/sd*math.sqrt(self._annualization(candles))) if sd else 0
        peak=self.starting_cash;max_dd=0
        for h in history:
            peak=max(peak,h["equity"]);max_dd=max(max_dd,peak-h["equity"])
        gross_profit=sum(wins);gross_loss=abs(sum(losses))
        pf=gross_profit/gross_loss if gross_loss else (math.inf if gross_profit else 0)
        expectancy=statistics.mean([t.pnl for t in trades]) if trades else 0
        return {"starting_cash":self.starting_cash,"ending_cash":cash,"return_pct":(cash/self.starting_cash-1)*100,"trades":[t.__dict__ for t in trades],"win_rate":len(wins)/len(trades)*100 if trades else 0.0,"profit_factor":pf,"expectancy":expectancy,"sharpe":sharpe,"max_drawdown":max_dd,"history":history}
