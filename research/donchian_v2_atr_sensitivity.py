from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

import donchian_v2_repo_inspired_exact as d

OUT = Path('donchian_v2_atr_sensitivity_output')
OUT.mkdir(exist_ok=True)
THRESHOLDS = [0.00, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75]


def name_for(x):
    return 'ATRBUF_' + str(int(round(x * 100))).zfill(2)


def summarize_subset(z):
    if z.empty:
        return {'trades':0,'wr':None,'pf':None,'mean_net_pct':None,'sum_net_pct':0.0}
    z=z.copy(); z['net']=z.raw_ret+z.funding_ret-d.BASE_COST
    gp=z.loc[z.net>0,'net'].sum(); gl=-z.loc[z.net<0,'net'].sum()
    return {'trades':len(z),'wr':float((z.net>0).mean()*100),'pf':float(gp/gl) if gl>0 else None,
            'mean_net_pct':float(z.net.mean()*100),'sum_net_pct':float(z.net.sum()*100)}


def window(t,a,b):
    et=pd.to_datetime(t.entry_time,utc=True)
    return t[(et>=a)&(et<b)].copy()


def main():
    raw_map={}; fund_map={}; daily_map={}; meta={}
    for sym in d.SYMS:
        print('LOAD',sym,flush=True)
        raw,km=d.loadbars(sym); f,fm=d.loadfund(sym)
        raw_map[sym]=raw; fund_map[sym]=f; daily_map[sym]=d.full_daily_features(raw) if not raw.empty else pd.DataFrame()
        meta[sym]={'bars1h':len(raw),'first':str(raw.index.min()) if len(raw) else None,'last':str(raw.index.max()) if len(raw) else None,
                   'fund_rows':len(f),'kline_missing':km,'funding_missing':fm}

    btc_daily=daily_map['BTCUSDT']; btc_bull=(btc_daily.ema20>btc_daily.ema50).fillna(False); btc_bear=(btc_daily.ema20<btc_daily.ema50).fillna(False)
    variants=[d.V(name_for(x),atrbuf=x) for x in THRESHOLDS]
    pools={v.name:[] for v in variants}

    for sym in d.SYMS:
        raw=raw_map[sym]
        if raw.empty: continue
        segs=[d.prep_segment(raw,fund_map[sym],d.EVAL_START,d.DEV_START,daily_map[sym]),
              d.prep_segment(raw,fund_map[sym],d.DEV_START,d.END,daily_map[sym])]
        for seg_no,x in enumerate(segs):
            if seg_no==0 and len(x)<250: continue
            for v in variants:
                t=d.simulate(sym,x,fund_map[sym],v,btc_bull,btc_bear)
                if not t.empty: pools[v.name].append(t)

    rows=[]; yearly=[]; pair=[]; side=[]; exits=[]
    allmap={}
    for v in variants:
        t=pd.concat(pools[v.name],ignore_index=True) if pools[v.name] else pd.DataFrame()
        allmap[v.name]=t
        pre=d.metrics(t,d.EVAL_START,d.DEV_START); dev=d.metrics(t,d.DEV_START,d.DEV_END); val=d.metrics(t,d.DEV_END,d.VAL_END)
        test=d.metrics(t,d.VAL_END,d.END); stress=d.metrics(t,d.VAL_END,d.END,d.STRESS_COST); rm=d.metrics(t,d.VAL_END,d.END,d.BASE_COST,3)
        yr={}
        for y in range(2020,2027):
            aa=max(d.EVAL_START,pd.Timestamp(f'{y}-01-01',tz='UTC')); bb=min(d.END,pd.Timestamp(f'{y+1}-01-01',tz='UTC'))
            if aa<bb:
                m=d.metrics(t,aa,bb); yr[y]=m; yearly.append({'variant':v.name,'threshold':v.atrbuf,'year':y,**m})
        rows.append({'variant':v.name,'threshold':v.atrbuf,
                     'pre_trades':pre['trades'],'pre_pf':pre['pf'],'dev_trades':dev['trades'],'dev_pf':dev['pf'],'dev_ret':dev['ret'],
                     'val_trades':val['trades'],'val_pf':val['pf'],'val_ret':val['ret'],'test_trades':test['trades'],'test_pf':test['pf'],
                     'test_ret':test['ret'],'test_dd':test['dd'],'test_tpw':test['tpw'],'test_stress_pf':stress['pf'],'test_remove_top3_pf':rm['pf'],
                     'pf_2022':yr.get(2022,{}).get('pf'),'pf_2025':yr.get(2025,{}).get('pf')})
        if v.atrbuf in (0.0,0.25) and not t.empty:
            tz=window(t,d.VAL_END,d.END)
            for s in d.SYMS: pair.append({'variant':v.name,'symbol':s,**d.metrics(t[t.symbol==s],d.VAL_END,d.END)})
            for sd in ['LONG','SHORT']: side.append({'variant':v.name,'side':sd,**d.metrics(t[t.side==sd],d.VAL_END,d.END)})
            for reason,g in tz.groupby('reason'):
                q=summarize_subset(g); exits.append({'variant':v.name,'reason':reason,**q})

    rank=pd.DataFrame(rows).sort_values('threshold'); rank.to_csv(OUT/'sensitivity.csv',index=False)
    pd.DataFrame(yearly).to_csv(OUT/'yearly.csv',index=False); pd.DataFrame(pair).to_csv(OUT/'pair_baseline_vs_025.csv',index=False)
    pd.DataFrame(side).to_csv(OUT/'side_baseline_vs_025.csv',index=False); pd.DataFrame(exits).to_csv(OUT/'exit_reasons.csv',index=False)

    # Entry-set diagnostic for locked comparison. Filtering one trade can free the symbol for a later signal,
    # so both baseline-only and candidate-only entries are reported rather than pretending the candidate is a strict subset.
    b=window(allmap[name_for(0.0)],d.VAL_END,d.END); c=window(allmap[name_for(0.25)],d.VAL_END,d.END)
    key=['symbol','side','entry_time']
    bk=set(map(tuple,b[key].astype(str).to_records(index=False))); ck=set(map(tuple,c[key].astype(str).to_records(index=False)))
    def mask_keys(df,ks):
        vals=list(map(tuple,df[key].astype(str).to_records(index=False)))
        return df[[v in ks for v in vals]].copy()
    common=bk&ck; bonly=bk-ck; conly=ck-bk
    diag={'common':summarize_subset(mask_keys(b,common)),
          'baseline_only':summarize_subset(mask_keys(b,bonly)),
          'candidate_only':summarize_subset(mask_keys(c,conly))}
    (OUT/'entry_set_diagnostic.json').write_text(json.dumps(diag,indent=2))
    (OUT/'meta.json').write_text(json.dumps(meta,indent=2))

    print('\nSENSITIVITY')
    print(rank.to_string(index=False))
    print('\nPAIR BASELINE VS 0.25')
    print(pd.DataFrame(pair).to_string(index=False))
    print('\nSIDE BASELINE VS 0.25')
    print(pd.DataFrame(side).to_string(index=False))
    print('\nEXIT REASONS')
    print(pd.DataFrame(exits).to_string(index=False))
    print('\nENTRY SET DIAGNOSTIC')
    print(json.dumps(diag,indent=2))

if __name__=='__main__': main()
