"""Guarded autonomous Jupiter execution.

Agents can request execution, but they cannot access signing credentials. The
external signer is an independent authority and the transaction is revalidated
before broadcast.
"""
import base64, hashlib, json, os, sqlite3, time
import swaps
from autonomous_signer import SignerClient
from live_control import LiveControl

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
    def execute_buy(self, *, wallet, mint, usd=10):
        if os.environ.get("AUTONOMOUS_LIVE_ENABLE")!="1": raise ValueError("Autonomous live execution is disabled.")
        if not self.signer.configured(): raise ValueError("External signer is not configured.")
        record=swaps.Swaps(self.path).prepare({"wallet":wallet,"mint":mint,"side":"buy","usd":usd})
        intent=record["id"]; self.guard.reserve_intent(float(record["reserved_usdc"])); swaps.Swaps(self.path).ready(intent,wallet); self._record(intent,"prepared",{"intent":record})
        try:
            signed=self.signer.sign(wallet=wallet,transaction_b64=record["transaction"],intent_id=intent,message_hash=record["message_hash"])
            raw=base64.b64decode(signed,validate=True)
            if hashlib.sha256(raw[65:]).hexdigest()!=record["message_hash"]: raise ValueError("Signer returned a transaction with a different message.")
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
