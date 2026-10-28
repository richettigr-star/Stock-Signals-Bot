from __future__ import annotations
import io, requests, pandas as pd, numpy as np
from pathlib import Path
import donchian_v2_repo_inspired_exact as eng

END=pd.Timestamp('2026-10-28 16:00:00',tz='UTC')
OCT=pd.Timestamp('2026-10-01',tz='UTC')
eng.END=END
SYMS=eng.SYMS
BASE_COST=eng.BASE_COST

# Extend audited monthly dataset with closed October hourly bars/funding from Binance USD-M REST.
def rest_bars(sym):
    st=int(OCT.timestamp()*1000); en=int(END.timestamp()*1000)-1
    url='https://fapi.binance.com/fapi/v1/klines'
    r=requests.get(url,params={'symbol':sym,'interval':'1h','startTime':st,'endTime':en,'limit':1500},timeout=30); r.raise_for_status()
    a=r.json();
    if not a: return pd.DataFrame(columns=['open','high','low','close','volume'])
    d=pd.DataFrame(a)
    x=pd.DataFrame({'time':pd.to_datetime(d[0].astype('int64'),unit='ms',utc=True),'open':d[1].astype(float),'high':d[2].astype(float),'low':d[3].astype(float),'close':d[4].astype(float),'volume':d[5].astype(float)})
    return x.set_index('time')

def rest_fund(sym):
    st=int(OCT.timestamp()*1000); en=int(END.timestamp()*1000)-1
    url='https://fapi.binance.com/fapi/v1/fundingRate'
    r=requests.get(url,params={'symbol':sym,'startTime':st,'endTime':en,'limit':1000},timeout=30); r.raise_for_status()
    a=r.json();
    if not a: return pd.DataFrame(columns=['time','last_funding_rate'])
    return pd.DataFrame({'time':pd.to_datetime([int(x['fundingTime']) for x in a],unit='ms',utc=True),'last_funding_rate':[float(x['fundingRate']) for x in a]})

raw_map={}; fund_map={}; daily_map={}
for sym in SYMS:
    print('LOAD',sym,flush=True)
    raw,_=eng.loadbars(sym); f,_=eng.loadfund(sym)
    rb=rest_bars(sym); rf=rest_fund(sym)
    raw=pd.concat([raw,rb]).sort_index(); raw=raw[~raw.index.duplicated(keep='last')]; raw=raw[raw.index<END]
    f=pd.concat([f,rf],ignore_index=True).drop_duplicates('time').sort_values('time'); f=f[f.time<END]
    raw_map[sym]=raw; fund_map[sym]=f; daily_map[sym]=eng.full_daily_features(raw)

v=eng.V('ATRBUF_025',atrbuf=0.25)
pools=[]
for sym in SYMS:
    x=eng.prep_segment(raw_map[sym],fund_map[sym],eng.DEV_START,END,daily_map[sym])
    t=eng.simulate(sym,x,fund_map[sym],v,pd.Series(dtype=bool),pd.Series(dtype=bool))
    if not t.empty: pools.append(t)
t=pd.concat(pools,ignore_index=True) if pools else pd.DataFrame()
if t.empty:
    raise SystemExit('no trades')
t['entry_time']=pd.to_datetime(t.entry_time,utc=True); t['exit_time']=pd.to_datetime(t.exit_time,utc=True)
t=t[(t.entry_time>=OCT)&(t.entry_time<END)].copy(); t['net']=t.raw_ret+t.funding_ret-BASE_COST
print('OCT CLOSED TRADES',len(t),'first',t.entry_time.min(),'last',t.entry_time.max())

configs=[
('SAFE12P5',0.125,1,8,1.0),('BAL15',0.075,2,8,1.5),('MID17P5',0.0875,2,8,1.5),('AGG20_CAP150',0.10,2,8,1.5),('AGG22P5_CAP175',0.1125,2,8,1.75),('AGG25_FULL',0.125,2,8,2.0)]

def sim(z,m,lev,mp,gcap):
    z=z.sort_values(['entry_time','symbol']).reset_index(drop=True)
    ev=[]
    for i,r in z.iterrows(): ev += [(r.exit_time,0,i),(r.entry_time,1,i)]
    ev.sort(key=lambda x:(x[0],x[1]))
    eq=100.; peak=100.; dd=0.; act={}; acc=skip=0
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
rows=[]
for cfg,m,l,mp,g in configs:
    rows.append({'config':cfg,**sim(t,m,l,mp,g)})
out=pd.DataFrame(rows); out.to_csv('donchian_v2_october_forward.csv',index=False)
print(out.to_string(index=False))
print('\nBY PAIR CLOSED OCT')
if len(t):
    print(t.groupby('symbol').agg(trades=('net','size'),mean_net=('net','mean'),sum_net=('net','sum')).sort_values('sum_net',ascending=False).to_string())
