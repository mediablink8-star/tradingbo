"""Durable public Pump.fun discovery events via third-party PumpPortal."""
import json, math, shutil, sqlite3, subprocess, threading, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE58=set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')

def normalize(payload,received=None):
    if not isinstance(payload,dict):raise ValueError('Expected an object')
    mint=payload.get('mint')
    if not isinstance(mint,str) or not 32<=len(mint)<=44 or not set(mint)<=BASE58:raise ValueError('Invalid mint')
    tx=payload.get('txType')
    kind='creation' if tx=='create' else 'migration' if tx in ('migration','migrate') else 'discovery'
    def number(key):
        value=payload.get(key)
        if value is None:return None
        if isinstance(value,bool):return None
        try:value=float(value)
        except (ValueError,TypeError):return None
        return value if math.isfinite(value) and value>=0 else None
    return {'mint':mint,'kind':kind,'symbol':str(payload.get('symbol',''))[:80],
        'name':str(payload.get('name',''))[:160],'market_cap_sol':number('marketCapSol'),
        'virtual_sol_reserve':number('vSolInBondingCurve'),'virtual_token_reserve':number('vTokensInBondingCurve'),
        'signature':str(payload.get('signature',''))[:160],
        'received_at':time.time() if received is None else received,
        'source':'PumpPortal (third-party Pump.fun discovery)','source_timestamp':None,
        'synthetic':False,'tradable':False}

class PumpStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS pump_events(id INTEGER PRIMARY KEY, received REAL, identity TEXT UNIQUE, normalized TEXT, raw TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS pump_status(id INTEGER PRIMARY KEY, received REAL, status TEXT, message TEXT)');self.db.commit()
    def event(self,payload):
        event=normalize(payload)
        identity=event['kind']+':'+(event['signature'] or event['mint'])+':'+event['mint']
        cur=self.db.execute('INSERT OR IGNORE INTO pump_events(received,identity,normalized,raw) VALUES(?,?,?,?)',
            (event['received_at'],identity,json.dumps(event),json.dumps(payload,allow_nan=False)))
        self.db.commit();return cur.rowcount==1
    def status(self,status,message):
        self.db.execute('INSERT INTO pump_status(received,status,message) VALUES(?,?,?)',(time.time(),status,message));self.db.commit()
    def recent(self,limit=100):
        events=[]
        for row in self.db.execute('SELECT id,normalized FROM pump_events ORDER BY id DESC LIMIT ?',(limit,)):
            event=json.loads(row[1]);event['id']=row[0];events.append(event)
        return events
    def count(self):return self.db.execute('SELECT COUNT(*) FROM pump_events').fetchone()[0]
    def export(self,limit=1000):
        return [dict(id=r[0],received_at=r[1],normalized=json.loads(r[2]),raw=json.loads(r[3])) for r in self.db.execute('SELECT id,received,normalized,raw FROM pump_events ORDER BY id DESC LIMIT ?',(limit,))]

class PumpFeed:
    def __init__(self,path):
        self.path=path;self.lock=threading.Lock();self.process=None;self.status='stopped';self.message='Feed not started.';self.heartbeat=None;self.last_event=None;self.worker=None
        store=PumpStore(path);store.db.close()
    def start(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:return self.snapshot_state()
            bundled=Path('C:/Users/30699/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
            node=shutil.which('node') or (str(bundled) if bundled.exists() else None)
            if not node:raise ValueError('Install Node.js 22+ to use the live feed. Offline experiments still work.')
            self.status='connecting';self.message='Starting public discovery collector.';self.heartbeat=time.time()
            self.process=subprocess.Popen([node,str(ROOT/'pump-stream.mjs')],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process=self.process;self.worker=threading.Thread(target=self.collect,args=(process,),daemon=True);self.worker.start()
            return self.snapshot_state()
    def snapshot_state(self):return {'status':self.status,'message':self.message,'last_event':self.last_event,'heartbeat':self.heartbeat,'running':self.process is not None and self.process.poll() is None}
    def snapshot(self):
        with self.lock:state=self.snapshot_state()
        store=PumpStore(self.path)
        try:state['events']=store.recent();state['total_events']=store.count()
        finally:store.db.close()
        state['stale']=state['heartbeat'] is None or time.time()-state['heartbeat']>30
        state['source']='PumpPortal · third-party Pump.fun feed';state['streams']=['new token creation','migration'];return state
    def collect(self,process):
        store=PumpStore(self.path)
        try:
            for line in process.stdout:
                if len(line)>1000100:continue
                try:
                    record=json.loads(line)
                    with self.lock:
                        if self.process is not process:break
                        self.heartbeat=time.time()
                        if record['type']=='status':self.status=record['status'];self.message=record['message'];store.status(self.status,self.message)
                        elif record['type']=='event':
                            payload=record['payload']
                            if isinstance(payload,dict) and 'mint' in payload:
                                if store.event(payload):
                                    self.last_event=time.time();self.status='connected';self.message='Receiving public Pump.fun discovery events.'
                            else:
                                message=str(payload.get('message',payload.get('error','Provider control message')))[:500] if isinstance(payload,dict) else 'Provider control message'
                                store.status('provider_message',message)
                                self.message=message
                                if 'error' in payload:self.status='error';self.message=message
                except (ValueError,TypeError,KeyError):store.status('invalid_event','Malformed provider event rejected.')
        except Exception:
            store.status('error','Collector failed; observations may have a gap.')
        finally:
            store.db.close()
            with self.lock:
                if self.process is process and self.status!='stopped':self.status='error';self.message='Collector ended; start the feed again.'
    def stop(self):
        with self.lock:
            process=self.process
            if process is not None and process.poll() is None:process.terminate()
            self.status='stopped';self.message='Collector stopped. Saved observations retained.'
        # Wait outside lock so the reader can finish before restarting a connection.
        if process is not None:
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        store=PumpStore(self.path);store.status('stopped',self.message);store.db.close()
        return self.snapshot()
