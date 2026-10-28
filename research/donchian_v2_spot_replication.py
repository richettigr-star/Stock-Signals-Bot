from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

import donchian_v2_repo_inspired_exact as d

OUT=Path('donchian_v2_spot_replication_output'); OUT.mkdir(exist_ok=True)
KURL='https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip'


def _bar(sym,m):
    ym=m.strftime('%Y-%m')
    raw=d.getzip(KURL.format(sym=sym,ym=ym))
    if raw is None:return ym,None
    x=pd.read_csv(io.BytesIO(raw),header=None)
    for c in range(6):x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=list(range(6)))
    if x.empty:return ym,None
    unit='us' if float(x.iloc[0,0])>=1e14 else 'ms'
    return ym,pd.DataFrame({'time':pd.to_datetime(x[0],unit=unit,utc=True,errors='coerce'),
                           'open':x[1],'high':x[2],'low':x[3],'close':x[4],'volume':x[5]}).dropna()


def load_spot(sym):
    ms=list(d.months(d.WARM_START,d.END)); pieces=[]; missing=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs=[ex.submit(_bar,sym,m) for m in ms]
        for f in as_completed(fs):
            ym,p=f.result()
            if p is None:missing.append(ym)
            else:pieces.append(p)
    if not pieces:return pd.DataFrame(),sorted(missing)
    x=pd.concat(pieces,ignore_index=True).drop_duplicates('time').sort_values('time')
    x=x[(x.time>=d.WARM_START)&(x.time<d.END)].set_index('time')
    return x[['open','high','low','close','volume']],sorted(missing)


def main():
    variants=[d.V('SPOT_BASE_V1',atrbuf=0.0),d.V('SPOT_ATRBUF_025',atrbuf=0.25)]
    pools={v.name:[] for v in variants}; meta={}
    emptyfund=pd.DataFrame(columns=['time','last_funding_rate'])
    dummy=pd.Series(dtype=bool)
    for sym in d.SYMS:
        print('LOAD',sym,flush=True)
        raw,missing=load_spot(sym)
        meta[sym]={'bars1h':len(raw),'first':str(raw.index.min()) if len(raw) else None,'last':str(raw.index.max()) if len(raw) else None,'missing':missing}
        if raw.empty:continue
        daily=d.full_daily_features(raw)
        segs=[d.prep_segment(raw,emptyfund,d.EVAL_START,d.DEV_START,daily),d.prep_segment(raw,emptyfund,d.DEV_START,d.END,daily)]
        for seg_no,x in enumerate(segs):
            if seg_no==0 and len(x)<250:continue
            for v in variants:
                t=d.simulate(sym,x,emptyfund,v,dummy,dummy)
                if not t.empty:pools[v.name].append(t)

    rows=[]; pair=[]; side=[]; yearly=[]
    for v in variants:
        t=pd.concat(pools[v.name],ignore_index=True) if pools[v.name] else pd.DataFrame()
        pre=d.metrics(t,d.EVAL_START,d.DEV_START); dev=d.metrics(t,d.DEV_START,d.DEV_END); val=d.metrics(t,d.DEV_END,d.VAL_END)
        test=d.metrics(t,d.VAL_END,d.END); stress=d.metrics(t,d.VAL_END,d.END,d.STRESS_COST); rm=d.metrics(t,d.VAL_END,d.END,d.BASE_COST,3)
        rows.append({'variant':v.name,'pre_trades':pre['trades'],'pre_pf':pre['pf'],'pre_ret':pre['ret'],
                     'dev_trades':dev['trades'],'dev_pf':dev['pf'],'dev_ret':dev['ret'],
                     'val_trades':val['trades'],'val_pf':val['pf'],'val_ret':val['ret'],
                     'test_trades':test['trades'],'test_pf':test['pf'],'test_ret':test['ret'],'test_dd':test['dd'],'test_tpw':test['tpw'],
                     'test_stress_pf':stress['pf'],'test_remove_top3_pf':rm['pf']})
        for y in range(2020,2027):
            aa=max(d.EVAL_START,pd.Timestamp(f'{y}-01-01',tz='UTC'));bb=min(d.END,pd.Timestamp(f'{y+1}-01-01',tz='UTC'))
            if aa<bb:yearly.append({'variant':v.name,'year':y,**d.metrics(t,aa,bb)})
        if not t.empty:
            for s in d.SYMS:pair.append({'variant':v.name,'symbol':s,**d.metrics(t[t.symbol==s],d.VAL_END,d.END)})
            for sd in ['LONG','SHORT']:side.append({'variant':v.name,'side':sd,**d.metrics(t[t.side==sd],d.VAL_END,d.END)})

    r=pd.DataFrame(rows); r.to_csv(OUT/'summary.csv',index=False);pd.DataFrame(pair).to_csv(OUT/'test_by_pair.csv',index=False);pd.DataFrame(side).to_csv(OUT/'test_by_side.csv',index=False);pd.DataFrame(yearly).to_csv(OUT/'yearly.csv',index=False);(OUT/'meta.json').write_text(json.dumps(meta,indent=2))
    print('\nSUMMARY');print(r.to_string(index=False));print('\nPAIR');print(pd.DataFrame(pair).to_string(index=False));print('\nSIDE');print(pd.DataFrame(side).to_string(index=False));print('\nYEARLY');print(pd.DataFrame(yearly).to_string(index=False))

if __name__=='__main__':main()
