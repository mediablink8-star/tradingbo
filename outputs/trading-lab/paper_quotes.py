"""Read-only USDC-denominated paper quotes. Never builds or submits transactions."""
import math,time
import swaps
from market_evidence import cost_hurdle
from engine import PaperExecutionAgent

class QuoteExecution:
    mode='conservative_jupiter_quote_paper'
    def __init__(self,events,network_cost=0,quote=swaps.quote,rpc=swaps.rpc,clock=time.time):
        self.events=events;self.quote=quote;self.rpc=rpc;self.clock=clock;self.cache={};self.decimals={};self.last_fill={};self.network_cost=network_cost
    def mint_decimals(self,token):
        if token not in self.decimals:
            a=self.rpc('getAccountInfo',[token,{'encoding':'jsonParsed','commitment':'confirmed'}])['value']
            info=a['data']['parsed']['info'];d=info['decimals']
            if a['owner']!=swaps.TOKEN or a['data']['parsed']['type']!='mint' or not info['isInitialized'] or type(d)!=int or not 0<=d<=12:raise ValueError('Unsupported mint')
            self.decimals[token]=d
        return self.decimals[token]
    def route(self,a,b,amount):
        key=(a,b,amount);now=self.clock();cached=self.cache.get(key)
        if cached and now-cached[0]<=15:return cached[1]
        q=self.quote(a,b,amount);received=self.clock()
        if received-now>15:raise ValueError('Quote request too slow')
        # Validate independently, including injected adapters used by tests.
        if q.get('inputMint')!=a or q.get('outputMint')!=b or str(q.get('inAmount'))!=str(amount) or q.get('swapMode')!='ExactIn' or q.get('slippageBps')!=50:raise ValueError('Quote mismatch')
        threshold=int(q['otherAmountThreshold']);out=int(q['outAmount']);impact=float(q['priceImpactPct'])
        if not 0<threshold<=out or not math.isfinite(impact) or not 0<=impact<=.01 or not q.get('routePlan'):raise ValueError('Unacceptable quote')
        self.cache[key]=(received,q)
        self.events.append({'kind':'paper_quote','timestamp':received,'input_mint':a,'output_mint':b,'amount':amount,'quote':q,'source':'Jupiter','paper_only':True})
        return q
    def buy(self,row,s):
        token=row['token'];d=self.mint_decimals(token);q=self.route(swaps.USDC,token,10_000_000)
        if len(q['routePlan'])!=1 or q['routePlan'][0].get('swapInfo',{}).get('ammKey')!=row['pair']:raise ValueError('Route differs from screened pool')
        raw=int(q['otherAmountThreshold']);reverse=self.route(token,swaps.USDC,raw)
        if int(reverse['otherAmountThreshold'])<9_700_000:raise ValueError('Conservative round-trip loss exceeds 3%')
        hurdle=cost_hurdle(int(reverse['otherAmountThreshold'])/1_000_000,self.network_cost,s.take_profit)
        if not hurdle['allowed']:raise ValueError('Assumed upside does not comfortably cover round-trip cost and uncertainty')
        units=raw/(10**d)
        if not math.isfinite(units) or units<=0:raise ValueError('Invalid quoted units')
        self.last_fill={"base_units":raw,"decimals":d,"trade_quality":hurdle}
        return units,10/units
    def sell_value(self,p,row,s):
        # Old positions retain their original snapshot valuation semantics until closed.
        if p.get('fill_mode')!=self.mode:return PaperExecutionAgent().sell_value(p,row,s)
        d=self.mint_decimals(row['token']);raw=p.get('base_units',int(p['units']*10**d))
        if raw<=0:raise ValueError('Dust position')
        q=self.route(row['token'],swaps.USDC,raw)
        return max(0,int(q['otherAmountThreshold'])/1_000_000-self.network_cost)

def usage_cost(usage,rates):
    """Estimate from reported usage + explicitly configured rates, never an invoice."""
    if not isinstance(usage,dict) or not isinstance(rates,dict):return None
    details=usage.get('input_tokens_details',{})
    if not isinstance(details,dict):return None
    incoming=usage.get('input_tokens');outgoing=usage.get('output_tokens');cached=details.get('cached_tokens',0)
    if any(type(v)!=int or v<0 for v in (incoming,outgoing,cached)) or cached>incoming:return None
    prices=[rates.get(k) for k in ('input','cached','output')]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in prices):return None
    return ((incoming-cached)*prices[0]+cached*prices[1]+outgoing*prices[2])/1_000_000
