"""Persistent broker-neutral FX paper execution."""
import math,sqlite3,time,uuid
from forex_risk import FXRisk
class ForexPaperBroker:
    def __init__(self,path,risk=None):
        self.path=path;self.risk=risk or FXRisk();db=self._db()
        db.execute("CREATE TABLE IF NOT EXISTS fx_account(id INTEGER PRIMARY KEY CHECK(id=1),cash REAL NOT NULL,realized_pnl REAL NOT NULL,day TEXT NOT NULL, daily_halted INTEGER NOT NULL DEFAULT 0)")
        columns={row[1] for row in db.execute("PRAGMA table_info(fx_account)")}
        if "daily_halted" not in columns: db.execute("ALTER TABLE fx_account ADD COLUMN daily_halted INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE TABLE IF NOT EXISTS fx_positions(id TEXT PRIMARY KEY,pair TEXT NOT NULL,side TEXT NOT NULL,units REAL NOT NULL,entry_price REAL NOT NULL,opened REAL NOT NULL,notional REAL NOT NULL)")
        if not db.execute("SELECT 1 FROM fx_account WHERE id=1").fetchone():
            db.execute("INSERT INTO fx_account(id,cash,realized_pnl,day,daily_halted) VALUES(1,?,?,?,0)",(self.risk.config.starting_cash,0.0,self._today()))
        db.commit();db.close()
    def _db(self):return sqlite3.connect(self.path,timeout=15)
    def _today(self):return time.strftime("%Y-%m-%d",time.gmtime())
    def _account(self,db):
        row=db.execute("SELECT cash,realized_pnl,day,daily_halted FROM fx_account WHERE id=1").fetchone()
        if not row:raise ValueError("FX account is unavailable.")
        cash,pnl,day,halted=row
        today=self._today()
        if day!=today:
            db.execute("UPDATE fx_account SET realized_pnl=0,day=?,daily_halted=0 WHERE id=1",(today,));pnl=0.0;halted=0
        return float(cash),float(pnl),today,bool(halted)
    def _base_to_usd(self,pair,price):
        base,quote=pair.upper().split("/",1)
        if quote=="USD": return float(price)
        if base=="USD": return 1.0
        raise ValueError(f"No built-in USD conversion for {pair}")
    def _quote_to_usd(self,pair,price):
        base,quote=pair.upper().split("/",1)
        if quote=="USD": return 1.0
        if base=="USD":
            if price<=0: raise ValueError("Invalid FX conversion price.")
            return 1.0/price
        raise ValueError(f"No built-in USD conversion for {pair}")
    def snapshot(self,prices):
        db=self._db()
        try:
            cash,pnl,day,halted=self._account(db);db.commit()
            rows=db.execute("SELECT id,pair,side,units,entry_price,opened,notional FROM fx_positions").fetchall()
            positions=[];equity=cash;unrealized_total=0.0;unmarked_positions=[];mark_data_fresh=True
            for iid,pair,side,units,entry,opened,notional in rows:
                quote = prices.get(pair) or {}
                # Mark to the executable close side so unrealized PnL includes
                # spread: longs exit at bid, shorts exit at ask.
                price = quote.get("bid" if side == "buy" else "ask")
                if price is None:
                    price = quote.get("price")  # compatibility for simple test marks
                valid_price=isinstance(price,(int,float)) and math.isfinite(float(price)) and price>0
                observed=quote.get("observed")
                fresh=False
                if isinstance(observed,(int,float)) and math.isfinite(float(observed)):
                    age=time.time()-float(observed)
                    try:
                        provider_day=str(quote.get("provider_date",""))[:10]
                        fresh=(-30.0<=age<=300.0 and provider_day==self._today()
                               and time.strftime("%Y-%m-%d",time.gmtime(float(observed)))==self._today())
                    except (OverflowError,OSError,ValueError):
                        fresh=False
                if not valid_price:
                    unmarked_positions.append(iid)
                    mark_data_fresh=False
                    u=0.0
                else:
                    u=float(units)*(float(price)-float(entry))*(1 if side=="buy" else -1)*self._quote_to_usd(pair,float(price))
                    equity+=u;unrealized_total+=u
                    if not fresh:
                        mark_data_fresh=False
                positions.append({"id":iid,"pair":pair,"side":side,"units":units,"entry_price":entry,"opened":opened,"notional":notional,"unrealized_pnl":u,"mark_valid":bool(valid_price),"mark_fresh":bool(fresh)})
            complete=not unmarked_positions
            return {"cash":cash,"realized_pnl":pnl,"unrealized_pnl":unrealized_total,"daily_pnl":pnl+unrealized_total,"daily_halted":halted,"equity":equity,"positions":positions,"exposure":sum(float(p["notional"]) for p in positions),"mark_data_complete":complete,"mark_data_fresh":mark_data_fresh,"unmarked_positions":unmarked_positions}
        finally:db.close()
    def open(self,pair,price,notional,side,prices=None):
        if side not in ("buy","sell") or not isinstance(pair,str):raise ValueError("Invalid FX order.")
        pair=pair.strip().upper()
        parts=pair.split("/")
        if len(parts)!=2 or any(len(currency)!=3 for currency in parts) or parts[0]==parts[1]:
            raise ValueError("Invalid FX pair.")
        price=float(price);notional=float(notional)
        if not math.isfinite(price) or price<=0:raise ValueError("Invalid FX price.")
        # Validate conversion support before touching account state.
        base_to_usd=self._base_to_usd(pair,price)
        db=self._db()
        try:
            with db:
                cash,pnl,_,halted=self._account(db)
                if halted: raise ValueError("Daily FX loss limit already breached; trading remains halted until the next UTC day.")
                rows=db.execute("SELECT * FROM fx_positions").fetchall();exposure=sum(float(r[6]) for r in rows)
                if db.execute("SELECT 1 FROM fx_positions WHERE pair=?",(pair,)).fetchone():raise ValueError("An FX position already exists for this pair.")
                unrealized = 0.0
                if rows and prices is None:
                    raise ValueError("Current prices for all open FX positions are required to check the daily loss limit.")
                for row in rows:
                    _, open_pair, open_side, units, entry, _, _ = row
                    quote = (prices or {}).get(open_pair)
                    if not isinstance(quote, dict):
                        raise ValueError(f"Missing current price for open FX position {open_pair}.")
                    observed = quote.get("observed")
                    if not isinstance(observed, (int, float)) or not math.isfinite(float(observed)):
                        raise ValueError(f"Missing quote timestamp for open FX position {open_pair}.")
                    age = time.time() - float(observed)
                    if age < -30.0 or age > 300.0:
                        raise ValueError(f"Stale quote for open FX position {open_pair}.")
                    try:
                        provider_day = time.strftime("%Y-%m-%d", time.gmtime(float(observed)))
                    except (OverflowError, OSError, ValueError):
                        raise ValueError(f"Invalid quote timestamp for open FX position {open_pair}.")
                    if str(quote.get("provider_date", ""))[:10] != self._today() or provider_day != self._today():
                        raise ValueError(f"Quote is not dated today for open FX position {open_pair}.")
                    mark = quote.get("bid" if open_side == "buy" else "ask")
                    if not isinstance(mark, (int, float)) or not math.isfinite(float(mark)) or mark <= 0:
                        raise ValueError(f"Invalid executable price for open FX position {open_pair}.")
                    direction = 1 if open_side == "buy" else -1
                    unrealized += float(units) * (float(mark) - float(entry)) * direction * self._quote_to_usd(open_pair, float(mark))
                try:
                    self.risk.validate_daily_loss(pnl + unrealized)
                except ValueError:
                    # Commit the circuit-breaker state before raising; otherwise
                    # the surrounding transaction would roll the halt back.
                    db.execute("UPDATE fx_account SET daily_halted=1 WHERE id=1")
                    db.commit()
                    raise
                self.risk.validate_entry(cash,exposure,rows,notional,pair=pair,side=side)
                iid=uuid.uuid4().hex;units=notional/base_to_usd
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
                cash,realized,_,_=self._account(db)
                db.execute("UPDATE fx_account SET cash=?,realized_pnl=? WHERE id=1",(cash+pnl,realized+pnl));db.execute("DELETE FROM fx_positions WHERE id=?",(iid,))
                return {"id":iid,"pair":pair,"side":side,"pnl":pnl,"exit_price":price}
        finally:db.close()
