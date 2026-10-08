"""Persistent broker-neutral FX paper execution."""
import math,sqlite3,time,uuid
from forex_risk import FXRisk
class ForexPaperBroker:
    def __init__(self,path,risk=None):
        self.path=path;self.risk=risk or FXRisk();db=self._db()
        db.execute("CREATE TABLE IF NOT EXISTS fx_account(id INTEGER PRIMARY KEY CHECK(id=1),cash REAL NOT NULL,realized_pnl REAL NOT NULL,day TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS fx_positions(id TEXT PRIMARY KEY,pair TEXT NOT NULL,side TEXT NOT NULL,units REAL NOT NULL,entry_price REAL NOT NULL,opened REAL NOT NULL,notional REAL NOT NULL)")
        if not db.execute("SELECT 1 FROM fx_account WHERE id=1").fetchone():
            db.execute("INSERT INTO fx_account VALUES(1,?,?,?)",(self.risk.config.starting_cash,0.0,self._today()))
        db.commit();db.close()
    def _db(self):return sqlite3.connect(self.path,timeout=15)
    def _today(self):return time.strftime("%Y-%m-%d",time.gmtime())
    def _account(self,db):
        row=db.execute("SELECT cash,realized_pnl,day FROM fx_account WHERE id=1").fetchone()
        if not row:raise ValueError("FX account is unavailable.")
        cash,pnl,day=row
        today=self._today()
        if day!=today:
            db.execute("UPDATE fx_account SET realized_pnl=0,day=? WHERE id=1",(today,));pnl=0.0
        return float(cash),float(pnl),today
    def _quote_to_usd(self,pair,price):
        base,quote=pair.upper().split("/",1)
        if quote=="USD": return 1.0
        if base=="USD": return 1.0/price
        raise ValueError(f"No built-in USD conversion for {pair}")
    def snapshot(self,prices):
        db=self._db()
        try:
            cash,pnl,day=self._account(db);db.commit()
            rows=db.execute("SELECT id,pair,side,units,entry_price,opened,notional FROM fx_positions").fetchall();positions=[];equity=cash
            for iid,pair,side,units,entry,opened,notional in rows:
                price=(prices.get(pair) or {}).get("price");u=0.0
                if isinstance(price,(int,float)) and price>0:u=float(units)*(float(price)-float(entry))*(1 if side=="buy" else -1)*self._quote_to_usd(pair,float(price));equity+=u
                positions.append({"id":iid,"pair":pair,"side":side,"units":units,"entry_price":entry,"opened":opened,"notional":notional,"unrealized_pnl":u})
            return {"cash":cash,"realized_pnl":pnl,"equity":equity,"positions":positions,"exposure":sum(float(p["notional"]) for p in positions)}
        finally:db.close()
    def open(self,pair,price,notional,side):
        if side not in ("buy","sell") or not isinstance(pair,str) or "/" not in pair:raise ValueError("Invalid FX order.")
        price=float(price);notional=float(notional)
        if not math.isfinite(price) or price<=0:raise ValueError("Invalid FX price.")
        db=self._db()
        try:
            with db:
                cash,pnl,_=self._account(db)
                rows=db.execute("SELECT * FROM fx_positions").fetchall();exposure=sum(float(r[6]) for r in rows)
                if db.execute("SELECT 1 FROM fx_positions WHERE pair=?",(pair,)).fetchone():raise ValueError("An FX position already exists for this pair.")
                self.risk.validate_daily_loss(pnl);self.risk.validate_entry(cash,exposure,rows,notional)
                iid=uuid.uuid4().hex;units=notional/price
                db.execute("INSERT INTO fx_positions VALUES(?,?,?,?,?,?,?)",(iid,pair,side,units,price,time.time(),notional))
                return {"id":iid,"pair":pair,"side":side,"units":units,"entry_price":price,"notional":notional}
        finally:db.close()
    def close(self,iid,price):
        db=self._db()
        try:
            with db:
                row=db.execute("SELECT id,pair,side,units,entry_price FROM fx_positions WHERE id=?",(iid,)).fetchone()
                if not row:raise ValueError("Unknown FX position.")
                _,pair,side,units,entry=row;price=float(price)
                if not math.isfinite(price) or price<=0:raise ValueError("Invalid FX price.")
                pnl=float(units)*(price-float(entry))*(1 if side=="buy" else -1)*self._quote_to_usd(pair,price)
                cash,realized,_=self._account(db)
                db.execute("UPDATE fx_account SET cash=?,realized_pnl=? WHERE id=1",(cash+pnl,realized+pnl));db.execute("DELETE FROM fx_positions WHERE id=?",(iid,))
                return {"id":iid,"pair":pair,"side":side,"pnl":pnl,"exit_price":price}
        finally:db.close()
