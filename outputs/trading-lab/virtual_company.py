"""Virtual-company responsibilities, work orders and bounded inference budget."""
import json,sqlite3,time,math
from contextlib import closing
from datetime import datetime,timezone
STAFF=[
('ceo','CEO','Leadership','Protect capital, set priorities and escalate blockers.','Rule-based supervisor'),
('research','Market researcher','Research','Monitor supplied market evidence and identify uncertainty.','AI review'),
('screening','Token screener','Security','Challenge eligibility and missing token evidence.','AI review'),
('strategy','Strategy analyst','Investment','Propose entries only when expected benefit covers costs.','AI review'),
('risk','Risk critic','Risk','Veto weak proposals; preserve hard risk limits.','AI review'),
('portfolio','Portfolio coordinator','Investment','Combine unanimous approvals within allocation limits.','AI review'),
('finance','CFO / Performance reviewer','Finance','Account for capital, inference costs and comparisons.','Deterministic accounting'),
('execution','Execution officer','Execution','Validate read-only quotes; real swaps require owner approval.','Fixed execution service'),
('operations','Operations officer','Operations','Watch worker health, stale data and incident recovery.','Fixed monitoring service'),
('audit','Audit officer','Governance','Retain reports, verdicts and outcomes; challenge unsupported claims.','Journal service')]
MISSION='Maximize net capital growth within fixed capital, loss and spending limits. Account for uncertainty, costs and failed exits. Abstain when evidence does not support an entry. Never loosen safeguards to meet a target.'
class Company:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path,timeout=15)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS live_log(id INTEGER PRIMARY KEY, received REAL, kind TEXT, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS company_config(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS company_tasks(id INTEGER PRIMARY KEY,task_key TEXT,title TEXT,owner TEXT,status TEXT,created REAL,updated REAL,note TEXT)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS active_company_task ON company_tasks(task_key) WHERE status!=\'done\'')
    def config(self):
        with closing(sqlite3.connect(self.path,timeout=15)) as db:r=db.execute('SELECT payload FROM company_config WHERE id=1').fetchone()
        return json.loads(r[0]) if r else {'name':'Ember Capital','priority':'balanced','daily_ai_budget':.5}
    def configure(self,data):
        c=self.config();name=data.get('name',c['name']);priority=data.get('priority',c['priority']);budget=data.get('daily_ai_budget',c['daily_ai_budget'])
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or priority not in ('preservation','balanced','research') or isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or not 0<=budget<=10:raise ValueError('Use a company name, valid priority and a 0–10 USD daily AI cap.')
        c={'name':name.strip(),'priority':priority,'daily_ai_budget':budget}
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:db.execute('INSERT OR REPLACE INTO company_config VALUES(1,?)',(json.dumps(c),))
        return c
    def budget(self,state,now=None):
        now=time.time() if now is None else now;day=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        with closing(sqlite3.connect(self.path,timeout=15)) as db:
            rows=db.execute("SELECT payload FROM live_log WHERE kind IN ('ai_usage_cost','ai_cost_unresolved') AND json_extract(payload,'$.timestamp')>=?",(day,)).fetchall()
        used=sum(float(e.get('amount',e.get('reserved',0))) for (raw,) in rows for e in [json.loads(raw)])
        pending=state.get('cost_accounting',{}).get('pending_call',{});used+=pending.get('reserve',0)
        cap=self.config()['daily_ai_budget'];return {'cap':cap,'used':used,'remaining':max(0,cap-used),'day':'UTC','basis':'Recorded usage-priced estimates plus unresolved reservations; infrastructure excluded'}
    def board(self,state,operations,now=None):
        now=time.time() if now is None else now;config=self.config();budget=self.budget(state,now);tasks=[]
        owners={'model':'operations','quotes':'execution','pricing':'finance','worker':'operations','feed':'research','fresh':'research','billing':'finance','risk':'risk','eligible':'research'}
        for check in operations['checklist']:
            if not check['ok']:tasks.append((check['key'],'Resolve: '+check['label'],owners[check['key']],check['detail']))
        if budget['remaining']<5*state['config']['cost_per_call']:tasks.append(('inference_budget','Review daily AI budget','finance','Five-agent decision reserve exceeds remaining daily allowance.'))
        tasks.append(('evaluate_edge','Evaluate evidence of a trading edge','audit','Compare prospective account returns, costs and failures. No profitability claim until evidence supports it.'))
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:
            active={k for k,_,_,_ in tasks}
            for i,key in db.execute("SELECT id,task_key FROM company_tasks WHERE status!='done'").fetchall():
                if key not in active:db.execute("UPDATE company_tasks SET status='done',updated=? WHERE id=?",(now,i))
            for key,title,owner,note in tasks:
                db.execute("INSERT INTO company_tasks(task_key,title,owner,status,created,updated,note) SELECT ?,?,?,'blocked',?,?,? WHERE NOT EXISTS (SELECT 1 FROM company_tasks WHERE task_key=? AND status!='done')",(key,title,owner,now,now,note,key))
            orders=[dict(zip(['id','key','title','owner','status','created','updated','note'],r)) for r in db.execute('SELECT id,task_key,title,owner,status,created,updated,note FROM company_tasks ORDER BY (status=\'done\'),id DESC LIMIT 100')]
        events=state.get('events',[]);employees=[]
        for key,name,department,responsibility,kind in STAFF:
            reports=[e for e in events if e.get('agent')==name];report=reports[0] if reports else None;work=[t for t in orders if t['owner']==key and t['status']!='done'];is_ai=kind=='AI review'
            status='Setup required' if is_ai and state['config']['provider']=='none' else 'Working' if report and report.get('kind')=='live_agent_started' and now-report.get('timestamp',0)<90 else 'Report received' if report else 'Monitoring' if state.get('worker_running') and not is_ai else 'Waiting'
            employees.append({'id':key,'name':name,'department':department,'responsibility':responsibility,'type':kind,'status':status,'tasks':[t['id'] for t in work],'last_report':report.get('timestamp') if report else None,'summary':report.get('summary') if report else responsibility})
        return {'config':config,'mission':MISSION,'budget':budget,'employees':employees,'tasks':orders,'departments':list(dict.fromkeys(e['department'] for e in employees)),'authority':'Owner approves real wallet transactions. CEO and AI cannot increase capital, lift shutdowns or override token-risk gates.','capital':{'equity':state['strategy']['equity'],'cash':state['strategy']['cash'],'exposure':state['strategy']['exposure'],'shutdown_equity':90,'max_exposure':30,'per_position':10},'briefing':operations['daily'],'limitations':'AI employees need a configured model. Service employees execute existing fixed rules; no human employees, separate payroll or guaranteed capital growth.'}
