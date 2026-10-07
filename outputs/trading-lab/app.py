import json, argparse, os, time, threading, uuid, atexit, hmac
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from engine import Settings, Store, run_demo, LiveObserver
from agents import AgentTeam, run_team
from pump_feed import PumpFeed, PumpStore
from live_trial import LiveTrial
import connections
import swaps
import token_risk
from live_control import LiveControl
from shadow_execution import ShadowLedger
from autonomous_execution import AutonomousExecutor
from operations import Operations,journal
from virtual_company import Company
from company_os import CompanyOS, CompanyScheduler
from research_lab import Research
from urllib.parse import urlparse,parse_qs

ROOT=Path(__file__).resolve().parent
JOBS={};LOCK=threading.Lock()
PUMP=PumpFeed(ROOT/'lab.sqlite')
atexit.register(PUMP.stop)
LIVE=LiveTrial(ROOT/'lab.sqlite',PUMP)
SWAPS=swaps.Swaps(ROOT/'lab.sqlite')
LIVE_GUARD=LiveControl(ROOT/'lab.sqlite')
SHADOW=ShadowLedger(ROOT/'lab.sqlite')
AUTONOMOUS=AutonomousExecutor(ROOT/'lab.sqlite')
OPS=Operations(ROOT/'lab.sqlite')
COMPANY=Company(ROOT/'lab.sqlite')
COMPANY_OS=CompanyOS(ROOT/'lab.sqlite')
COMPANY_SCHEDULER=CompanyScheduler(COMPANY_OS, interval=60)
atexit.register(COMPANY_OS.close)
RESEARCH=Research(ROOT/'lab.sqlite')

def start_team(data):
    settings=Settings(**data.get('settings',{})).validate();partition=data.get('partition','development')
    if partition not in ('development','evaluation'):raise ValueError('Unknown partition')
    identifier=uuid.uuid4().hex
    def update(record):
        with LOCK:JOBS[identifier]['events'].append(record)
        store=Store(ROOT/'lab.sqlite')
        try:store.capture('agent_message',{'job_id':identifier,**record})
        finally:store.db.close()
    team=AgentTeam(data.get('provider','scripted'),data.get('model',''),data.get('max_rounds',3),data.get('cost_per_call',0),update)
    with LOCK:
        if any(j['status']=='running' for j in JOBS.values()):raise ValueError('A team is already running; stop it or wait for completion')
        if len(JOBS)>=20:
            oldest=next(iter(JOBS));del JOBS[oldest]
        JOBS[identifier]={'status':'running','events':[],'team':team,'result':None}
    def worker():
        try:
            result=run_team(settings,partition,team);store=Store(ROOT/'lab.sqlite')
            try:result['run_id']=store.save(partition,settings,result)
            finally:store.db.close()
            with LOCK:JOBS[identifier]['result']=result;JOBS[identifier]['status']='completed'
        except Exception:
            with LOCK:JOBS[identifier]['status']='failed';JOBS[identifier]['error']='Experiment failed; inspect saved agent messages. No real trades occurred.'
    threading.Thread(target=worker,daemon=True).start();return identifier

class Handler(BaseHTTPRequestHandler):
    def send(self,data,status=200):
        content=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content)
    def local_host(self):
        if self.headers.get('Host') not in ('127.0.0.1:8765','localhost:8765'):
            self.send({'error':'host rejected'},403);return False
        return True
    def do_GET(self):
        if not self.local_host():return
        if self.path=='/api/research':self.send(RESEARCH.snapshot());return
        if self.path=='/api/briefing':
            state=LIVE.snapshot();operations=OPS.update(state,PUMP.snapshot());self.send(RESEARCH.briefing(state,operations,COMPANY.board(state,operations)));return
        if self.path=='/api/evidence':
            state=LIVE.snapshot();self.send({'screening':state.get('screening',[]),'rows':state.get('market_rows',[]),'holders':state.get('holder_changes',{})});return
        if self.path=='/api/company':
            state=LIVE.snapshot();operations=OPS.update(state,PUMP.snapshot())
            board=COMPANY.board(state,operations)
            board['company_os']=COMPANY_OS.company_snapshot()
            self.send(board);return
        if self.path=='/api/company/os':
            self.send({**COMPANY_OS.company_snapshot(), "ceo_priority": COMPANY_OS.ceo_prioritize(), "scheduler": {"interval": COMPANY_SCHEDULER.interval, "last_run": COMPANY_SCHEDULER.last_run, "failures": COMPANY_SCHEDULER.failures}});return
        if self.path=='/api/operations':self.send(OPS.update(LIVE.snapshot(),PUMP.snapshot()));return
        if self.path.startswith('/api/journal'):
            try:
                q=parse_qs(urlparse(self.path).query);self.send(journal(ROOT/'lab.sqlite',q.get('category',['decisions'])[0],int(q.get('before',['0'])[0]),q.get('token',[''])[0]))
            except (ValueError,TypeError):self.send({'error':'Invalid journal filter'},400)
            return
        if self.path=='/api/swaps':self.send(SWAPS.state());return
        if self.path=='/api/connections':self.send(connections.status());return
        if self.path=='/api/live':self.send(LIVE.snapshot());return
        if self.path=='/api/live-trading':self.send(LIVE_GUARD.status());return
        if self.path=='/api/shadow':self.send(SHADOW.status());return
        if self.path=='/api/autonomous':self.send(AUTONOMOUS.status());return
        if self.path=='/api/pump':self.send(PUMP.snapshot());return
        if self.path=='/api/pump/export':
            store=PumpStore(ROOT/'lab.sqlite')
            try:self.send({'source':'PumpPortal','synthetic':False,'scope':'Latest 1000 recorded events; complete history retained in SQLite','events':store.export()})
            finally:store.db.close()
            return
        if self.path=='/api/agents':
            self.send({'openai_configured':bool(connections.api_key()),'local_endpoint':'http://127.0.0.1:11434','execution':'paper_only'});return
        if self.path.startswith('/api/team/'):
            with LOCK:
                job=JOBS.get(self.path.rsplit('/',1)[1]);payload={k:v for k,v in job.items() if k!='team'} if job else {'error':'Unknown job'}
            self.send(payload,200 if job else 404);return
        if self.path.startswith('/api/run/'):
            store=Store(ROOT/'lab.sqlite')
            try:self.send(store.load(int(self.path.rsplit('/',1)[1])))
            except ValueError as exc:self.send({'error':str(exc)},404)
            finally:store.db.close()
            return
        if self.path=='/api/history':
            store=Store(ROOT/'lab.sqlite');self.send(store.history());store.db.close();return
        if self.path in ('/product.css','/product.js','/operations.js','/virtual-company.js','/performance.js'):
            name=self.path[1:];content=(ROOT/name).read_bytes()
            self.send_response(200);self.send_header('Content-Type','text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content);return
        if self.path!='/':self.send({'error':'not found'},404);return
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write((ROOT/'index.html').read_bytes())
    def autonomous_auth(self):
        expected=os.environ.get('AUTONOMOUS_API_TOKEN','')
        auth=self.headers.get('Authorization','')
        if not expected or not auth.startswith('Bearer '):
            self.send({'error':'autonomous API authentication is not configured'},503);return False
        supplied=auth[7:]
        if not hmac.compare_digest(supplied,expected):
            self.send({'error':'autonomous API authentication failed'},401);return False
        return True
    def do_POST(self):
        if not self.local_host():return
        if self.path in ('/api/autonomous/buy','/api/autonomous/sell') and not self.autonomous_auth():return
        if self.headers.get('Origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):
            self.send({'error':'origin rejected'},403);return
        if self.path.startswith('/api/research/') or self.path in ('/api/company/config','/api/company/os/cycle') or self.path=='/api/operations/ack' or self.path.startswith('/api/connections/') or self.path=='/api/wallet/balance' or self.path.startswith('/api/swaps/') or self.path=='/api/token-risk' or self.path in ('/api/autonomous/buy','/api/autonomous/sell'):
            if self.headers.get('Origin') not in ('http://127.0.0.1:8765','http://localhost:8765'):
                self.send({'error':'local browser origin required'},403);return
        if self.headers.get('Content-Type')!='application/json':self.send({'error':'JSON required'},400);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>20000:raise ValueError('Request size must be 1–20000 bytes')
            data=json.loads(self.rfile.read(size));store=Store(ROOT/'lab.sqlite')
            try:
                if self.path=='/api/research/review':self.send(RESEARCH.propose())
                elif self.path=='/api/research/finish':self.send(RESEARCH.finish(data.get('id')))
                elif self.path=='/api/research/test':self.send(RESEARCH.test_proposal(data.get('id')))
                elif self.path=='/api/swaps/recover':self.send(SWAPS.recover(data.get('id')))
                elif self.path=='/api/company/config':self.send(COMPANY.configure(data))
                elif self.path=='/api/company/os/cycle':
                    state=LIVE.snapshot();operations=OPS.update(state,PUMP.snapshot())
                    result=COMPANY_OS.cycle_from_state(state,operations,force=True)
                    result["ceo_priority"]=COMPANY_OS.ceo_prioritize({
                        "data_quality_bad": result["signals"].get("data_quality_alert",False),
                        "open_audits": result["signals"].get("unresolved_audit_findings",False),
                        "evaluation_due": result["signals"].get("loss_review_due",False),
                        "research_capacity": bool(COMPANY_OS.budget.research_slots)})
                    result["ceo_resource_plan"]=COMPANY_OS.ceo_resource_plan({
                        "research_capacity": bool(COMPANY_OS.budget.research_slots)})
                    self.send(result)
                elif self.path=='/api/operations/ack':self.send(OPS.acknowledge(data.get('id')))
                elif self.path=='/api/token-risk':self.send(token_risk.scan(data.get('mint'),ROOT/'lab.sqlite'))
                elif self.path=='/api/swaps/connect':self.send(swaps.connect(data))
                elif self.path=='/api/swaps/prepare':self.send(SWAPS.prepare(data))
                elif self.path=='/api/swaps/ready':self.send(SWAPS.ready(data.get('id'),data.get('wallet')))
                elif self.path=='/api/swaps/confirm':self.send(SWAPS.confirm(data.get('id'),data.get('signature')))
                elif self.path=='/api/swaps/halt':self.send(SWAPS.halt())
                elif self.path=='/api/connections/model':self.send(connections.configure(data))
                elif self.path=='/api/connections/verify':self.send(connections.verify())
                elif self.path=='/api/connections/forget':self.send(connections.forget())
                elif self.path=='/api/wallet/balance':self.send(connections.wallet_balance(data.get('address')))
                elif self.path=='/api/live/start':self.send(LIVE.start(data))
                elif self.path=='/api/live/stop':self.send(LIVE.stop())
                elif self.path=='/api/shadow/reconcile':self.send(SHADOW.reconcile(data.get('balances',{}),data.get('prices',{})))
                elif self.path=='/api/autonomous/buy':self.send(AUTONOMOUS.execute_buy(wallet=data.get('wallet'),mint=data.get('mint'),usd=data.get('usd',10)))
                elif self.path=='/api/autonomous/sell':self.send(AUTONOMOUS.execute_sell(wallet=data.get('wallet'),mint=data.get('mint'),amount=data.get('amount')))
                elif self.path=='/api/live-trading/arm':self.send(LIVE_GUARD.arm())
                elif self.path=='/api/live-trading/disarm':self.send(LIVE_GUARD.disarm())
                elif self.path=='/api/live-trading/kill':self.send(LIVE_GUARD.kill(data.get('reason','manual kill switch')))
                elif self.path=='/api/live-trading/reset-kill':self.send(LIVE_GUARD.reset_kill())
                elif self.path=='/api/pump/start':self.send(PUMP.start())
                elif self.path=='/api/pump/stop':self.send(PUMP.stop())
                elif self.path=='/api/team/start':self.send({'job_id':start_team(data)},202)
                elif self.path=='/api/team/stop':
                    with LOCK:
                        job=JOBS.get(data.get('job_id'))
                        if not job:raise ValueError('Unknown job')
                        job['team'].cancelled=True
                    self.send({'status':'stopping','message':'Pending model call may finish. New entries stop; paper exits continue under risk controls.'})
                elif self.path=='/api/run':
                    result=run_demo(Settings(**data.get('settings',{})),data.get('partition','development'))
                    result['run_id']=store.save(result['partition'],Settings(**result['settings']),result);self.send(result)
                elif self.path=='/api/observe':
                    try:result=LiveObserver().observe(data['mint'])
                    except Exception as exc:
                        store.capture('dexscreener_failure',{'received':time.time(),'mint':data.get('mint'),'error':str(exc)})
                        raise
                    store.capture('dexscreener',result);self.send(result)
                else:self.send({'error':'not found'},404)
            finally:store.db.close()
        except Exception as exc:self.send({'error':str(exc)},400)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--quote');args=parser.parse_args()
    if args.quote:
        key=os.environ.get('JUPITER_API_KEY')
        if not key:parser.error('Set JUPITER_API_KEY for read-only quotes; no wallet secrets')
        observer=LiveObserver();observer.observe(args.quote)
        result=observer.quote(args.quote,10000000,key);store=Store(ROOT/'lab.sqlite');store.capture('jupiter_quote',result);print(json.dumps(result,indent=2))
    else:
        print('AI paper team + wallet-approved swap pilot: http://127.0.0.1:8765 (Ctrl+C to stop)',flush=True)
        LIVE.resume()
        def monitor():
            while True:
                try:
                    state=LIVE.snapshot();operations=OPS.update(state,PUMP.snapshot());COMPANY.board(state,operations);COMPANY_SCHEDULER.tick(state,operations)
                except Exception:pass
                time.sleep(10)
        threading.Thread(target=monitor,daemon=True).start()
        ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()

