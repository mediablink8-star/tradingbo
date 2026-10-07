"""Production-style shadow execution ledger.

This module consumes agent decisions but never signs or broadcasts transactions.
It prices simulated fills from fresh executable Jupiter quotes, persists every
intent/fill/reconciliation event, and is deliberately independent of wallet
credentials.
"""
import hashlib, json, math, sqlite3, time, uuid
from dataclasses import dataclass

MAX_TRADE_USDC = 10.0
MAX_DAILY_USDC = 25.0
MAX_OPEN_POSITIONS = 3
MAX_EXPOSURE_USDC = 25.0
STALE_SECONDS = 30.0

@dataclass(frozen=True)
class ShadowConfig:
    max_trade_usdc: float = MAX_TRADE_USDC
    daily_budget_usdc: float = MAX_DAILY_USDC
    max_open_positions: int = MAX_OPEN_POSITIONS
    max_exposure_usdc: float = MAX_EXPOSURE_USDC
    stale_seconds: float = STALE_SECONDS

class ShadowLedger:
    def __init__(self, path, config=None):
        self.path = str(path)
        self.config = config or ShadowConfig()
        db = self._db()
        db.close()

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("""CREATE TABLE IF NOT EXISTS shadow_intents(
            id TEXT PRIMARY KEY, created REAL NOT NULL, day TEXT NOT NULL,
            token TEXT NOT NULL, side TEXT NOT NULL, usd REAL NOT NULL,
            status TEXT NOT NULL, decision_hash TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS shadow_positions(
            token TEXT PRIMARY KEY, units TEXT NOT NULL, cost_usdc REAL NOT NULL,
            entry_price REAL NOT NULL, opened REAL NOT NULL, intent_id TEXT NOT NULL,
            payload TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS shadow_events(
            id INTEGER PRIMARY KEY, received REAL NOT NULL, kind TEXT NOT NULL,
            intent_id TEXT, payload TEXT NOT NULL)""")
        db.commit()
        return db

    @staticmethod
    def _day(ts): return time.strftime("%Y-%m-%d", time.gmtime(ts))

    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",",":")).encode()).hexdigest()

    def _event(self, db, kind, intent_id, payload):
        db.execute("INSERT INTO shadow_events(received,kind,intent_id,payload) VALUES(?,?,?,?)",
                   (time.time(), kind, intent_id, json.dumps(payload, allow_nan=False)))

    def status(self):
        db=self._db()
        try:
            positions=[json.loads(r[0]) for r in db.execute("SELECT payload FROM shadow_positions ORDER BY opened")]
            today=self._day(time.time())
            spent=db.execute("SELECT COALESCE(SUM(usd),0) FROM shadow_intents WHERE day=? AND side='buy' AND status IN ('reserved','filled','reconciled')",(today,)).fetchone()[0]
            unresolved=db.execute("SELECT COUNT(*) FROM shadow_intents WHERE status IN ('reserved','filled')").fetchone()[0]
            return dict(mode="shadow_live",live_money=False,positions=positions,daily_spend=float(spent),
                        daily_remaining=max(0,self.config.daily_budget_usdc-float(spent)),
                        unresolved_intents=int(unresolved),limits=self.config.__dict__)
        finally: db.close()

    def reserve(self, token, side, usd, decision):
        now=time.time()
        if not isinstance(token,str) or not token: raise ValueError("token required")
        if side not in ("buy","sell"): raise ValueError("side must be buy or sell")
        if isinstance(usd,bool) or not isinstance(usd,(int,float)) or not math.isfinite(usd) or usd<=0 or usd>self.config.max_trade_usdc:
            raise ValueError("shadow trade exceeds per-trade limit")
        db=self._db()
        try:
            with db:
                day=self._day(now)
                spent=db.execute("SELECT COALESCE(SUM(usd),0) FROM shadow_intents WHERE day=? AND side='buy' AND status IN ('reserved','filled','reconciled')",(day,)).fetchone()[0]
                if side=="buy" and spent+usd>self.config.daily_budget_usdc: raise ValueError("shadow daily budget exhausted")
                count=db.execute("SELECT COUNT(*) FROM shadow_positions").fetchone()[0]
                exposure=db.execute("SELECT COALESCE(SUM(cost_usdc),0) FROM shadow_positions").fetchone()[0]
                if side=="buy" and count>=self.config.max_open_positions: raise ValueError("shadow position limit reached")
                if side=="buy" and exposure+usd>self.config.max_exposure_usdc: raise ValueError("shadow exposure limit reached")
                if db.execute("SELECT 1 FROM shadow_positions WHERE token=?",(token,)).fetchone() and side=="buy":
                    raise ValueError("shadow position already exists")
                iid=uuid.uuid4().hex
                payload={"id":iid,"token":token,"side":side,"usd":float(usd),"created":now,"decision":decision,"status":"reserved"}
                db.execute("INSERT INTO shadow_intents VALUES(?,?,?,?,?,?,?,?,?)",
                           (iid,now,day,token,side,float(usd),"reserved",self._hash(decision),json.dumps(payload,allow_nan=False)))
                self._event(db,"intent_reserved",iid,payload)
                return payload
        finally: db.close()

    def fill(self, intent_id, units, price, quote, observed_at=None):
        observed_at=observed_at or time.time()
        if isinstance(units,bool) or not isinstance(units,(int,float)) or not math.isfinite(units) or units<=0: raise ValueError("invalid shadow units")
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0: raise ValueError("invalid shadow price")
        if observed_at > time.time()+5 or time.time()-observed_at > self.config.stale_seconds: raise ValueError("shadow quote is stale")
        db=self._db()
        try:
            with db:
                row=db.execute("SELECT payload,status FROM shadow_intents WHERE id=?",(intent_id,)).fetchone()
                if not row: raise ValueError("unknown shadow intent")
                payload=json.loads(row[0])
                if row[1]!="reserved": raise ValueError("shadow intent already processed")
                payload.update(units=float(units),entry_price=float(price),quote=quote,filled_at=time.time(),status="filled")
                db.execute("UPDATE shadow_intents SET status='filled',payload=? WHERE id=?",(json.dumps(payload,allow_nan=False),intent_id))
                if payload["side"]=="buy":
                    db.execute("INSERT OR REPLACE INTO shadow_positions VALUES(?,?,?,?,?,?,?)",
                               (payload["token"],str(units),payload["usd"],float(price),payload["created"],intent_id,json.dumps(payload,allow_nan=False)))
                self._event(db,"intent_filled",intent_id,payload)
                return payload
        finally: db.close()

    def close(self, intent_id, units, price, quote, reason):
        now=time.time()
        db=self._db()
        try:
            with db:
                row=db.execute("SELECT payload,status FROM shadow_intents WHERE id=?",(intent_id,)).fetchone()
                if not row: raise ValueError("unknown shadow entry intent")
                entry=json.loads(row[0])
                if entry["side"]!="buy" or row[1] not in ("filled","reconciled"): raise ValueError("shadow position is not open")
                position=db.execute("SELECT units,cost_usdc,entry_price FROM shadow_positions WHERE token=?",(entry["token"],)).fetchone()
                if not position: raise ValueError("shadow position missing")
                proceeds=float(units)*float(price)
                pnl=proceeds-float(position[1])
                close_id=uuid.uuid4().hex
                payload={"id":close_id,"token":entry["token"],"side":"sell","units":float(units),"price":float(price),"proceeds":proceeds,"pnl":pnl,"reason":reason,"entry_intent_id":intent_id,"created":now,"status":"reconciled","quote":quote}
                db.execute("INSERT INTO shadow_intents VALUES(?,?,?,?,?,?,?,?,?)",
                           (close_id,now,self._day(now),entry["token"],"sell",proceeds,"reconciled",self._hash(payload),json.dumps(payload,allow_nan=False)))
                db.execute("DELETE FROM shadow_positions WHERE token=?",(entry["token"],))
                db.execute("UPDATE shadow_intents SET status='reconciled',payload=? WHERE id=?",(json.dumps({**entry,"status":"reconciled","closed_at":now,"close_id":close_id},allow_nan=False),intent_id))
                self._event(db,"position_closed",close_id,payload)
                return payload
        finally: db.close()

    def reconcile(self, balances, prices):
        db=self._db()
        findings=[]
        try:
            db.execute("BEGIN IMMEDIATE")
            rows=db.execute("SELECT token,units,cost_usdc,entry_price,opened,intent_id FROM shadow_positions").fetchall()
            seen=set()
            for token,units,cost,entry,opened,iid in rows:
                seen.add(token)
                actual=balances.get(token)
                if actual is None:
                    findings.append({"token":token,"kind":"missing_balance","intent_id":iid})
                    continue
                if float(actual)<0: findings.append({"token":token,"kind":"invalid_balance","intent_id":iid})
                price=prices.get(token)
                if price and math.isfinite(float(price)):
                    mark=float(actual)*float(price)
                    self._event(db,"mark",iid,{"token":token,"units":float(actual),"mark_usdc":mark,"unrealized_pnl":mark-float(cost)})
            for token,actual in balances.items():
                if token not in seen and float(actual)>0:
                    findings.append({"token":token,"kind":"unexpected_balance","units":float(actual)})
            self._event(db,"reconciliation",None,{"findings":findings,"balances":balances})
            db.commit()
            return {"ok":not findings,"findings":findings,"checked_positions":len(rows)}
        finally: db.close()
