"""Persistent operator gate for real-money wallet-approved execution.

This module never signs or broadcasts transactions. It only controls whether the
existing Phantom/Jupiter handoff may be prepared. AI agents cannot bypass it.
"""
import os, sqlite3, time

MAX_TRADE_USDC=10.0
MAX_DAILY_INTENT_USDC=25.0

class LiveControl:
    def __init__(self,path):
        self.path=path
        db=self.db();db.close()
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute("""CREATE TABLE IF NOT EXISTS live_control(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL,halted INTEGER NOT NULL,day TEXT NOT NULL,day_intents REAL NOT NULL,last_error TEXT,updated REAL NOT NULL)""")
        if db.execute("SELECT 1 FROM live_control WHERE id=1").fetchone() is None:
            db.execute("INSERT INTO live_control VALUES(1,0,0,?,0,NULL,?)",(time.strftime("%Y-%m-%d",time.gmtime()),time.time()));db.commit()
        return db
    def _state(self,db):
        row=db.execute("SELECT enabled,halted,day,day_intents,last_error,updated FROM live_control WHERE id=1").fetchone()
        day=time.strftime("%Y-%m-%d",time.gmtime())
        if row[2]!=day:
            db.execute("UPDATE live_control SET day=?,day_intents=0,updated=? WHERE id=1",(day,time.time()));db.commit();row=(row[0],row[1],day,0,row[4],time.time())
        return dict(enabled=bool(row[0]),halted=bool(row[1]),day=row[2],day_intents=row[3],last_error=row[4],updated=row[5])
    def status(self):
        db=self.db()
        try:
            s=self._state(db);s.update(environment_enabled=os.environ.get("LIVE_TRADING_ENABLE")=="1",
                max_trade_usdc=MAX_TRADE_USDC,max_daily_intent_usdc=MAX_DAILY_INTENT_USDC,
                execution="wallet_approved_only",autonomous_signing=False)
            return s
        finally:db.close()
    def arm(self):
        if os.environ.get("LIVE_TRADING_ENABLE")!="1":raise ValueError("Live trading is disabled. Set LIVE_TRADING_ENABLE=1 deliberately.")
        db=self.db()
        try:
            with db:
                s=self._state(db)
                if s["halted"]:raise ValueError("Live kill switch is latched.")
                db.execute("UPDATE live_control SET enabled=1,last_error=NULL,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally:db.close()
    def disarm(self):
        db=self.db()
        try:
            with db:db.execute("UPDATE live_control SET enabled=0,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally:db.close()
    def kill(self,reason="manual kill switch"):
        db=self.db()
        try:
            with db:db.execute("UPDATE live_control SET enabled=0,halted=1,last_error=?,updated=? WHERE id=1",(str(reason)[:500],time.time()))
            return self.status()
        finally:db.close()
    def reset_kill(self):
        if os.environ.get("LIVE_TRADING_RESET_KILL")!="1":raise ValueError("Set LIVE_TRADING_RESET_KILL=1 for an explicit operator reset.")
        db=self.db()
        try:
            with db:db.execute("UPDATE live_control SET halted=0,last_error=NULL,updated=? WHERE id=1",(time.time(),))
            return self.status()
        finally:db.close()
    def reserve_intent(self,usd):
        if isinstance(usd,bool) or not isinstance(usd,(int,float)) or not 0<usd<=MAX_TRADE_USDC:raise ValueError("Live intent exceeds the hard $10 limit.")
        db=self.db()
        try:
            with db:
                s=self._state(db)
                if not s["enabled"] or s["halted"]:raise ValueError("Live wallet handoff is not armed.")
                if s["day_intents"]+usd>MAX_DAILY_INTENT_USDC:raise ValueError("Daily live intent budget exhausted.")
                db.execute("UPDATE live_control SET day_intents=day_intents+?,updated=? WHERE id=1",(usd,time.time()))
        finally:db.close()
