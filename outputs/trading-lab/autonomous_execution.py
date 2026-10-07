"""Guarded autonomous Jupiter execution.

Agents can request execution, but they cannot access signing credentials. The
external signer is an independent authority and the transaction is revalidated
before broadcast.
"""
import base64, hashlib, json, os, sqlite3, time
import swaps
from autonomous_signer import SignerClient
from live_control import LiveControl

MAX_OPEN_POSITIONS=3
MAX_EXPOSURE_USDC=25.0

class AutonomousExecutor:
    def __init__(self,path,signer=None):
        self.path=path; self.signer=signer or SignerClient(); self.guard=LiveControl(path); self._db().close()
    def _db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute("CREATE TABLE IF NOT EXISTS autonomous_execution(id TEXT PRIMARY KEY,created REAL NOT NULL,state TEXT NOT NULL,intent TEXT NOT NULL,payload TEXT NOT NULL)")
        db.commit(); return db
    def status(self):
        return {"mode":"autonomous_external_signer","enabled":os.environ.get("AUTONOMOUS_LIVE_ENABLE")=="1","signer_configured":self.signer.configured(),"live_control":self.guard.status(),"private_key_in_process":False}
    def _record(self,identifier,state,payload):
        db=self._db()
        try:
            with db: db.execute("INSERT OR REPLACE INTO autonomous_execution VALUES(?,?,?,?,?)",(identifier,time.time(),state,json.dumps(payload.get("intent",{}),allow_nan=False),json.dumps(payload,allow_nan=False)))
        finally: db.close()
    def _open_buy_exposure(self, wallet):
        db=self._db()
        try:
            rows=db.execute("SELECT payload FROM autonomous_execution WHERE state='confirmed'").fetchall()
        finally:
            db.close()
        total=0.0; count=0
        for (raw,) in rows:
            try:
                payload=json.loads(raw); intent=payload.get("intent",{})
                if intent.get("wallet")==wallet and intent.get("side")=="buy":
                    total+=float(intent.get("reserved_usdc",0)); count+=1
            except (TypeError,ValueError,json.JSONDecodeError):
                raise ValueError("Autonomous ledger contains an unreadable confirmed intent; execution is halted for safety.")
        return count,total

    def execute_buy(self, *, wallet, mint, usd=10):
        if os.environ.get("AUTONOMOUS_LIVE_ENABLE")!="1": raise ValueError("Autonomous live execution is disabled.")
        if not self.signer.configured(): raise ValueError("External signer is not configured.")
        expected_wallet=os.environ.get("AUTONOMOUS_WALLET","")
        if not expected_wallet: raise ValueError("AUTONOMOUS_WALLET is not configured; autonomous execution is fail-closed.")
        if wallet!=expected_wallet: raise ValueError("Requested wallet is not the configured autonomous trading wallet.")
        if not isinstance(mint,str) or not mint: raise ValueError("Token mint is required.")
        if isinstance(usd,bool) or not isinstance(usd,(int,float)) or not 0<usd<=10: raise ValueError("Autonomous buy must be between 0 and 10 USDC-equivalent.")
        open_count,exposure=self._open_buy_exposure(wallet)
        if open_count>=MAX_OPEN_POSITIONS: raise ValueError("Autonomous position limit reached.")
        if exposure+float(usd)>MAX_EXPOSURE_USDC: raise ValueError("Autonomous exposure limit reached.")
        record=swaps.Swaps(self.path).prepare({"wallet":wallet,"mint":mint,"side":"buy","usd":usd})
        intent=record["id"]; self.guard.reserve_intent(float(record["reserved_usdc"])); swaps.Swaps(self.path).ready(intent,wallet); self._record(intent,"prepared",{"intent":record})
        try:
            signed=self.signer.sign(wallet=wallet,transaction_b64=record["transaction"],intent_id=intent,message_hash=record["message_hash"])
            raw=base64.b64decode(signed,validate=True)
            signed_message=swaps.message(signed,wallet,unsigned=False)
            if hashlib.sha256(signed_message).hexdigest()!=record["message_hash"]: raise ValueError("Signer returned a transaction with a different message.")
            payload={"signedTransaction":signed}
            if record.get("requestId"): payload["requestId"]=record["requestId"]
            result=swaps.request("https://api.jup.ag/swap/v1/execute",payload,{"x-api-key":swaps.credential()})
            signature=result.get("signature")
            if not isinstance(signature,str) or not signature: raise ValueError("Jupiter did not return a transaction signature.")
            self._record(intent,"broadcast",{"intent":record,"signature":signature,"jupiter":result})
            confirmed=swaps.Swaps(self.path).confirm(intent,signature)
            return {"ok":confirmed.get("state")=="confirmed","intent":intent,"signature":signature,"state":confirmed.get("state"),"reconciliation":confirmed.get("reconciliation")}
        except Exception as exc:
            self._record(intent,"failed",{"intent":record,"error":str(exc)[:500]}); raise
