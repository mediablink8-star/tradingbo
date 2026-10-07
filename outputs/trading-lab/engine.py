"""Deterministic agents. No wallet, signing, transaction submission or live execution."""
import math, random, sqlite3, json, time, urllib.request, urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    capital: float = 1000
    ticket: float = 100
    max_positions: int = 3
    max_exposure: float = .3
    max_loss: float = .1
    min_liquidity: float = 100000
    momentum: float = .03
    stop_loss: float = .05
    take_profit: float = .08
    hold_steps: int = 12
    stale_seconds: int = 90
    fee_bps: float = 30
    slippage_bps: float = 50
    latency_steps: int = 1
    network_cost: float = .02
    operating_cost_step: float = .005
    def validate(self):
        for k,v in asdict(self).items():
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v <= 0:
                raise ValueError(f'{k} must be finite and positive')
        for k in ('max_positions','hold_steps','stale_seconds','latency_steps'):
            if int(getattr(self,k)) != getattr(self,k): raise ValueError(f'{k} must be integer')
        if not 0 < self.max_exposure <= 1 or not 0 < self.max_loss < 1: raise ValueError('Invalid risk fractions')
        if self.ticket > self.capital * self.max_exposure: raise ValueError('Ticket exceeds exposure limit')
        if self.fee_bps + self.slippage_bps >= 10000: raise ValueError('Costs too large')
        return self

class Store:
    def __init__(self, path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, created REAL, partition TEXT, settings TEXT, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, received REAL, source TEXT, payload TEXT)')
        self.db.commit()
    def save(self,partition,settings,result):
        cur=self.db.execute('INSERT INTO runs(created,partition,settings,result) VALUES(?,?,?,?)',(time.time(),partition,json.dumps(asdict(settings)),json.dumps(result)))
        self.db.commit(); return cur.lastrowid
    def capture(self,source,payload):
        self.db.execute('INSERT INTO observations(received,source,payload) VALUES(?,?,?)',(time.time(),source,json.dumps(payload)));self.db.commit()
    def history(self):
        return [dict(id=r[0],created=r[1],partition=r[2]) for r in self.db.execute('SELECT id,created,partition FROM runs ORDER BY id DESC LIMIT 30')]
    def load(self,run_id):
        row=self.db.execute('SELECT result FROM runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise ValueError('Run not found')
        result=json.loads(row[0]);result['run_id']=run_id;return result

class Scanner:
    @staticmethod
    def synthetic(partition):
        rng=random.Random(41 if partition=='development' else 871)
        prices=[1.,.4,2.,.8,1.5]; frames=[]
        for step in range(120):
            rows=[]
            for i in range(5):
                prices[i]*=max(.1,1+rng.gauss(.001 if i<2 else -.001,.025))
                if i==3 and step==65: prices[i]*=.15
                # Missing and delisted tokens remain in the universe; no survivor filtering.
                missing=(i==3 and step>=65) or (i==1 and 45<=step<=49)
                rows.append(dict(token=f'SYNTH-{i}',price=prices[i],liquidity=180000 if i<4 else 12000,
                    volume=20000,age_hours=30,observed=step*60-(180 if missing else 0),available=not missing,
                    exit_ok=not (i==2 and 35<=step<=42),synthetic=True))
            frames.append(dict(timestamp=step*60,rows=rows))
        return frames

class ScreeningAgent:
    def check(self,row,now,s):
        if not row['available'] or now-row['observed']>s.stale_seconds:return 'stale_or_missing'
        if not math.isfinite(row['price']) or row['price']<=0:return 'invalid_price'
        if row['liquidity']<s.min_liquidity:return 'low_liquidity'
        if row['age_hours']<24:return 'young_pool'
        return None

class StrategyAgent:
    version='liquidity-momentum-v1-unproven'
    def entry(self,history,s,baseline):
        if baseline:return len(history)>=6
        return len(history)>=6 and history[-1]/history[-6]-1 >= s.momentum
    def exit(self,p,row,step,s,baseline):
        change=row['price']/p['entry_price']-1
        return step-p['step']>=s.hold_steps or (not baseline and (change<=-s.stop_loss or change>=s.take_profit))

class RiskController:
    def __init__(self,s):self.s=s;self.halted=False
    def check(self,equity,exposure,count,cash):
        if equity<=self.s.capital*(1-self.s.max_loss):self.halted=True
        if self.halted:return 'loss_shutdown'
        if count>=self.s.max_positions:return 'position_limit'
        if exposure+self.s.ticket>self.s.capital*self.s.max_exposure+1e-9:return 'exposure_limit'
        if cash<self.s.ticket+self.s.network_cost:return 'finite_cash'
        return None

class PaperExecutionAgent:
    def buy(self,row,s):
        # Constant-product-inspired impact is an approximation, not an executable quote.
        impact=s.ticket/max(row['liquidity']/2,1)
        price=row['price']*(1+(s.fee_bps+s.slippage_bps)/10000+impact)
        return s.ticket/price,price
    def sell_value(self,p,row,s):
        gross=p['units']*row['price'];impact=gross/max(row['liquidity']/2,1)
        return max(0,gross*(1-(s.fee_bps+s.slippage_bps)/10000-impact)-s.network_cost)

class ReviewAgent:
    def run(self,frames,s,baseline=False,advisor=None):
        screen=ScreeningAgent();strategy=StrategyAgent();risk=RiskController(s);execution=PaperExecutionAgent()
        cash=s.capital;positions={};hist={};pending=[];events=[];curve=[];peak=s.capital;drawdown=0;cost=0;trades=0;ai_cost=0
        def log(step,role,token,action,reason,**kw):events.append(dict(timestamp=frames[step]['timestamp'],step=step,agent=role,token=token,action=action,reason=reason,**kw))
        for step,frame in enumerate(frames):
            now=frame['timestamp'];rows={r['token']:r for r in frame['rows']}
            charge=min(max(cash,0),s.operating_cost_step);cash-=charge;cost+=charge
            if charge<s.operating_cost_step:risk.halted=True;log(step,'risk','*','stop','operating_budget_exhausted')
            # Conservative liquidation marks: unavailable positions valued at zero, retained for exit retries.
            def mark():return sum(execution.sell_value(p,rows[t],s) if t in rows and not screen.check(rows[t],now,s) and rows[t]['exit_ok'] else 0 for t,p in positions.items())
            equity=cash+mark();risk.check(equity,sum(p['cost'] for p in positions.values()),len(positions),cash)
            approvals=None;ai_exits=set()
            if advisor:
                approvals,ai_exits=advisor.assess(step,frame,hist,positions,s,cash,risk.halted)
                charge=min(cash,advisor.consume_cost());cash-=charge;ai_cost+=charge
                risk.check(cash+mark(),sum(p['cost'] for p in positions.values()),len(positions),cash)
                if advisor.cancelled:risk.halted=True
            for t,p in list(positions.items()):
                r=rows.get(t)
                if r is None or screen.check(r,now,s) or not r['exit_ok']:
                    log(step,'execution',t,'failed_exit','unavailable_or_stale_route');continue
                if (risk.halted or t in ai_exits or strategy.exit(p,r,step,s,baseline)) and 'exit_due' not in p:
                    p['exit_due']=step+s.latency_steps
                    log(step,'strategy',t,'exit_signal','shutdown' if risk.halted else ('ai_requested_exit' if t in ai_exits else 'strategy_exit'))
                if 'exit_due' in p and step>=p['exit_due']:
                    proceeds=execution.sell_value(p,r,s);cash+=proceeds;trades+=1
                    log(step,'execution',t,'sell','shutdown' if risk.halted else 'strategy_exit',net_proceeds=proceeds,net_trade_pnl=proceeds-p['cost']-s.network_cost);del positions[t]
            for due,t in list(pending):
                if due>step:continue
                pending.remove((due,t));r=rows.get(t)
                reason='missing' if r is None else screen.check(r,now,s)
                reason=reason or risk.check(cash+mark(),sum(p['cost'] for p in positions.values()),len(positions),cash)
                if t in positions:reason='already_held'
                if advisor and (advisor.cancelled or advisor.error or t not in approvals):reason='ai_approval_absent'
                if reason:log(step,'risk',t,'reject',reason);continue
                units,price=execution.buy(r,s);cash-=s.ticket+s.network_cost
                positions[t]=dict(units=units,entry_price=price,step=step,cost=s.ticket)
                log(step,'execution',t,'buy','delayed_modeled_fill',units=units,price=price)
            fresh=False
            for t,r in rows.items():
                reason=screen.check(r,now,s);log(step,'screening',t,'reject' if reason else 'candidate',reason or 'liquidity_pass')
                if reason:hist[t]=[];continue
                fresh=True;hist.setdefault(t,[]).append(r['price'])
                if t not in positions and not any(x[1]==t for x in pending) and strategy.entry(hist[t],s,baseline):
                    if advisor and t not in approvals:log(step,'ai_team',t,'reject','no_unanimous_current_approval');continue
                    if not risk.halted:pending.append((step+s.latency_steps,t));log(step,'strategy',t,'signal','baseline_hold' if baseline else 'past_5_step_momentum')
            if not fresh:log(step,'risk','*','stop','all_data_stale');pending=[]
            equity=cash+mark();peak=max(peak,equity);drawdown=max(drawdown,(peak-equity)/peak)
            curve.append(dict(timestamp=now,equity=equity,exposure=sum(p['cost'] for p in positions.values())))
        return dict(net_pnl=curve[-1]['equity']-s.capital,equity=curve[-1]['equity'],cash=cash,drawdown=drawdown,positions=positions,exposure=curve[-1]['exposure'],halted=risk.halted,closed_trades=trades,operating_cost=cost,ai_cost_estimate=ai_cost,curve=curve,events=events,
            valuation='Conservative modeled liquidation; unavailable exits marked zero. Open positions retained.',synthetic=True)


class HistoricalReplay:
    """Deterministic point-in-time replay over stored observation frames."""
    def __init__(self, settings):
        self.settings = settings.validate()

    def split(self, frames, development_fraction=0.7, embargo_steps=0):
        ordered = sorted(frames, key=lambda x: x["timestamp"])
        if not ordered:
            raise ValueError("Cannot split empty history")
        if not 0.5 <= development_fraction < 1:
            raise ValueError("development_fraction must be between 0.5 and 1")
        if embargo_steps < 0 or int(embargo_steps) != embargo_steps:
            raise ValueError("embargo_steps must be a non-negative integer")
        cut = max(1, min(len(ordered) - 1, int(len(ordered) * development_fraction)))
        eval_start = min(len(ordered), cut + int(embargo_steps))
        if eval_start >= len(ordered):
            raise ValueError("Embargo removes the entire evaluation partition")
        return {
            "development": ordered[:cut],
            "embargo": ordered[cut:eval_start],
            "evaluation": ordered[eval_start:],
            "contract": "Evaluation is held out and cannot be passed to parameter-selection code."
        }

    def run(self, frames, start=None, end=None, embargo_steps=0, baseline=False):
        if not frames:
            raise ValueError("Replay requires at least one frame")
        ordered = sorted(frames, key=lambda x: x["timestamp"])
        if any(ordered[i]["timestamp"] > ordered[i+1]["timestamp"] for i in range(len(ordered)-1)):
            raise ValueError("Frames must be chronologically ordered")
        selected = ordered[start:end] if start is not None or end is not None else ordered
        if not selected:
            raise ValueError("Replay window is empty")
        if embargo_steps < 0 or int(embargo_steps) != embargo_steps:
            raise ValueError("embargo_steps must be a non-negative integer")
        # A replay window may be explicitly partitioned into development/evaluation.
        # Evaluation begins only after the embargo gap; evaluation frames are never fed
        # back into parameter selection by this class.
        if start is not None and start < 0 or end is not None and end < 0:
            raise ValueError("Replay slices must use non-negative bounds")
        if start is not None and end is not None and end < start:
            raise ValueError("Replay end must not precede start")
        # Replay only consumes observations present at each timestamp. No future frame is exposed.
        replay = ReviewAgent().run([{"timestamp": f["timestamp"], "rows": [dict(r) for r in f["rows"]]}
                                    for f in selected], self.settings, baseline=baseline)
        replay["replay"] = {
            "frames": len(selected),
            "start_timestamp": selected[0]["timestamp"],
            "end_timestamp": selected[-1]["timestamp"],
            "embargo_steps": int(embargo_steps),
            "no_lookahead": True,
            "deterministic": True,
            "baseline": baseline,
        }
        return replay

def run_demo(s,partition):
    s.validate()
    if partition not in ('development','evaluation'):raise ValueError('Unknown partition')
    frames=Scanner.synthetic(partition)
    return dict(strategy=ReviewAgent().run(frames,s),baseline=ReviewAgent().run(frames,s,True),hypothesis=StrategyAgent.version,partition=partition,settings=asdict(s),observations=frames)

def get_json(url,headers=None):
    req=urllib.request.Request(url,headers=headers or {})
    with urllib.request.urlopen(req,timeout=12) as response:return json.load(response)

class LiveObserver:
    """Read-only watchlist observation. No conversion into research fills."""
    USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
    def observe(self,mint,amount=10000000):
        if not 32<=len(mint)<=44 or any(c not in '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz' for c in mint):raise ValueError('Invalid Solana mint')
        received=time.time();pairs=get_json('https://api.dexscreener.com/token-pairs/v1/solana/'+mint)
        return dict(received=received,chain='solana',mint=mint,pairs=pairs,quote_status='Not requested; use quote CLI with optional Jupiter API key',warning='Fetch timestamp is not source freshness; pool data cannot prove token safety or executability.')
    def quote(self,mint,amount,key):
        params=urllib.parse.urlencode(dict(inputMint=self.USDC,outputMint=mint,amount=amount,slippageBps=50))
        buy=get_json('https://api.jup.ag/swap/v1/quote?'+params,{'x-api-key':key})
        params=urllib.parse.urlencode(dict(inputMint=mint,outputMint=self.USDC,amount=int(buy['outAmount']),slippageBps=50))
        sell=get_json('https://api.jup.ag/swap/v1/quote?'+params,{'x-api-key':key})
        return dict(received=time.time(),buy=buy,sell=sell,warning='Indicative GET quotes only, not guaranteed fills. V1 is deprecated; errors fail closed. No transactions built.')
