"""Persistent prospective $100 live-data paper trial. No real trade endpoints."""
import json, math, sqlite3, threading, time
from datetime import datetime, timezone
from dataclasses import asdict, replace
from engine import Settings, ScreeningAgent, PaperExecutionAgent, get_json
from agents import ModelClient, ROLES, validate_output
from token_risk import scan as scan_risk, KNOWLEDGE
from paper_quotes import QuoteExecution, usage_cost
import swaps
from live_execution import ControlledLiveExecution, LiveGuard
from market_evidence import evidence,assess
from virtual_company import Company,MISSION

S=Settings(capital=100,ticket=10,max_positions=3,max_exposure=.3,max_loss=.1)

def initial():
    def book():return dict(cash=100.,positions={},pending=[],equity=100.,peak=100.,drawdown=0.,halted=False,cost=0.,trades=0,pnl=0.,exposure=0.)
    return dict(enabled=False,status='not_started',created=time.time(),config=dict(provider='none',model='',cost_per_call=0.,daily_calls=20),
        strategy=book(),baseline=book(),history={},watch=[],ticks=0,last_tick=None,day='',calls_today=0,settings=asdict(S),
        valuation='Hypothetical fills from live DEX snapshots. No executable quotes or token security certification.')

class TrialStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=15)
        self.db.execute('CREATE TABLE IF NOT EXISTS live_state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS live_log(id INTEGER PRIMARY KEY, received REAL, kind TEXT, payload TEXT)');self.db.commit()
    def load(self):
        row=self.db.execute('SELECT payload FROM live_state WHERE id=1').fetchone();return json.loads(row[0]) if row else initial()
    def save(self,state,events):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO live_state VALUES(1,?)',(json.dumps(state,allow_nan=False),))
            for e in events:self.db.execute('INSERT INTO live_log(received,kind,payload) VALUES(?,?,?)',(time.time(),e['kind'],json.dumps(e,allow_nan=False)))
    def capital_history(self):
        rows=self.db.execute("SELECT payload FROM live_log WHERE kind='valuation' ORDER BY id DESC LIMIT 10000").fetchall()
        points=[]
        for (payload,) in reversed(rows):
            value=json.loads(payload)
            if all(isinstance(value.get(k),(int,float)) and not isinstance(value[k],bool) and math.isfinite(value[k]) for k in ('timestamp','strategy','baseline')):
                points.append(dict(timestamp=value['timestamp'],strategy=value['strategy'],baseline=value['baseline']))
        return points
    def logs(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM live_log ORDER BY id DESC LIMIT 100')]

def normalize_pairs(mint,pairs,now):
    valid=[]
    for p in pairs if isinstance(pairs,list) else []:
        try:
            if p.get('chainId')!='solana' or p['baseToken']['address']!=mint:continue
            price=float(p['priceUsd']);liquidity=float(p['liquidity']['usd']);created=float(p['pairCreatedAt'])/1000
            if not all(math.isfinite(x) for x in (price,liquidity,created)) or price<=0 or liquidity<0 or created>now:continue
            valid.append(dict(token=mint,price=price,liquidity=liquidity,age_hours=(now-created)/3600,
                observed=now,available=True,exit_ok=True,pair=p['pairAddress'],source='DEX Screener',source_timestamp=None,synthetic=False,activity=evidence(p,now)))
        except (KeyError,TypeError,ValueError):continue
    return max(valid,key=lambda r:r['liquidity']) if valid else None

def readiness(state,now):
    reasons={}
    for item in state.get('screening',[]):
        reason=item['reason']
        reasons[reason]=reasons.get(reason,0)+1
    blockers=[]
    if not state.get('worker_running'):blockers.append('Paper worker is stopped.')
    if state['config']['provider']=='none':blockers.append('Choose and configure an AI provider; no AI team is running yet.')
    if not state.get('valid_price_snapshots'):blockers.append('No usable pool prices in the latest observation.')
    if state.get('accounting_version')==2 and not swaps.credential():blockers.append('Connect a Jupiter key for quote-based paper fills; no snapshot fallback for new entries.')
    if not state.get('eligible_count'):blockers.append('No token passes the pool, history and momentum requirements yet.')
    if (state.get('cost_accounting',{}).get('pending_call') or state.get('cost_accounting',{}).get('unresolved_calls')):blockers.append('An interrupted AI call has unresolved billing; new AI decisions are paused.')
    if state['strategy']['halted']:blockers.append('Loss shutdown is latched; new entries are disabled.')
    if state['calls_today']+5>state['config']['daily_calls']:blockers.append('Daily AI allowance cannot fund another five-agent decision.')
    if state.get('last_tick') is not None and now-state['last_tick']>90:blockers.append('Latest completed observation is stale.')
    return dict(blockers=blockers,screening_counts=reasons,
        modeled_operating_cost_per_day=0 if state.get('accounting_version')==2 else S.operating_cost_step*1440,
        quote_provider_configured=bool(swaps.credential()),
        cost_accounting=state.get('cost_accounting',{}),
        estimated_ai_cost_per_decision=5*state['config']['cost_per_call'],
        completed_strategy_trades=state['strategy']['trades'],
        performance='Profitability unproven; compare prospective net results with the baseline.',
        real_money='AI paper only; real swaps require separate wallet approval. Basic token-risk checks do not certify safety.')

def process_tick(state,rows,now,decide=None,stopping=False,execution=None,settings=None):
    S=settings or globals()['S']
    events=[];execution=execution or PaperExecutionAgent();screen=ScreeningAgent()
    def log(kind,**data):events.append(dict(kind=kind,timestamp=now,**data))
    fresh={r['token']:r for r in rows if 0<=now-r['observed']<=90}
    if state['last_tick'] is not None and now-state['last_tick']>90:
        state['history']={};log('data_gap',message='Momentum history cleared after a missed interval.')
    eligible=[];state['screening']=[]
    for token in state['watch']:
        r=fresh.get(token);reason='missing_or_stale' if not r else screen.check(r,now,S)
        if r and state.get('quality_policy_version'):
            quality_history=state.setdefault('quality_history',{}).setdefault(token,[])
            quality=assess(r,quality_history,now);r['quality']=quality
            quality_history.append(dict(pair=r['pair'],liquidity=r['liquidity'],time=now))
            state['quality_history'][token]=quality_history[-6:]
            if not quality['allowed']:reason=quality['reasons'][0]
            log('market_quality',token=token,evidence=quality)
        if reason:state['screening'].append(dict(token=token,reason=reason));state['history'].pop(token,None);log('candidate_rejected',token=token,reason=reason);continue
        history=state['history'].get(token,[])
        if history and history[-1]['pair']!=r['pair']:history=[]
        history=(history+[dict(price=r['price'],pair=r['pair'],time=now,liquidity=r['liquidity'])])[-6:];state['history'][token]=history
        if len(history)==6 and now-history[0]['time']>=240 and r['price']/history[0]['price']-1>=S.momentum:eligible.append(token)
        state['screening'].append(dict(token=token,reason='eligible' if token in eligible else 'history_or_momentum'))
        log('candidate',token=token,eligible=token in eligible,reason='eligible' if token in eligible else 'history_or_momentum',price=r['price'])
    state['eligible_count']=len(eligible)
    day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
    if state['day']!=day:state['day']=day;state['calls_today']=0
    def value(p,r,name='valuation'):
        try:return execution.sell_value(p,r,S)
        except Exception:
            log('paper_quote_unavailable',portfolio=name,token=r['token'],message='No fresh acceptable exit quote; retained position marked zero.')
            return None
    def mark(book):
        return sum((value(p,fresh[t]) or 0) if t in fresh and fresh[t]['liquidity']>0 else 0 for t,p in book['positions'].items())
    for name in (('strategy','baseline','rules') if 'rules' in state else ('strategy','baseline')):
        b=state[name];charge=min(b['cash'],S.operating_cost_step);b['cash']-=charge;b['cost']+=charge
        if charge<S.operating_cost_step or b['cash']+mark(b)<=90:b['halted']=True
        for token,p in list(b['positions'].items()):
            r=fresh.get(token)
            if not r or r['liquidity']<=0:log('failed_exit',portfolio=name,token=token,reason='missing_or_stale_snapshot');continue
            change=r['price']/p['entry_price']-1
            must_exit=b['halted'] or now-p['opened']>=S.hold_steps*60 or (name in ('strategy','rules') and (change<=-S.stop_loss or change>=S.take_profit))
            if must_exit and 'exit_due' not in p:p['exit_due']=now+60;log('exit_signal',portfolio=name,token=token)
            if p.get('exit_due',math.inf)<=now:
                proceeds=value(p,r,name)
                if proceeds is None:continue
                b['cash']+=proceeds;b['trades']+=1;del b['positions'][token]
                b['cost']+=S.network_cost
                log('paper_sell',portfolio=name,token=token,proceeds=proceeds,trade_pnl=proceeds-p['cost']-p.get('entry_network_cost',0),opened=p['opened'],mode=p.get('fill_mode','hypothetical_live_snapshot_fill'))
        for order in list(b['pending']):
            if order['due']>now:continue
            b['pending'].remove(order);token=order['token'];r=fresh.get(token)
            reason='missing_or_stale' if not r else screen.check(r,now,S)
            if r and state.get('quality_policy_version') and not r.get('quality',{}).get('allowed'):reason='market_quality_rejected'
            exposure=sum(p['cost'] for p in b['positions'].values())
            risk=state.get('token_risk',{}).get(token)
            if (name in ('strategy','rules') or isinstance(execution,QuoteExecution)) and (not risk or not risk.get('allowed') or now>risk.get('expires',0)):reason='token_risk_unknown_or_stale'
            if now-order['due']>90:reason='expired_order'
            if b['halted'] or b['cash']+mark(b)<=90:reason='loss_shutdown';b['halted']=True
            if token in b['positions'] or len(b['positions'])>=3 or exposure+10>30 or b['cash']<10+S.network_cost:reason='capital_or_position_limit'
            if stopping:reason='trial_pausing'
            if reason:log('order_rejected',portfolio=name,token=token,reason=reason);continue
            try:units,price=execution.buy(r,S)
            except Exception:
                log('order_rejected',portfolio=name,token=token,reason='fresh_quote_or_roundtrip_unavailable');continue
            if isinstance(execution,QuoteExecution) and (execution.clock()-r['observed']>90 or execution.clock()>risk.get('expires',0)):
                log('order_rejected',portfolio=name,token=token,reason='evidence_expired_during_quote');continue
            mode=getattr(execution,'mode','hypothetical_live_snapshot_fill')
            b['cash']-=10+S.network_cost;b['cost']+=S.network_cost;b['positions'][token]=dict(units=units,entry_price=price,opened=now,cost=10,entry_network_cost=S.network_cost,fill_mode=mode,**getattr(execution,'last_fill',{}))
            log('paper_buy',portfolio=name,token=token,price=price,units=units,mode=mode)
            if b['cash']+mark(b)<=90:b['halted']=True
    candidates=[t for t in eligible if t not in state['strategy']['positions'] and not any(o['token']==t for o in state['strategy']['pending'])]
    approvals=[];exits=[]
    if candidates and not stopping and not state['strategy']['halted']:
        c=state['config'];reserve=5*c['cost_per_call']
        if c['provider']=='none':state['status']='waiting_for_ai_provider';log('ai_wait',message='AI configuration required; no AI entries.')
        elif state['calls_today']+5>c['daily_calls']:state['status']='daily_ai_budget_reached'
        elif state['strategy']['cash']<reserve+10+S.network_cost:state['status']='ai_cash_budget_reached'
        elif decide:
            try:approvals,exits=decide(candidates,fresh,state,events)
            except Exception:state['status']='ai_error';log('ai_error',message='No approval: model unavailable or invalid output.')
    for token in approvals:
        if token in candidates:state['strategy']['pending'].append(dict(token=token,due=now+60));log('ai_entry_signal',token=token)
    for token in exits:
        if token in state['strategy']['positions']:state['strategy']['positions'][token].setdefault('exit_due',now+60)
    b=state['baseline']
    for token in sorted(fresh):
        if not stopping and not b['halted'] and not screen.check(fresh[token],now,S) and (not state.get('quality_policy_version') or fresh[token].get('quality',{}).get('allowed')) and len(state['history'].get(token,[]))>=6 and token not in b['positions'] and not any(o['token']==token for o in b['pending']):b['pending'].append(dict(token=token,due=now+60))
    if 'rules' in state:
        b=state['rules']
        rules_eligible=[t for t in fresh if len(state['history'].get(t,[]))>=6 and fresh[t]['price']/state['history'][t][0]['price']-1>=state.get('rules_momentum',S.momentum) and not screen.check(fresh[t],now,S) and (not state.get('quality_policy_version') or fresh[t].get('quality',{}).get('allowed'))]
        for token in rules_eligible:
            if not stopping and not b['halted'] and token not in b['positions'] and not any(o['token']==token for o in b['pending']):
                b['pending'].append(dict(token=token,due=now+60));log('rules_entry_signal',token=token)
    for name in (('strategy','baseline','rules') if 'rules' in state else ('strategy','baseline')):
        b=state[name];b['equity']=b['cash']+mark(b);b['peak']=max(b['peak'],b['equity']);b['drawdown']=max(b['drawdown'],(b['peak']-b['equity'])/b['peak'])
        if b['equity']<=90:b['halted']=True
        b['pnl']=b['equity']-100;b['exposure']=sum(p['cost'] for p in b['positions'].values())
    state['ticks']+=1;state['last_tick']=now
    log('valuation',strategy=state['strategy']['equity'],baseline=state['baseline']['equity']);return events

class LiveTrial:
    def __init__(self,path,pump):
        self.path=path;self.pump=pump;self.stop_event=threading.Event();self.thread=None;self.lock=threading.Lock()
    def snapshot(self):
        store=TrialStore(self.path)
        try:
            state=store.load();state['events']=store.logs();state['capital_history']=store.capital_history();state['worker_running']=bool(self.thread and self.thread.is_alive());state['readiness']=readiness(state,time.time());return state
        finally:store.db.close()
    def start(self,config=None):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if config is not None:raise ValueError('Pause the trial before changing AI configuration.')
                return self.snapshot()
            store=TrialStore(self.path);state=store.load()
            try:
                if config is not None:
                    provider=config.get('provider','none');model=config.get('model','');cost=config.get('cost_per_call',0);limit=config.get('daily_calls',20)
                    if provider not in ('none','ollama','openai') or type(limit)!=int or not 5<=limit<=100:raise ValueError('Invalid provider or daily call cap (5–100)')
                    if not isinstance(cost,(int,float)) or not math.isfinite(cost) or not 0<=cost<=1:raise ValueError('Estimated inference cost must be 0–1 dollars per call')
                    if provider!='none':ModelClient(provider,model)
                    if provider=='openai' and cost<=0:raise ValueError('Positive cost estimate required')
                    rates=config.get('token_rates',{})
                    if provider=='openai' and (usage_cost({'input_tokens':1,'output_tokens':1},rates) is None or rates.get('input',0)<=0 or rates.get('output',0)<=0):raise ValueError('Enter current input, cached-input and output prices per million tokens.')
                    network=config.get('network_cost',0)
                    if isinstance(network,bool) or not isinstance(network,(int,float)) or not math.isfinite(network) or not 0<=network<=1:raise ValueError('Network-cost scenario must be 0–1 USD per fill.')
                    state['config']=dict(provider=provider,model=model,cost_per_call=cost,daily_calls=limit,token_rates=rates,network_cost=network)
                state['enabled']=True;state['status']='collecting_live_observations';store.save(state,[dict(kind='trial_started',timestamp=time.time(),config=state['config'])])
            finally:store.db.close()
            self.stop_event.clear();self.pump.start();self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start();return self.snapshot()
    def stop(self):
        self.stop_event.set()
        return dict(status='stopping',message='Pausing after any in-flight request; paper positions and balance retained.')
    def decide(self,candidates,rows,state,events):
        if (state.get('cost_accounting',{}).get('pending_call') or state.get('cost_accounting',{}).get('unresolved_calls')):
            state['status']='billing_reconciliation_required';return [],[]
        company=Company(self.path);budget=company.budget(state)
        if 5*state['config']['cost_per_call']>budget['remaining']:
            state['status']='company_ai_budget_reached';events.append(dict(kind='company_budget_block',timestamp=time.time(),budget=budget));return [],[]
        screened=sorted(candidates,key=lambda t:state.get('token_risk',{}).get(t,{}).get('observed',0))[:1];reports_by_token={}
        for token in screened:
            report=scan_risk(token,self.path);reports_by_token[token]=report
            prior=state.get('token_risk',{}).get(token,{})
            old=prior.get('metrics',{}).get('top10_sampled_owners_pct');new=report.get('metrics',{}).get('top10_sampled_owners_pct')
            state.setdefault('holder_changes',{})[token]=dict(observed=report.get('observed'),previous_observed=prior.get('observed'),top10_change_points=new-old if isinstance(new,(int,float)) and isinstance(old,(int,float)) else None,scope='Largest-account sample concentration changes; holder transactions and insiders are unverified.')
            events.append(dict(kind='token_risk_check',timestamp=time.time(),token=token,status=report['status'],reasons=report['reasons']))
        state.setdefault('token_risk',{}).update(reports_by_token)
        candidates=[t for t in screened if reports_by_token[t]['allowed'] and time.time()<=reports_by_token[t]['expires']]
        if not candidates:
            state['status']='waiting_for_token_risk_evidence';return [],[]
        if state.get('accounting_version')==2 and not swaps.credential():
            state['status']='waiting_for_quote_provider';return [],[]
        c=state['config']
        if state.get('accounting_version')==2 and c['provider']=='openai' and usage_cost({'input_tokens':1,'output_tokens':1},c.get('token_rates',{})) is None:
            state['status']='waiting_for_model_price_configuration';return [],[]
        client=ModelClient(c['provider'],c['model']);reports=[]
        from research_lab import Research
        context=dict(company_mission=MISSION,company_priority=company.config()['priority'],company_budget=budget,synthetic=False,execution='hypothetical_paper_only',eligible=candidates,rows=list(rows.values()),
            positions=state['strategy']['positions'],past_observations=state['history'],settings=state['settings'],
            loss_review=Research(self.path).snapshot()['proposals'][:3],token_risk_reports=reports_by_token,rug_risk_knowledge=KNOWLEDGE,security='Basic risk screen only; LP locks and hidden insiders remain unverified. Snapshots are not executable quotes.')
        for role,instructions in ROLES:
            if c['cost_per_call']>company.budget(state)['remaining']:state['status']='company_ai_budget_reached';return [],[]
            if state.get('cost_accounting',{}).get('unresolved_calls') or state['strategy']['halted'] or self.stop_event.is_set() or time.time()-min(rows[t]['observed'] for t in candidates)>90:return [],[]
            state['calls_today']+=1;state['strategy']['cash']-=c['cost_per_call'];state['strategy']['cost']+=c['cost_per_call']
            if state.get('accounting_version')==2:
                state.setdefault('cost_accounting',{})['pending_call']=dict(agent=role,started=time.time(),reserve=c['cost_per_call'])
            checkpoint=TrialStore(self.path)
            try:checkpoint.save(state,events);events.clear()
            finally:checkpoint.db.close()
            started_report=dict(kind='live_agent_started',timestamp=time.time(),agent=role,status='working',summary='Assessing eligible tokens and earlier team reports.')
            checkpoint=TrialStore(self.path)
            try:checkpoint.save(state,[started_report])
            finally:checkpoint.db.close()
            client.last_usage={}
            try:output=validate_output(client.call(role,instructions,context,reports),candidates,state['strategy']['positions'])
            finally:
                if state.get('accounting_version')==2:
                    measured=usage_cost(client.last_usage,c.get('token_rates',{})) if c['provider']=='openai' else 0
                    accounting=state.setdefault('cost_accounting',{});accounting.pop('pending_call',None)
                    if measured is None:
                        accounting['unresolved_calls']=accounting.get('unresolved_calls',0)+1
                        accounting['unresolved_reserved_usd']=accounting.get('unresolved_reserved_usd',0)+c['cost_per_call']
                        events.append(dict(kind='ai_cost_unresolved',timestamp=time.time(),reserved=c['cost_per_call'],message='Usage unavailable; conservative reservation retained.'))
                    else:
                        delta=measured-c['cost_per_call'];state['strategy']['cash']-=delta;state['strategy']['cost']+=delta
                        accounting['usage_priced_usd']=accounting.get('usage_priced_usd',0)+measured
                        if state['strategy']['cash']<=0 or measured>c['cost_per_call']:state['strategy']['halted']=True
                        events.append(dict(kind='ai_usage_cost',timestamp=time.time(),amount=measured,usage=client.last_usage,rates=c.get('token_rates',{}),basis='Reported tokens × user-configured rates; not provider invoice'))
                    checkpoint=TrialStore(self.path)
                    try:checkpoint.save(state,events);events.clear()
                    finally:checkpoint.db.close()
            reports.append(dict(agent=role,**output));events.append(dict(kind='live_agent_report',timestamp=time.time(),agent=role,usage=client.last_usage,**output))
        if self.stop_event.is_set() or time.time()-min(rows[t]['observed'] for t in candidates)>90:return [],[]
        if state.get('cost_accounting',{}).get('unresolved_calls') or state['strategy']['halted']:return [],[]
        events.append(dict(kind='ai_team_decision',timestamp=time.time(),eligible=candidates,approve=sorted(set(candidates).intersection(*(set(r['approve']) for r in reports))),vetoes={t:[r['agent'] for r in reports if t not in r['approve']] for t in candidates},reports=reports))
        return sorted(set(candidates).intersection(*(set(r['approve']) for r in reports))),reports[-1]['exit']
    def loop(self):
        store=TrialStore(self.path);state=store.load()
        if state.get('accounting_version')!=2:
            state['accounting_version']=2
            state['cost_accounting']=dict(transition_at=time.time(),legacy_cost_preserved=state['strategy']['cost'],usage_priced_usd=0,unresolved_calls=0,unresolved_reserved_usd=0,infrastructure='Not measured; excluded and disclosed',network='User-declared per-fill scenario, not measured chain fees')
            state['valuation']='New fills: conservative Jupiter USDC quotes, not transactions. Legacy positions retain snapshot assumptions. Infrastructure and actual chain costs are unmeasured.'
            store.save(state,[dict(kind='accounting_transition',timestamp=time.time(),legacy_strategy_equity=state['strategy']['equity'],legacy_baseline_equity=state['baseline']['equity'],message='No history reset. Arbitrary per-observation charges removed prospectively; quote fills required for new entries.')])
        if 'rules' not in state:
            state['rules']=initial()['strategy']
            state['comparison_start']=dict(timestamp=time.time(),equity={n:state[n]['equity'] for n in ('strategy','baseline','rules')})
            store.save(state,[dict(kind='comparison_started',timestamp=time.time(),message='Fixed momentum comparison started prospectively. Existing accounts retained.')])
        try:
            while not self.stop_event.is_set():
                started=time.time();events=[]
                recent=store.db.execute('SELECT normalized FROM pump_events ORDER BY id DESC LIMIT 200').fetchall()
                tokens=list(dict.fromkeys(json.loads(r[0])['mint'] for r in recent))
                migrations=store.db.execute("SELECT normalized FROM pump_events WHERE json_extract(normalized,'$.kind')='migration' ORDER BY id DESC LIMIT 200").fetchall()
                migrated=list(dict.fromkeys(json.loads(r[0])['mint'] for r in migrations))
                held=list(dict.fromkeys(list(state['strategy']['positions'])+list(state['baseline']['positions'])+list(state.get('rules',{}).get('positions',{}))))
                from research_lab import Research
                held=list(dict.fromkeys(held+Research(self.path).held()))
                cooldown=state.setdefault('unpriced_cooldown',{})
                cooldown={t:until for t,until in cooldown.items() if until>started};state['unpriced_cooldown']=cooldown
                pool=list(dict.fromkeys(migrated+state['watch']+tokens))
                state['watch']=list(dict.fromkeys(held+[t for t in pool if t not in cooldown]))[:20]
                rows=[]
                if state['watch'] and not self.stop_event.is_set():
                    try:
                        raw=get_json('https://api.dexscreener.com/tokens/v1/solana/'+','.join(state['watch']),{'User-Agent':'MemecoinResearchLab/1.0','Accept':'application/json'})
                        received=time.time()
                        if not isinstance(raw,list):raise ValueError('Invalid batch snapshot')
                        events.append(dict(kind='live_snapshot_batch',timestamp=received,tokens=state['watch'],raw=raw))
                        for mint in state['watch']:
                            row=normalize_pairs(mint,raw,received)
                            if row:rows.append(row)
                    except Exception as exc:
                        events.append(dict(kind='snapshot_failure',timestamp=time.time(),tokens=state['watch'],error_type=type(exc).__name__,http_status=getattr(exc,'code',None)))
                state['poll_duration_seconds']=round(time.time()-started,3)
                priced={r['token'] for r in rows};misses=state.setdefault('unpriced_attempts',{})
                for mint in state['watch']:
                    misses[mint]=0 if mint in priced else misses.get(mint,0)+1
                    if misses[mint]>=3 and mint not in held:
                        cooldown[mint]=time.time()+3600
                        events.append(dict(kind='monitor_cooldown',timestamp=time.time(),token=mint,reason='Three observations without a usable pool; raw failures retained.'))
                state['unpriced_attempts']={t:n for t,n in misses.items() if t in state['watch']}
                state['quality_policy_version']=1;state['valid_price_snapshots']=len(rows)
                state['market_rows']=rows
                # Give the baseline the same entry-security gate; never scan more than one due mint per cycle.
                if swaps.credential() and not self.stop_event.is_set():
                    due=[o['token'] for o in state['baseline']['pending']+state.get('rules',{}).get('pending',[]) if o['due']<=time.time() and any(r['token']==o['token'] for r in rows)]
                    for token in due[:1]:
                        existing=state.get('token_risk',{}).get(token,{})
                        if time.time()>existing.get('expires',0):
                            report=scan_risk(token,self.path);state.setdefault('token_risk',{})[token]=report
                            events.append(dict(kind='baseline_token_risk_check',timestamp=time.time(),token=token,status=report['status'],reasons=report['reasons']))
                network=state['config'].get('network_cost',0)
                execution=QuoteExecution(events,network_cost=network)
                live_settings=replace(S,operating_cost_step=0,network_cost=network)
                state['settings']=asdict(live_settings)
                live_guard=LiveGuard(self.path)
                if live_guard.status()['armed'] and not live_guard.status()['halted']:
                    execution=ControlledLiveExecution(self.path)
                    state['execution_mode']=execution.mode
                    events.append(dict(kind='live_execution_armed',timestamp=time.time(),mode=execution.mode,limits=live_guard.status()['limits']))
                else:
                    state['execution_mode']=execution.mode
                events+=process_tick(state,rows,time.time(),None if self.stop_event.is_set() else self.decide,self.stop_event.is_set(),execution,live_settings)
                if self.stop_event.is_set():state['enabled']=False;state['status']='paused'
                elif state['strategy']['halted']:state['status']='loss_shutdown_exits_only'
                elif state['config']['provider']=='none':state['status']='observing_waiting_for_ai_provider'
                store.save(state,events)
                from research_lab import Research
                try:Research(self.path).tick(rows,time.time(),state,events,execution)
                except Exception as exc:
                    store.save(state,[dict(kind='research_error',timestamp=time.time(),error_type=type(exc).__name__)])
                self.stop_event.wait(max(1,60-(time.time()-started)))
            state['enabled']=False;state['status']='paused'
            state['strategy']['pending']=[];state['baseline']['pending']=[]
            if 'rules' in state:state['rules']['pending']=[]
            store.save(state,[dict(kind='trial_paused',timestamp=time.time())])
        except Exception:
            state=store.load();state['enabled']=False;state['status']='worker_error';store.save(state,[dict(kind='worker_error',timestamp=time.time())])
        finally:store.db.close()
    def resume(self):
        if self.snapshot()['enabled']:self.start()




