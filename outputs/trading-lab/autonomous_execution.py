"""Guarded autonomous Jupiter execution.

Agents can request execution, but they cannot access signing credentials. The
external signer is an independent authority and the transaction is revalidated
before broadcast.
"""
import hashlib, json, os, sqlite3, time
import swaps
from autonomous_signer import SignerClient
from live_control import LiveControl
from signing_policy import build as build_signing_policy

MAX_OPEN_POSITIONS=3
MAX_EXPOSURE_USDC=25.0

class AutonomousExecutor:
    def __init__(self,path,signer=None):
        self.path=path
        self.signer=signer or SignerClient()
        self.guard=LiveControl(path)
        self._db().close()

    def _db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute("CREATE TABLE IF NOT EXISTS autonomous_execution(id TEXT PRIMARY KEY,created REAL NOT NULL,state TEXT NOT NULL,intent TEXT NOT NULL,payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS autonomous_positions(wallet TEXT NOT NULL,mint TEXT NOT NULL,intent_id TEXT NOT NULL PRIMARY KEY,units TEXT NOT NULL,entry_usdc REAL NOT NULL,opened REAL NOT NULL)")
        db.commit()
        return db

    def status(self):
        db=self._db()
        try:
            positions=db.execute(
                "SELECT wallet,mint,intent_id,units,entry_usdc,opened FROM autonomous_positions ORDER BY opened DESC"
            ).fetchall()
        finally:
            db.close()
        return {
            "mode":"autonomous_external_signer",
            "enabled":os.environ.get("AUTONOMOUS_LIVE_ENABLE")=="1",
            "signer_configured":self.signer.configured(),
            "live_control":self.guard.status(),
            "private_key_in_process":False,
            "positions":[
                {"wallet":w,"mint":m,"intent_id":i,"units":u,"entry_usdc":e,"opened":o}
                for w,m,i,u,e,o in positions
            ],
        }

    def _record(self,identifier,state,payload):
        db=self._db()
        try:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO autonomous_execution VALUES(?,?,?,?,?)",
                    (identifier,time.time(),state,
                     json.dumps(payload.get("intent",{}),allow_nan=False),
                     json.dumps(payload,allow_nan=False)),
                )
        finally:
            db.close()

    def _open_buy_exposure(self,wallet):
        db=self._db()
        try:
            rows=db.execute(
                "SELECT units,entry_usdc FROM autonomous_positions WHERE wallet=?",
                (wallet,),
            ).fetchall()
        finally:
            db.close()
        total=0.0
        count=0
        for units,entry in rows:
            try:
                if float(units)>0:
                    total+=float(entry)
                    count+=1
            except (TypeError,ValueError):
                raise ValueError("Autonomous position ledger is unreadable; execution is halted for safety.")
        return count,total

    def _position(self,wallet,mint):
        db=self._db()
        try:
            row=db.execute(
                "SELECT wallet,mint,intent_id,units,entry_usdc,opened FROM autonomous_positions WHERE wallet=? AND mint=?",
                (wallet,mint),
            ).fetchone()
        finally:
            db.close()
        return row

    def _assert_live_gate(self):
        if os.environ.get("AUTONOMOUS_LIVE_ENABLE")!="1":
            raise ValueError("Autonomous live execution is disabled.")
        gate=self.guard.status()
        if not gate["enabled"] or gate["halted"]:
            raise ValueError("Autonomous execution requires the operator live gate to be armed and not halted.")
        if not self.signer.configured():
            raise ValueError("External signer is not configured.")

    def _execute_prepared(self,record):
        intent=record["id"]
        wallet=record["wallet"]
        swap=swaps.Swaps(self.path)
        policy, policy_hash = build_signing_policy(record)
        self.guard.reserve_intent(float(record["reserved_usdc"]))
        swap.ready(intent,wallet)
        self._record(intent,"prepared",{"intent":record})
        try:
            signed=self.signer.sign(
                wallet=wallet,
                transaction_b64=record["transaction"],
                intent_id=intent,
                message_hash=record["message_hash"],
                policy_hash=policy_hash,
            )
            signed_message=swaps.message(signed,wallet,unsigned=False)
            if hashlib.sha256(signed_message).hexdigest()!=record["message_hash"]:
                raise ValueError("Signer returned a transaction with a different message.")
            payload={"signedTransaction":signed}
            if record.get("requestId"):
                payload["requestId"]=record["requestId"]
            result=swaps.request(
                "https://api.jup.ag/swap/v2/execute",
                payload,
                {"x-api-key":swaps.credential()},
            )
            signature=result.get("signature")
            if not isinstance(signature,str) or not signature:
                raise ValueError("Jupiter did not return a transaction signature.")
            self._record(
                intent,"broadcast",
                {"intent":record,"signature":signature,"jupiter":result},
            )
            confirmed=swap.confirm(intent,signature)
            reconciliation=confirmed.get("reconciliation") or {}
            if confirmed.get("state")!="confirmed" or reconciliation.get("status")!="verified":
                self.guard.kill("Autonomous transaction reconciliation failed: "+str(reconciliation.get("status","unknown")))
                raise ValueError("Autonomous transaction was not fully reconciled; the live kill switch has been latched.")
            return confirmed
        except Exception as exc:
            self._record(intent,"failed",{"intent":record,"error":str(exc)[:500]})
            raise

    def execute_buy(self, *, wallet, mint, usd=10):
        self._assert_live_gate()
        expected_wallet=os.environ.get("AUTONOMOUS_WALLET","")
        if not expected_wallet:
            raise ValueError("AUTONOMOUS_WALLET is not configured; autonomous execution is fail-closed.")
        if wallet!=expected_wallet:
            raise ValueError("Requested wallet is not the configured autonomous trading wallet.")
        if not isinstance(mint,str) or not mint:
            raise ValueError("Token mint is required.")
        if isinstance(usd,bool) or not isinstance(usd,(int,float)) or not 0<usd<=10:
            raise ValueError("Autonomous buy must be between 0 and 10 USDC-equivalent.")
        if self._position(wallet,mint):
            raise ValueError("An autonomous position already exists for this token.")
        open_count,exposure=self._open_buy_exposure(wallet)
        if open_count>=MAX_OPEN_POSITIONS:
            raise ValueError("Autonomous position limit reached.")
        if exposure+float(usd)>MAX_EXPOSURE_USDC:
            raise ValueError("Autonomous exposure limit reached.")

        swap=swaps.Swaps(self.path)
        record=swap.prepare({"wallet":wallet,"mint":mint,"side":"buy","usd":usd})
        confirmed=self._execute_prepared(record)
        reconciliation=confirmed["reconciliation"]
        units=str(reconciliation["realized_output"])
        if not units.isdigit() or int(units)<=0:
            self.guard.kill("Autonomous buy reconciled without a positive token position.")
            raise ValueError("Autonomous buy did not produce a usable token position.")
        db=self._db()
        try:
            with db:
                db.execute(
                    "INSERT INTO autonomous_positions VALUES(?,?,?,?,?,?)",
                    (wallet,mint,record["id"],units,float(record["reserved_usdc"]),time.time()),
                )
        finally:
            db.close()
        return {
            "ok":True,
            "intent":record["id"],
            "signature":confirmed["signature"],
            "state":confirmed["state"],
            "reconciliation":reconciliation,
            "position":{"mint":mint,"units":units,"entry_usdc":float(record["reserved_usdc"])},
        }

    def execute_sell(self, *, wallet, mint, amount=None):
        self._assert_live_gate()
        expected_wallet=os.environ.get("AUTONOMOUS_WALLET","")
        if not expected_wallet or wallet!=expected_wallet:
            raise ValueError("Requested wallet is not the configured autonomous trading wallet.")
        position=self._position(wallet,mint)
        if not position:
            raise ValueError("No autonomous position exists for this wallet and token.")
        position_units=position[3]
        if amount is None:
            amount=position_units
        if not isinstance(amount,str) or not amount.isdigit() or not 0<int(amount)<=int(position_units):
            raise ValueError("Sell amount must be a positive token base-unit amount within the tracked position.")

        swap=swaps.Swaps(self.path)
        record=swap.prepare({"wallet":wallet,"mint":mint,"side":"sell","amount":amount})
        confirmed=self._execute_prepared(record)
        reconciliation=confirmed["reconciliation"]
        db=self._db()
        try:
            remaining=int(position_units)-int(amount)
            with db:
                if remaining==0:
                    db.execute("DELETE FROM autonomous_positions WHERE intent_id=?",(position[2],))
                else:
                    db.execute("UPDATE autonomous_positions SET units=? WHERE intent_id=?",(str(remaining),position[2]))
        finally:
            db.close()
        return {
            "ok":True,
            "intent":record["id"],
            "signature":confirmed["signature"],
            "state":confirmed["state"],
            "reconciliation":reconciliation,
            "position":{"mint":mint,"units":str(remaining)},
        }
