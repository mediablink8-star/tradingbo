"""Prospective matched paper comparison, frozen challengers and owner review."""
import json,sqlite3,time,uuid
from contextlib import closing
from dataclasses import replace,asdict
class Research:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path,timeout=15)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,kind TEXT,created REAL,state TEXT,config TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS research_frames(id INTEGER PRIMARY KEY,run TEXT,timestamp REAL,payload TEXT,UNIQUE(run,timestamp))')
            db.execute('CREATE TABLE IF NOT EXISTS research_proposals(id TEXT PRIMARY KEY,created REAL,payload TEXT,status TEXT,run TEXT)')
    def start(self,kind='matched',config=None):
        from live_trial import initial,S
        now=time.time();state=initial();state['rules']=initial()['strategy'];state['watch']=[];state['quality_policy_version']=1;state['config'].update(provider='ollama',model='observed-live-verdicts',daily_calls=100);state['last_cost_id']=0;state['closed_trades']=[];state['failure_count']=0;state['last_ai_cost_total']=0
        config=config or {'momentum':S.momentum,'stop_loss':S.stop_loss,'take_profit':S.take_profit,'hold_steps':S.hold_steps,'network_cost':0};identifier=uuid.uuid4().hex
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:
            if kind=='matched' and db.execute("SELECT id FROM research_runs WHERE kind='matched'").fetchone():return
            maxid=db.execute('SELECT COALESCE(MAX(id),0) FROM live_log').fetchone()[0];state['last_cost_id']=maxid
            db.execute('INSERT INTO research_runs VALUES(?,?,?,?,?)',(identifier,kind,now,json.dumps(state),json.dumps(config)))
        return identifier
    def tick(self,rows,now,production,events,execution):
        from live_trial import process_tick,S
        self.start(config={'momentum':S.momentum,'stop_loss':S.stop_loss,'take_profit':S.take_profit,'hold_steps':S.hold_steps,'network_cost':production['config'].get('network_cost',0)})
        approves=[e['token'] for e in events if e['kind']=='ai_entry_signal'];exits=[t for e in events if e['kind']=='ai_team_decision' for t in e.get('reports',[{}])[-1].get('exit',[])]
        with closing(sqlite3.connect(self.path,timeout=15)) as db:runs=db.execute('SELECT id,state,config FROM research_runs').fetchall()
        for identifier,raw,settings in runs:
            state=json.loads(raw);config=json.loads(settings)
            if state.get('completed'):continue
            if state['last_tick'] is not None and now<=state['last_tick']:continue
            state['watch']=list(dict.fromkeys(production.get('watch',[r['token'] for r in rows])+[t for n in ('strategy','baseline','rules') for t in state[n]['positions']]))
            state['token_risk']=production.get('token_risk',{})
            with closing(sqlite3.connect(self.path,timeout=15)) as db:costs=db.execute("SELECT id,payload FROM live_log WHERE id>? AND kind IN ('ai_usage_cost','ai_cost_unresolved') ORDER BY id",(state['last_cost_id'],)).fetchall()
            charge=0
            for eid,payload in costs:
                c=json.loads(payload);charge+=c.get('amount',c.get('reserved',0));state['last_cost_id']=eid
            state['strategy']['cash']-=charge;state['strategy']['cost']+=charge;state['last_ai_cost_total']+=charge
            if state['strategy']['equity']-charge<=90:state['strategy']['halted']=True
            effective=dict(config)
            if config['momentum']!=S.momentum:state['rules_momentum']=config['momentum'];effective['momentum']=S.momentum
            frozen=replace(S,**effective,operating_cost_step=0)
            # Challenger modifies only fixed rules; the AI arm keeps frozen matched policy.
            from paper_quotes import QuoteExecution
            adapter=QuoteExecution(execution.events,network_cost=frozen.network_cost,quote=execution.quote,rpc=execution.rpc,clock=execution.clock) if isinstance(execution,QuoteExecution) else execution
            if isinstance(execution,QuoteExecution):adapter.cache=execution.cache;adapter.decimals=execution.decimals
            out=process_tick(state,[dict(r) for r in rows],now,lambda *args:(approves,exits),execution=adapter,settings=frozen)
            state['closed_trades']=(state['closed_trades']+[e for e in out if e['kind']=='paper_sell'])[-500:]
            state['failure_count']+=sum(e['kind'] in ('failed_exit','paper_quote_unavailable','order_rejected') for e in out)
            state['observed_verdicts']=len(approves)
            frame={'rows':rows,'approvals':approves,'exits':exits,'ai_cost':charge,'events':out,'execution':'Shared read-only quote adapter; no additional model calls'}
            with closing(sqlite3.connect(self.path,timeout=15)) as db,db:
                db.execute('INSERT OR IGNORE INTO research_frames(run,timestamp,payload) VALUES(?,?,?)',(identifier,now,json.dumps(frame,allow_nan=False)))
                db.execute('UPDATE research_runs SET state=? WHERE id=?',(json.dumps(state,allow_nan=False),identifier))
        if any(e.get('kind')=='paper_sell' and e.get('trade_pnl',0)<0 for e in events):self.propose()
    def propose(self):
        with closing(sqlite3.connect(self.path,timeout=15)) as db:
            losses=[json.loads(r[0]) for r in db.execute("SELECT payload FROM live_log WHERE kind='paper_sell' AND json_extract(payload,'$.trade_pnl')<0 ORDER BY id DESC LIMIT 20")]
            rejects=[json.loads(r[0]) for r in db.execute("SELECT payload FROM live_log WHERE kind='order_rejected' ORDER BY id DESC LIMIT 100")]
        if not losses:return {'status':'insufficient_evidence','message':'No recorded losing trades with trade-level P&L yet. No fabricated review or strategy change.'}
        cfg={'momentum':.05,'stop_loss':.05,'take_profit':.08,'hold_steps':12,'network_cost':0}
        proposal={'title':'Test a stricter 5% momentum entry','analyst':'Deterministic loss-review rule; no model called','hypothesis':'A stronger entry threshold may reduce weak entries, but may worsen entry timing. Test prospectively.','auditor':'Losses alone do not prove causality. Freeze this challenger, retain failures and compare new data without revising the active policy.','losses_reviewed':losses,'execution_rejections':len(rejects),'config':cfg,'deployment':'Owner review only; no automatic adoption'}
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:
            existing=db.execute("SELECT id FROM research_proposals WHERE status='proposed'").fetchone()
            if existing:return {'status':'existing_proposal','id':existing[0]}
            identifier=uuid.uuid4().hex;db.execute('INSERT INTO research_proposals VALUES(?,?,?,?,?)',(identifier,time.time(),json.dumps(proposal),'proposed',None))
        return {'status':'proposed','id':identifier}
    def test_proposal(self,identifier):
        with closing(sqlite3.connect(self.path,timeout=15)) as db:r=db.execute('SELECT payload,status,run FROM research_proposals WHERE id=?',(identifier,)).fetchone()
        if not r:raise ValueError('Unknown proposal')
        if r[2]:return {'run':r[2]}
        if r[1]!='proposed':raise ValueError('Proposal already reviewed')
        with closing(sqlite3.connect(self.path,timeout=15)) as db:
            if db.execute("SELECT COUNT(*) FROM research_runs WHERE kind='challenger' AND COALESCE(json_extract(state,'$.completed'),0)=0").fetchone()[0]>=1:raise ValueError('One frozen challenger at a time; finish evaluating it before adding another.')
        config=json.loads(r[0])['config']
        with closing(sqlite3.connect(self.path,timeout=15)) as db:matched=db.execute("SELECT config FROM research_runs WHERE kind='matched'").fetchone()
        if matched:config['network_cost']=json.loads(matched[0])['network_cost']
        run=self.start('challenger',config)
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:db.execute("UPDATE research_proposals SET status='testing',run=? WHERE id=?",(run,identifier))
        return {'run':run,'message':'Frozen prospective test started; active strategy unchanged.'}
    def finish(self,identifier):
        with closing(sqlite3.connect(self.path,timeout=15)) as db,db:
            row=db.execute('SELECT run,status FROM research_proposals WHERE id=?',(identifier,)).fetchone()
            if not row or not row[0]:raise ValueError('No test for this proposal')
            raw=db.execute('SELECT state FROM research_runs WHERE id=?',(row[0],)).fetchone()[0]
            state=json.loads(raw);state['completed']=True
            db.execute('UPDATE research_runs SET state=? WHERE id=?',(json.dumps(state),row[0]))
            db.execute("UPDATE research_proposals SET status='completed' WHERE id=?",(identifier,))
        return {'message':'Test archived with its final observations. Open paper positions remain in the recorded results. Active policy unchanged.'}
    def held(self):
        with closing(sqlite3.connect(self.path,timeout=15)) as db:states=[json.loads(r[0]) for r in db.execute('SELECT state FROM research_runs')]
        return list(dict.fromkeys(t for s in states if not s.get('completed') for n in ('strategy','baseline','rules') for t in s[n]['positions']))
    def snapshot(self):
        with closing(sqlite3.connect(self.path,timeout=15)) as db:
            runs=db.execute('SELECT id,kind,created,state,config FROM research_runs ORDER BY created DESC').fetchall();proposals=db.execute('SELECT id,created,payload,status,run FROM research_proposals ORDER BY created DESC LIMIT 20').fetchall()
        output=[]
        for identifier,kind,created,raw,cfg in runs:
            s=json.loads(raw);books=[]
            for key,title in [('strategy','Observed AI decisions'),('rules','Fixed momentum'),('baseline','Holding baseline')]:
                b=s[key];trades=[t for t in s['closed_trades'] if t['portfolio']==key];books.append({'name':title,'equity':b['equity'],'pnl':b['equity']-100,'drawdown':b['drawdown'],'trades':b['trades'],'win_rate':sum(t.get('trade_pnl',0)>0 for t in trades)/len(trades) if trades else None,'charges':b['cost'],'positions':len(b['positions']),'halted':b['halted']})
            output.append({'id':identifier,'kind':kind,'created':created,'completed':s.get('completed',False),'cycles':s['ticks'],'config':json.loads(cfg),'books':books,'failures':s['failure_count'],'ai_usage_cost':s['last_ai_cost_total'],'ai_value_evidence':'Unproven; observed live approvals are reused, not independent randomized AI reviews.'})
        return {'runs':output,'proposals':[{'id':i,'created':t,**json.loads(p),'status':status,'run':r} for i,t,p,status,r in proposals],'comparison':'All new comparison books start at $100, share observation cycles, universe, hard risk gates, quote adapter and frozen settings. Only the AI arm pays recorded inference costs. Unavailable quotes stay unavailable. Historic production books are untouched.','learning':'Proposals are frozen and tested only on future observations. No automatic live-policy adoption. Analyst/auditor reviews are deterministic until a separate model-review integration is configured.'}
    def briefing(self,production,operations,company):
        now=time.time();day=now-now%86400
        with closing(sqlite3.connect(self.path,timeout=15)) as db:
            values=[json.loads(r[0]) for r in db.execute("SELECT payload FROM live_log WHERE kind='valuation' AND json_extract(payload,'$.timestamp')>=? ORDER BY id",(day,))]
            trades=[json.loads(r[0]) for r in db.execute("SELECT payload FROM live_log WHERE kind='paper_sell' AND json_extract(payload,'$.timestamp')>=? ORDER BY id DESC",(day,))]
        attributable=[t for t in trades if t.get('portfolio')=='strategy' and isinstance(t.get('trade_pnl'),(int,float))]
        return {'as_of':now,'day':'UTC','capital':production['strategy']['equity'],'capital_change_today':values[-1]['strategy']-values[0]['strategy'] if len(values)>1 else None,'closed_trades_today':len(attributable),'best_trade':max(attributable,key=lambda t:t['trade_pnl']) if attributable else None,'worst_trade':min(attributable,key=lambda t:t['trade_pnl']) if attributable else None,'ai_spending':company['budget'],'needs_attention':[c for c in operations['checklist'] if not c['ok']],'incidents':[a for a in operations['alerts'] if a['resolved'] is None],'limits':'Daily capital change spans recorded valuations only; trade P&L excludes unallocated inference and infrastructure. No retrospective attribution without evidence.'}
