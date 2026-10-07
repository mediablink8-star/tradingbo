"""Forex dashboard orchestration."""
import time
from forex_market import DEFAULT_PAIRS,snapshot
from forex_paper import ForexPaperBroker
from forex_risk import FXRisk,RiskConfig
MAX_QUOTE_AGE=300.0
class ForexLab:
    def __init__(self,path):
        self.broker=ForexPaperBroker(path,FXRisk(RiskConfig()));self.pairs=list(DEFAULT_PAIRS);self.last=None;self.error=None
    def tick(self):
        try:
            market=snapshot(self.pairs);account=self.broker.snapshot(market["pairs"]);self.last={"market":market,"account":account,"timestamp":time.time()};self.error=None;return self.last
        except Exception as e:self.error=str(e);return self.status()
    def status(self):
        market=(self.last or {}).get("market",{"pairs":{},"source":"No FX observation yet"});return {"mode":"forex_paper","market":market,"account":self.broker.snapshot(market.get("pairs",{})),"risk":self.broker.risk.config.__dict__,"error":self.error}
    def _fresh_quote(self,pair):
        data=self.tick();row=data["market"]["pairs"].get(pair.upper())
        if not row:raise ValueError("No current price for that FX pair.")
        if time.time()-float(row["observed"])>MAX_QUOTE_AGE:raise ValueError("FX quote is stale; paper order rejected.")
        return row
    def open(self,pair,side,notional):
        row=self._fresh_quote(pair)
        execution_price=float(row["ask"] if side=="buy" else row["bid"])
        return {"ok":True,"position":self.broker.open(pair.upper(),execution_price,notional,side),"status":self.status()}
    def close(self,iid):
        data=self.tick();p=next((x for x in data["account"]["positions"] if x["id"]==iid),None)
        if not p:raise ValueError("Unknown FX position.")
        row=self._fresh_quote(p["pair"]);execution_price=float(row["bid"] if p["side"]=="buy" else row["ask"])
        return {"ok":True,"result":self.broker.close(iid,execution_price),"status":self.status()}
