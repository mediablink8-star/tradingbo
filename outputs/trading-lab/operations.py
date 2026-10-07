"""Operational checklist, durable incident history and decision journal. No trade authority."""
import json,sqlite3,time
from contextlib import closing
from live_trial import TrialStore
from paper_quotes import usage_cost
import connections,swaps
KINDS={'reports':['live_agent_report','ai_team_decision'],'trades':['paper_buy','paper_sell','order_rejected','failed_exit','paper_quote_unavailable'],'screening':['candidate_rejected','candidate','token_risk_check','baseline_token_risk_check'],'decisions':['live_agent_report','ai_team_decision','ai_entry_signal','ai_wait','ai_error','order_rejected','paper_buy','paper_sell','accounting_transition']}
def journal(path,category='decisions',before=0,token=''):
    if category not in KINDS or type(before)!=int or before<0 or not isinstance(token,str) or len(token)>100:raise ValueError('Invalid journal filter')
    db=sqlite3.connect(path,timeout=15)
    try:
        kinds=KINDS[category];sql='SELECT id,payload FROM live_log WHERE kind IN ('+','.join('?' for _ in kinds)+')';args=list(kinds)
        if before:sql+=' AND id<?';args.append(before)
        if token:sql+=" AND (json_extract(payload,'$.token')=? OR EXISTS (SELECT 1 FROM json_each(json_extract(payload,'$.approve')) WHERE value=?) OR EXISTS (SELECT 1 FROM json_each(json_extract(payload,'$.eligible')) WHERE value=?))";args.extend([token]*3)
        rows=db.execute(sql+' ORDER BY id DESC LIMIT 51',args).fetchall();items=[{'id':i,**json.loads(p)} for i,p in rows[:50]]
        return {'items':items,'next_cursor':items[-1]['id'] if len(rows)>50 else None,'scope':'50 entries per page; complete history retained','category':category}
    finally:db.close()
def checks(state,pump,now):
    c=state['config'];pricing=c['provider']!='openai' or usage_cost({'input_tokens':1,'output_tokens':1},c.get('token_rates',{})) is not None
    model=c['provider']!='none' and (c['provider']!='openai' or bool(connections.api_key()))
    accounting=state.get('cost_accounting',{});fresh=state.get('last_tick') is not None and 0<=now-state['last_tick']<=90
    return [{'key':k,'label':label,'ok':bool(ok),'detail':detail,'route':route} for k,label,ok,detail,route in [
        ('model','Model connection',model,'Connection selected; availability still needs verification.' if model else 'Choose a local model or connect a hosted model key.','settings'),
        ('quotes','Jupiter quote connection',bool(swaps.credential()),'Credentials configured; successful routes still required.' if swaps.credential() else 'Connect a Jupiter API key for executable quote evidence.','execution'),
        ('pricing','Model prices',pricing,'Enter prices for your exact hosted model.','settings'),
        ('worker','Paper worker',state.get('worker_running'),'Resume the paper trial to collect observations.','settings'),
        ('feed','Discovery feed',pump.get('running') and not pump.get('stale'),'Collector running with a recent heartbeat.','market'),
        ('fresh','Fresh observations',fresh and state.get('valid_price_snapshots',0)>0,'Recent cycle and at least one usable pool price required.','market'),
        ('billing','Billing resolved',not accounting.get('pending_call') and not accounting.get('unresolved_calls'),'Unknown usage reservations pause AI decisions.','settings'),
        ('risk','Risk limits',not state['strategy']['halted'],'Latched risk shutdown blocks new entries.','risk'),
        ('eligible','Eligible candidates',state.get('eligible_count',0)>0,'Waiting for qualifying candidates is normal.','market')]]
def incidents(state,pump,now):
    result={}
    if not state.get('worker_running'):result['worker_stopped']='Paper worker is stopped. Resume it when ready.'
    if not state.get('last_tick') or now-state['last_tick']>90:result['stale_data']='No fresh completed paper observation in the last 90 seconds.'
    if not pump.get('running') or pump.get('stale'):result['feed_down']='Discovery feed is stopped or its heartbeat is stale.'
    if state['strategy']['halted']:result['risk_shutdown']='Risk shutdown is latched. New entries are disabled.'
    a=state.get('cost_accounting',{})
    if a.get('pending_call') or a.get('unresolved_calls'):result['billing_unknown']='AI billing is unresolved. Inspect the cost ledger.'
    if state.get('status') in ('worker_error','ai_error'):result['worker_error']='The paper or AI worker reported an error. Inspect the journal.'
    return result
class Operations:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path,timeout=15)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS operational_alerts(id INTEGER PRIMARY KEY,key TEXT,message TEXT,opened REAL,resolved REAL,acknowledged REAL)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_active_incident ON operational_alerts(key) WHERE resolved IS NULL')
    def update(self,state,pump,now=None):
        now=time.time() if now is None else now;active=incidents(state,pump,now)
        with closing(sqlite3.connect(self.path,timeout=15)) as db, db:
            for key,message in active.items():db.execute('INSERT INTO operational_alerts(key,message,opened) SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM operational_alerts WHERE key=? AND resolved IS NULL)',(key,message,now,key))
            for identifier,key in db.execute('SELECT id,key FROM operational_alerts WHERE resolved IS NULL').fetchall():
                if key not in active:db.execute('UPDATE operational_alerts SET resolved=? WHERE id=?',(now,identifier))
            alerts=[dict(zip(['id','key','message','opened','resolved','acknowledged'],r)) for r in db.execute('SELECT id,key,message,opened,resolved,acknowledged FROM operational_alerts ORDER BY id DESC LIMIT 100')]
        score=[];epoch=state.get('comparison_start')
        for name,title in [('strategy','AI paper decisions'),('rules','Fixed momentum rules'),('baseline','Holding baseline')]:
            b=state.get(name)
            if not b:score.append({'name':title,'status':'Not started'});continue
            start=epoch['equity'][name] if epoch else 100
            score.append({'name':title,'equity':b['equity'],'pnl':b['equity']-start,'return_pct':(b['equity']/start-1)*100,'drawdown':b['drawdown'],'trades':b['trades'],'charges':b['cost'],'status':'Halted' if b['halted'] else 'Observing','start_equity':start})
        return {'checklist':checks(state,pump,now),'alerts':alerts,'scoreboard':score,'comparison_start':epoch,'limitations':'Comparison uses a common start time but different starting balances; AI and baseline retain existing history and positions. Drawdown, charges and trade counts are lifetime values. Returns include quote assumptions, not realized wallet fills. No causal AI advantage is established.','daily':{'date':time.strftime('%Y-%m-%d',time.gmtime(now)),'calls_today':state['calls_today'],'cycles_total':state['ticks'],'eligible_now':state.get('eligible_count',0),'unresolved_alerts':sum(a['resolved'] is None for a in alerts)}}
    def acknowledge(self,identifier):
        if type(identifier)!=int or identifier<=0:raise ValueError('Invalid alert ID')
        with closing(sqlite3.connect(self.path,timeout=15)) as db, db:
            changed=db.execute('UPDATE operational_alerts SET acknowledged=COALESCE(acknowledged,?) WHERE id=?',(time.time(),identifier)).rowcount
            if not changed:raise ValueError('Unknown alert')
        return {'acknowledged':identifier}
