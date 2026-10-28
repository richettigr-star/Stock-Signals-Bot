from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

import donchian_v2_repo_inspired_exact as d

OUT=Path('donchian_v2_final_robustness_output');OUT.mkdir(exist_ok=True)
SEED=20261028
SIMS=10000
BLOCK=10


def moving_block_bootstrap(t,a,b):
    et=pd.to_datetime(t.entry_time,utc=True)
    z=t[(et>=a)&(et<b)].copy().sort_values(['exit_time','entry_time'])
    r=(z.raw_ret+z.funding_ret-d.BASE_COST).to_numpy(float)
    n=len(r)
    rng=np.random.default_rng(SEED)
    finals=np.empty(SIMS);dds=np.empty(SIMS)
    max_start=max(n-BLOCK,0)
    for s in range(SIMS):
        vals=[]
        while len(vals)<n:
            st=int(rng.integers(0,max_start+1)) if max_start>0 else 0
            vals.extend(r[st:min(st+BLOCK,n)].tolist())
        rr=np.asarray(vals[:n],float)
        curve=np.cumprod(1.0+d.ALLOC*rr)
        peak=np.maximum.accumulate(curve)
        finals[s]=(curve[-1]-1.0)*100
        dds[s]=np.min(curve/peak-1.0)*100
    return {
        'trades':n,
        'simulations':SIMS,
        'block_trades':BLOCK,
        'final_return_median':float(np.median(finals)),
        'final_return_p05':float(np.percentile(finals,5)),
        'final_return_p95':float(np.percentile(finals,95)),
        'max_dd_median':float(np.median(dds)),
        'max_dd_p05':float(np.percentile(dds,5)),
        'max_dd_p95':float(np.percentile(dds,95)),
        'prob_positive_return_pct':float(np.mean(finals>0)*100),
        'prob_dd_worse_20_pct':float(np.mean(dds<-20)*100),
        'prob_dd_worse_30_pct':float(np.mean(dds<-30)*100),
    }


def main():
    variants=[d.V('BASE_V1',atrbuf=0.0),d.V('ATRBUF_025',atrbuf=0.25)]
    pools={v.name:[] for v in variants};meta={}
    raw_map={};fund_map={};daily_map={}
    for sym in d.SYMS:
        print('LOAD',sym,flush=True)
        raw,km=d.loadbars(sym);f,fm=d.loadfund(sym)
        raw_map[sym]=raw;fund_map[sym]=f;daily_map[sym]=d.full_daily_features(raw) if not raw.empty else pd.DataFrame()
        meta[sym]={'bars1h':len(raw),'first':str(raw.index.min()) if len(raw) else None,'last':str(raw.index.max()) if len(raw) else None,'fund_rows':len(f),'kline_missing':km,'funding_missing':fm}
    btc=daily_map['BTCUSDT'];bull=(btc.ema20>btc.ema50).fillna(False);bear=(btc.ema20<btc.ema50).fillna(False)
    for sym in d.SYMS:
        raw=raw_map[sym]
        if raw.empty:continue
        segs=[d.prep_segment(raw,fund_map[sym],d.EVAL_START,d.DEV_START,daily_map[sym]),d.prep_segment(raw,fund_map[sym],d.DEV_START,d.END,daily_map[sym])]
        for seg_no,x in enumerate(segs):
            if seg_no==0 and len(x)<250:continue
            for v in variants:
                t=d.simulate(sym,x,fund_map[sym],v,bull,bear)
                if not t.empty:pools[v.name].append(t)

    allmap={k:(pd.concat(v,ignore_index=True) if v else pd.DataFrame()) for k,v in pools.items()}
    windows=[]
    for y in range(2020,2027):
        for half in (1,2):
            aa=pd.Timestamp(f'{y}-01-01' if half==1 else f'{y}-07-01',tz='UTC')
            bb=pd.Timestamp(f'{y}-07-01' if half==1 else f'{y+1}-01-01',tz='UTC')
            aa=max(aa,d.EVAL_START);bb=min(bb,d.END)
            if aa>=bb:continue
            label=f'{y}H{half}' + ('_partial' if bb< pd.Timestamp(f'{y+1}-01-01',tz='UTC') and half==2 else '')
            for name,t in allmap.items():windows.append({'window':label,'variant':name,'start':aa,'end':bb,**d.metrics(t,aa,bb)})
    w=pd.DataFrame(windows)
    pivot=w.pivot(index='window',columns='variant',values='pf')
    comparison=[]
    for win,row in pivot.iterrows():
        b=row.get('BASE_V1');c=row.get('ATRBUF_025')
        comparison.append({'window':win,'base_pf':b,'candidate_pf':c,'candidate_better':bool(pd.notna(b) and pd.notna(c) and c>b),'candidate_pf_gt1':bool(pd.notna(c) and c>1)})
    comp=pd.DataFrame(comparison)
    summary={'windows':len(comp),'candidate_better_windows':int(comp.candidate_better.sum()),'candidate_pf_gt1_windows':int(comp.candidate_pf_gt1.sum()),
             'base_pf_gt1_windows':int((comp.base_pf>1).sum())}

    mc={}
    for name,t in allmap.items():
        print('MONTE CARLO',name,flush=True)
        mc[name]=moving_block_bootstrap(t,d.DEV_START,d.END)

    w.to_csv(OUT/'halfyear_metrics.csv',index=False);comp.to_csv(OUT/'halfyear_comparison.csv',index=False)
    (OUT/'halfyear_summary.json').write_text(json.dumps(summary,indent=2));(OUT/'monte_carlo.json').write_text(json.dumps(mc,indent=2));(OUT/'meta.json').write_text(json.dumps(meta,indent=2))
    print('\nHALF-YEAR COMPARISON');print(comp.to_string(index=False));print('\nHALF-YEAR SUMMARY');print(json.dumps(summary,indent=2));print('\nMONTE CARLO');print(json.dumps(mc,indent=2))

if __name__=='__main__':main()
