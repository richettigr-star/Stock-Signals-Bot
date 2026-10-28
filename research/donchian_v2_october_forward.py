from __future__ import annotations
import io, zipfile, requests, pandas as pd, numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import donchian_v2_repo_inspired_exact as eng

END=pd.Timestamp('2026-10-28 00:00:00',tz='UTC')
OCT=pd.Timestamp('2026-10-01',tz='UTC')
eng.END=END
SYMS=eng.SYMS
BASE_COST=eng.BASE_COST
KDAY='https://data.binance.vision/data/futures/um/daily/klines/{sym}/1h/{sym}-1h-{day}.zip'
FDAY='https://data.binance.vision/data/futures/um/daily/fundingRate/{sym}/{sym}-fundingRate-{day}.zip'

def get_zip_csv(url):
    r=requests.get(url,timeout=30)
    if r.status_code==404: return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        n=next(x for x in z.namelist() if x.endswith('.csv'))
        return z.read(n)

def parse_bar(raw):
    if raw is None: return pd.DataFrame(columns=['open','high','low','close','volume'])
    d=pd.read_csv(io.BytesIO(raw),header=None)
    for c in range(6): d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.dropna(subset=list(range(6)))
    if d.empty: return pd.DataFrame(columns=['open','high','low','close','volume'])
    unit='us' if float(d.iloc[0,0])>=1e14 else 'ms'
    x=pd.DataFrame({'time':pd.to_datetime(d[0],unit=unit,utc=True,errors='coerce'),'open':d[1],'high':d[2],'low':d[3],'close':d[4],'volume':d[5]}).dropna()
    return x.set_index('time')[['open','high','low','close','volume']]

def parse_fund(raw):
    if raw is None: return pd.DataFrame(columns=['time','last_funding_rate'])
    d=pd.read_csv(io.BytesIO(raw)); d.columns=[str(c).strip().lower() for c in d.columns]
    if 'calc_time' in d.columns and 'last_funding_rate' in d.columns: tc,rc='calc_time','last_funding_rate'
    elif 'fundingtime' in d.columns and 'fundingrate' in d.columns: tc,rc='fundingtime','fundingrate'
    else:
        d=pd.read_csv(io.BytesIO(raw),header=None)
        if d.shape[1]<2: return pd.DataFrame(columns=['time','last_funding_rate'])
        d.columns=['calc_time','last_funding_rate']+list(d.columns[2:]); tc,rc='calc_time','last_funding_rate'
    d[tc]=pd.to_numeric(d[tc],errors='coerce'); d[rc]=pd.to_numeric(d[rc],errors='coerce'); d=d.dropna(subset=[tc,rc])
    if d.empty: return pd.DataFrame(columns=['time','last_funding_rate'])
    unit='us' if float(d.iloc[0][tc])>=1e14 else 'ms'
    return pd.DataFrame({'time':pd.to_datetime(d[tc],unit=unit,utc=True,errors='coerce'),'last_funding_rate':d[rc].astype(float)}).dropna()

def one_day(sym,d):
    day=d.strftime('%Y-%m-%d')
    return day,parse_bar(get_zip_csv(KDAY.format(sym=sym,day=day))),parse_fund(get_zip_csv(FDAY.format(sym=sym,day=day)))

def daily_oct(sym):
    dates=list(pd.date_range(OCT,END-pd.Timedelta(days=1),freq='1D',tz='UTC'))
    bars=[]; funds=[]
    with ThreadPoolExecutor(max_workers=16) as ex:
        fs=[ex.submit(one_day,sym,d) for d in dates]
        for future in as_completed(fs):
            _,b,fr=future.result()
            if not b.empty: bars.append(b)
            if not fr.empty: funds.append(fr)
    b=pd.concat(bars).sort_index() if bars else pd.DataFrame(columns=['open','high','low','close','volume'])
    f=pd.concat(funds,ignore_index=True).sort_values('time') if funds else pd.DataFrame(columns=['time','last_funding_rate'])
    return b,f

raw_map={}; fund_map={}; daily_map={}
for sym in SYMS:
    print('LOAD',sym,flush=True)
    raw,_=eng.loadbars(sym); f,_=eng.loadfund(sym); rb,rf=daily_oct(sym)
    print(' OCT',sym,'bars',len(rb),'daily_fund',len(rf),flush=True)
    raw=pd.concat([raw,rb]).sort_index(); raw=raw[~raw.index.duplicated(keep='last')]; raw=raw[raw.index<END]
    # Binance daily archive path currently has no funding files for October. Keep
    # official monthly funding through Sep and append daily rows only if present.
    if not rf.empty: f=pd.concat([f,rf],ignore_index=True)
    f=f.drop_duplicates('time').copy()
    f['time']=pd.to_datetime(f['time'],utc=True,errors='coerce')
    f=f.dropna(subset=['time']).sort_values('time'); f=f[f.time<END]
    raw_map[sym]=raw; fund_map[sym]=f; daily_map[sym]=eng.full_daily_features(raw)

v=eng.V('ATRBUF_025',atrbuf=0.25); pools=[]
for sym in SYMS:
    x=eng.prep_segment(raw_map[sym],fund_map[sym],eng.DEV_START,END,daily_map[sym])
    z=eng.simulate(sym,x,fund_map[sym],v,pd.Series(dtype=bool),pd.Series(dtype=bool))
    if not z.empty: pools.append(z)
t=pd.concat(pools,ignore_index=True) if pools else pd.DataFrame()
if t.empty: raise SystemExit('no trades')
t['entry_time']=pd.to_datetime(t.entry_time,utc=True); t['exit_time']=pd.to_datetime(t.exit_time,utc=True)
t=t[(t.entry_time>=OCT)&(t.entry_time<END)].copy(); t['net']=t.raw_ret+t.funding_ret-BASE_COST
print('OCT CLOSED TRADES',len(t),'first',t.entry_time.min(),'last',t.entry_time.max(),'funding_sum',float(t.funding_ret.sum()))
configs=[('SAFE12P5',0.125,1,8,1.0),('BAL15',0.075,2,8,1.5),('MID17P5',0.0875,2,8,1.5),('AGG20_CAP150',0.10,2,8,1.5),('AGG22P5_CAP175',0.1125,2,8,1.75),('AGG25_FULL',0.125,2,8,2.0)]

def sim(z,m,lev,mp,gcap):
    z=z.sort_values(['entry_time','symbol']).reset_index(drop=True); ev=[]
    for i,r in z.iterrows(): ev += [(r.exit_time,0,i),(r.entry_time,1,i)]
    ev.sort(key=lambda x:(x[0],x[1])); eq=100.; peak=100.; dd=0.; act={}; acc=skip=0
    for _,typ,i in ev:
        r=z.loc[i]
        if typ==0:
            p=act.pop(i,None)
            if p is None: continue
            eq += p[1]*float(r.net); peak=max(peak,eq); dd=min(dd,eq/peak-1)
        else:
            margin=m*eq; notional=margin*lev; rm=sum(v[0] for v in act.values()); rg=sum(v[1] for v in act.values())
            if len(act)>=mp or rm+margin>eq+1e-12 or rg+notional>gcap*eq+1e-12: skip+=1; continue
            act[i]=(margin,notional); acc+=1
    return {'eq':eq,'ret':(eq/100-1)*100,'dd':dd*100,'acc':acc,'skip':skip,'skip_pct':100*skip/max(1,acc+skip)}
rows=[{'config':cfg,**sim(t,m,l,mp,g)} for cfg,m,l,mp,g in configs]
out=pd.DataFrame(rows); out.to_csv('donchian_v2_october_forward.csv',index=False)
print(out.to_string(index=False)); print('\nBY PAIR CLOSED OCT')
if len(t): print(t.groupby('symbol').agg(trades=('net','size'),mean_net=('net','mean'),sum_net=('net','sum')).sort_values('sum_net',ascending=False).to_string())
