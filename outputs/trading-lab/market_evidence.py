"""Provider-reported activity evidence and conservative cost-hurdle policies."""
import math
POLICY={'min_volume_m5':1000,'min_transactions_m5':20,'max_volume_liquidity_m5':1,'max_liquidity_drop':.1,'assumed_upside':.08,'uncertainty_margin':.02,'cost_multiplier':2}
def number(v):
    if isinstance(v,bool):return None
    try:v=float(v)
    except (ValueError,TypeError):return None
    return v if math.isfinite(v) and v>=0 else None
def evidence(pair,now):
    tx=pair.get('txns',{}).get('m5',{}) or {};volume=number((pair.get('volume') or {}).get('m5'));buys=number(tx.get('buys'));sells=number(tx.get('sells'));liq=number((pair.get('liquidity') or {}).get('usd'));count=None if buys is None or sells is None else buys+sells
    return {'received_at':now,'source':'DEX Screener','source_timestamp':None,'volume_m5_usd':volume,'buys_m5':buys,'sells_m5':sells,'transactions_m5':count,'volume_liquidity_ratio':volume/liq if volume is not None and liq else None,'average_transaction_usd':volume/count if volume is not None and count else None,'wash_trading_verified':False,'unique_traders':None,'holder_transactions':None,'limitations':'Activity totals are provider-reported; unique traders, wash trades and holder transactions are unverified.'}
def assess(row,history,now):
    e=row.get('activity',{});reasons=[]
    if now-row['observed']>90 or now<row['observed']:reasons.append('stale_activity')
    if any(e.get(k) is None for k in ('volume_m5_usd','transactions_m5','volume_liquidity_ratio')):reasons.append('activity_evidence_missing')
    else:
        if e['volume_m5_usd']<POLICY['min_volume_m5']:reasons.append('insufficient_activity_volume')
        if e['transactions_m5']<POLICY['min_transactions_m5']:reasons.append('insufficient_transactions')
        if e['volume_liquidity_ratio']>POLICY['max_volume_liquidity_m5']:reasons.append('volume_quality_outlier')
    prior=next((p for p in history if p.get('liquidity') and p.get('pair')==row['pair']),None);drop=None
    if prior:
        drop=1-row['liquidity']/prior['liquidity']
        if drop>=POLICY['max_liquidity_drop']:reasons.append('liquidity_deterioration')
    return {'allowed':not reasons,'reasons':reasons,'liquidity_change_pct':None if drop is None else -drop*100,'activity':e,'policy':POLICY}
def cost_hurdle(conservative_output_usd,network_cost=0,upside=.08):
    cost=max(0,1-conservative_output_usd/10)+network_cost*2/10;required=cost*POLICY['cost_multiplier']+POLICY['uncertainty_margin']
    return {'allowed':upside>required,'roundtrip_cost_fraction':cost,'assumed_upside_fraction':upside,'required_upside_fraction':required,'basis':'Take-profit target is an assumption, not an estimated probability or forecast.'}
