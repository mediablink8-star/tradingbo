"""Controlled live Solana execution boundary.

The AI never receives a signer or execution tool. Live execution is opt-in, fail-closed,
and uses a dedicated keypair loaded only from LIVE_TRADING_KEYPAIR. Never commit that secret.
"""
import base64, json, os, re, sqlite3, time, threading
import swaps

MAX_TRADE_USDC = 10.0
MAX_DAILY_BUYS_USDC = 25.0
MAX_OPEN_POSITIONS = 1
DAILY_LOSS_LIMIT_USDC = 10.0

def _b58decode(value):
    alphabet=swaps._ALPHABET
    n=0
    for c in value:
        if c not in alphabet: raise ValueError("Invalid base58 value")
        n=n*58+alphabet.index(c)
    raw=n.to_bytes((n.bit_length()+7)//8,"big") if n else b""
    return b"\0"*(len(value)-len(value.lstrip("1")))+raw

def _keypair():
    raw=os.environ.get("LIVE_TRADING_KEYPAIR","")
    if not raw: raise ValueError("LIVE_TRADING_KEYPAIR is not configured.")
    try: values=json.loads(raw)
    except Exception: raise ValueError("LIVE_TRADING_KEYPAIR must be a Solana JSON keypair array.") from None
    if not isinstance(values,list) or len(values) not in (32,64) or any(type(x)!=int or not 0<=x<=255 for x in values):
        raise ValueError("LIVE_TRADING_KEYPAIR must contain 32 or 64 byte values.")
    try:
        from nacl.signing import SigningKey
    except ImportError: raise ValueError("PyNaCl is required for live signing. Install requirements.txt; paper mode remains available.") from None
    key=SigningKey(bytes(values[:32]));wallet=swaps.encode58(bytes(key.verify_key))
    if len(values)==64 and bytes(values[32:])!=bytes(key.verify_key): raise ValueError("Keypair public key does not match its seed.")
    return key,wallet

def _compact(n):
    out=bytearray()
    while True:
        b=n&127;n>>=7;out.append(b|(128 if n else 0))
        if not n:return bytes(out)

class LiveGuard:
    def __init__(self,path): self.path=path;self.lock=threading.Lock();self.db().close()
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute("""CREATE TABLE IF NOT EXISTS live_guard(id INTEGER PRIMARY KEY CHECK(id=1), armed INTEGER NOT NULL, halted INTEGER NOT NULL, day TEXT NOT NULL, day_buys REAL NOT NULL, day_pnl REAL NOT NULL, last_error TEXT, updated REAL NOT NULL)""")
        if db.execute("SELECT 1 FROM live_guard WHERE id=1").fetchone() is None:
            day=time.strftime("%Y-%m-%d",time.gmtime());db.execute("INSERT INTO live_guard VALUES(1,0,0,?,0,0,NULL,?)",(day,time.time()));db.commit()
        return db
    def _row(self,db):
        row=db.execute("SELECT armed,halted,day,day_buys,day_pnl,last_error,updated FROM live_guard WHERE id=1").fetchone()
        day=time.strftime("%Y-%m-%d",time.gmtime())
        if row[2]!=day:
            db.execute("UPDATE live_guard SET day=?,day_buys=0,day_pnl=0,updated=? WHERE id=1",(day,time.time()));db.commit();row=(row[0],row[1],day,0,0,row[5],time.time())
        return dict(armed=bool(row[0]),halted=bool(row[1]),day=row[2],day_buys=row[3],day_pnl=row[4],last_error=row[5],updated=row[6])
    def status(self):
        db=self.db()
        try:
            s=self._row(db)
            try: _,wallet=_keypair()
            except Exception: wallet=None
            s.update(wallet=wallet,signer_configured=wallet is not None,environment_enabled=os.environ.get("LIVE_TRADING_ENABLE")=="1",limits=dict(max_trade_usdc=MAX_TRADE_USDC,max_daily_buys_usdc=MAX_DAILY_BUYS_USDC,max_open_positions=MAX_OPEN_POSITIONS,daily_loss_limit_usdc=DAILY_LOSS_LIMIT_USDC))
            return s
        finally: db.close()
    def arm(self):
        if os.environ.get("LIVE_TRADING_ENABLE")!="1": raise ValueError("Live trading is disabled by environment. Set LIVE_TRADING_ENABLE=1 deliberately.")
        _,wallet=_keypair();db=self.db()
        try:
            with db:
                s=self._row(db)
                if s["halted"]: raise ValueError("Live kill switch is latched. Reset it explicitly before arming.")
                db.execute("UPDATE live_guard SET armed=1,last_error=NULL,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally: db.close()
    def disarm(self):
        db=self.db()
        try:
            with db: db.execute("UPDATE live_guard SET armed=0,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally: db.close()
    def kill(self,reason="manual kill switch"):
        db=self.db()
        try:
            with db: db.execute("UPDATE live_guard SET armed=0,halted=1,last_error=?,updated=? WHERE id=1",(reason[:500],time.time()))
            return self.status()
        finally: db.close()
    def reset_kill(self):
        if os.environ.get("LIVE_TRADING_RESET_KILL")!="1": raise ValueError("Kill reset is disabled. Set LIVE_TRADING_RESET_KILL=1 for an explicit operator reset.")
        db=self.db()
        try:
            with db: db.execute("UPDATE live_guard SET halted=0,last_error=NULL,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally: db.close()
    def debit_buy(self,usd):
        db=self.db()
        try:
            with db:
                s=self._row(db)
                if not s["armed"] or s["halted"]: raise ValueError("Live execution is not armed.")
                if usd>MAX_TRADE_USDC: raise ValueError("Live trade exceeds the hard per-trade limit.")
                if s["day_buys"]+usd>MAX_DAILY_BUYS_USDC: raise ValueError("Daily live-buy budget exhausted.")
                db.execute("UPDATE live_guard SET day_buys=day_buys+?,updated=? WHERE id=1",(usd,time.time()))
        finally: db.close()
    def record_error(self,message):
        db=self.db()
        try:
            with db: db.execute("UPDATE live_guard SET last_error=?,updated=? WHERE id=1",(message[:500],time.time()))
        finally: db.close()

class ControlledLiveExecution:
    mode="controlled_live"
    def __init__(self,path): self.path=path;self.guard=LiveGuard(path);self.swaps=swaps.Swaps(path);self.last_fill={}
    def _signed(self,record):
        key,wallet=_keypair()
        if wallet!=record["wallet"]: raise ValueError("Signer wallet does not match the prepared wallet.")
        message=_b58decode(record["message"])
        if len(message)<100 or len(message)>1232: raise ValueError("Prepared transaction message length is invalid.")
        signature=key.sign(message).signature;raw=_compact(1)+signature+message
        return base64.b64encode(raw).decode()
    def _send(self,record):
        signed=self._signed(record)
        result=swaps.rpc("sendTransaction",[signed,dict(encoding="base64",skipPreflight=False,preflightCommitment="confirmed",maxRetries=0)])
        signature=result.get("value")
        if not isinstance(signature,str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{64,88}",signature): raise ValueError("RPC did not return a valid transaction signature.")
        confirmed=self.swaps.confirm(record["id"],signature)
        if confirmed["state"]!="confirmed": raise ValueError("Live transaction was not confirmed successfully.")
        return confirmed
    def buy(self,row,s):
        self.guard.debit_buy(10.0)
        try:
            record=self.swaps.prepare(dict(wallet=_keypair()[1],mint=row["token"],side="buy",usd=10))
            self.swaps.ready(record["id"],record["wallet"]);confirmed=self._send(record)
            units=int(confirmed["reconciliation"]["realized_output"])/(10**record["token_decimals"])
            if units<=0: raise ValueError("Confirmed buy delivered no positive token balance.")
            price=10/units
            self.last_fill={"base_units":int(confirmed["reconciliation"]["realized_output"]),"decimals":record["token_decimals"],"signature":confirmed["signature"],"trade_quality":record.get("trade_quality")}
            return units,price
        except Exception as exc:
            self.guard.record_error(type(exc).__name__+": live buy failed");raise
    def sell_value(self,p,row,s):
        if p.get("fill_mode")!=self.mode: raise ValueError("Live execution refuses to close a non-live position.")
        raw=int(p.get("base_units",0))
        if raw<=0: raise ValueError("Live position has no token base-unit amount.")
        try:
            record=self.swaps.prepare(dict(wallet=_keypair()[1],mint=row["token"],side="sell",amount=str(raw)))
            self.swaps.ready(record["id"],record["wallet"]);confirmed=self._send(record)
            realized=int(confirmed["reconciliation"]["realized_output"])
            if realized<0: raise ValueError("Negative live sell output.")
            return realized/1_000_000
        except Exception as exc:
            self.guard.record_error(type(exc).__name__+": live sell failed");raise
