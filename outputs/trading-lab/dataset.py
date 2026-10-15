"""Reproducible historical FX dataset pipeline.

Downloads pinned-provider daily reference rates, validates ordering/duplicates,
and writes a manifest plus per-pair JSON datasets. No trading/execution occurs.
"""
import datetime,json,os
from historical import load_pairs,save_json

def validate(candles):
    if not candles:return {"rows":0,"duplicates":0,"non_monotonic":0,"gaps":0,"max_gap_days":0}
    timestamps=[c.timestamp for c in candles]
    duplicates=len(timestamps)-len(set(timestamps))
    non_monotonic=sum(b<=a for a,b in zip(timestamps,timestamps[1:]))
    gaps=[(b-a)/86400 for a,b in zip(timestamps,timestamps[1:]) if b>a]
    large=[g for g in gaps if g>4]
    return {"rows":len(candles),"duplicates":duplicates,"non_monotonic":non_monotonic,"gaps":len(large),"max_gap_days":max(large,default=0)}

def build_dataset(pairs,start_date,end_date,output_dir,provider="ecb"):
    if datetime.date.fromisoformat(start_date)>datetime.date.fromisoformat(end_date):
        raise ValueError("start_date must not be after end_date")
    os.makedirs(output_dir,exist_ok=True)
    datasets=load_pairs(pairs,start_date,end_date,provider)
    manifest={"provider":provider,"start_date":start_date,"end_date":end_date,"pairs":{}}
    for pair,candles in datasets.items():
        checks=validate(candles)
        if checks["duplicates"] or checks["non_monotonic"]:
            raise ValueError(f"Invalid ordering/duplicates for {pair}: {checks}")
        name=pair.replace("/","_")+".json"
        save_json(candles,os.path.join(output_dir,name))
        manifest["pairs"][pair]=checks|{"file":name}
    with open(os.path.join(output_dir,"manifest.json"),"w",encoding="utf-8") as f:
        json.dump(manifest,f,indent=2)
    return manifest
