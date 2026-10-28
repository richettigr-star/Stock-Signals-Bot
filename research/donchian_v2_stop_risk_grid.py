from __future__ import annotations
import itertools, subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import donchian_v2_repo_inspired_exact as eng

END=pd.Timestamp('2026-10-01',tz='UTC')
RISK_BUDGETS=[0.005,0.0075,0.01,0.0125,0.015,0.02,0.025,0.03]
LEVS=[2,3,4,5,7,10]
HEAT_CAPS=[0.04,0.06,0.08,0.10,0.12,0.16]
GROSS_CAPS=[1.0,1.5,2.0,2.5,3.0,4.0]
MAX_POS=[4,6,8]
BASE_COST=eng.BASE_COST
PERIODS={'YTD_2026':('2026-01-01','2026-10-01'),'RECENT':('2025-01-01','2026-10-01'),'FULL':('2021-01-01','2026-10-01')}
PERIODS={k:(pd.Timestamp(a,tz='UTC'),pd.Timestamp(b,tz='UTC')) for k,(a,b) in PERIODS.items()}

# Load exact data and generate the same ATRBUF_025 entries, but retain entry stop distance.
raw_map={};fund_map={};daily_map={}
for sym in eng.SYMS:
    print('LOAD',sym,flush=True)
    raw,_=eng.loadbars(sym); f,_=eng.loadfund(sym)
    raw_map[sym]=raw;fund_map[sym]=f;daily_map[sym]=eng.full_daily_features(raw)

def gen(sym,x,f):
    eh=x.high.shift(1).rolling(40,min_periods=40).max(); el=x.low.shift(1).rolling(40,min_periods=40).min(); ap=x.atr.shift(1)
    long=((x.close>eh+0.25*ap)&(x.close>x.ema200)).fillna(False).to_numpy(bool)
    short=((x.close<el-0.25*ap)&(x.close<x.ema200)).fillna(False).to_numpy(bool)
    xh=x.high.shift(1).rolling(20,min_periods=20).max(); xl=x.low.shift(1).rolling(20,min_periods=20).min()
    o=x.open.to_numpy(float);h=x.high.to_numpy(float);l=x.low.to_numpy(float);c=x.close.to_numpy(float);a=x.atr.to_numpy(float);ix=x.index
    ft,fr=eng.fund_arrays(f);out=[];pos=None;pend=None
    for i in range(len(x)):
        if pos is None and pend is not None:
            si,side,a0=pend
            if i>si and np.isfinite(a0) and a0>0:
                e=o[i];risk_frac=2*a0/e
                pos={'side':side,'e':e,'et':ix[i],'sl':e-side*2*a0,'bars':0,'risk_frac':risk_frac}
            pend=None
        if pos is not None:
            pos['bars']+=1;side=pos['side'];xp=None;reason=None
            if side==1 and l[i]<=pos['sl']:xp=pos['sl'];reason='SL'
            elif side==-1 and h[i]>=pos['sl']:xp=pos['sl'];reason='SL'
            elif side==1 and np.isfinite(xl.iloc[i]) and c[i]<xl.iloc[i]:xp=c[i];reason='CHANNEL'
            elif side==-1 and np.isfinite(xh.iloc[i]) and c[i]>xh.iloc[i]:xp=c[i];reason='CHANNEL'
            elif pos['bars']>=60:xp=c[i];reason='TIME'
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=4);rawret=side*(xp-pos['e'])/pos['e'];fund=-side*eng.fsum(ft,fr,pos['et'],xt)
                out.append({'symbol':sym,'side':'LONG' if side==1 else 'SHORT','entry_time':pos['et'],'exit_time':xt,'raw_ret':rawret,'funding_ret':fund,'risk_frac':pos['risk_frac'],'reason':reason})
                pos=None
        if pos is None and pend is None and i+1<len(x):
            if long[i] and not short[i]:pend=(i,1,a[i])
            elif short[i] and not long[i]:pend=(i,-1,a[i])
    return pd.DataFrame(out)

pools=[]
for sym in eng.SYMS:
    x=eng.prep_segment(raw_map[sym],fund_map[sym],eng.DEV_START,END,daily_map[sym]);z=gen(sym,x,fund_map[sym])
    if not z.empty:pools.append(z)
t=pd.concat(pools,ignore_index=True);t['entry_time']=pd.to_datetime(t.entry_time,utc=True);t['exit_time']=pd.to_datetime(t.exit_time,utc=True);t['net']=t.raw_ret+t.funding_ret-BASE_COST
t.to_csv('donchian_v2_stop_risk_trades.csv',index=False)
print('TRADES',len(t),'risk_frac median',t.risk_frac.median(),'p10',t.risk_frac.quantile(.1),'p90',t.risk_frac.quantile(.9),flush=True)

def sim(z,risk_budget,lev,heatcap,gcap,maxpos):
    z=z.sort_values(['entry_time','symbol']).reset_index(drop=True);ev=[]
    for i,r in z.iterrows():ev += [(r.exit_time,0,i),(r.entry_time,1,i)]
    ev.sort(key=lambda q:(q[0],q[1]));eq=100.;peak=100.;dd=0.;active={};acc=skip=0;peakgross=peakheat=peakmargin=0.
    for _,typ,i in ev:
        r=z.loc[i]
        if typ==0:
            p=active.pop(i,None)
            if p is None:continue
            eq += p['notional']*float(r.net);peak=max(peak,eq);dd=min(dd,eq/peak-1)
            if eq<=0:return {'ret':-100.,'dd':-100.,'acc':acc,'skip':skip,'skip_pct':100*skip/max(1,acc+skip),'peakgross':peakgross*100,'peakheat':peakheat*100,'peakmargin':peakmargin*100,'bankrupt':1}
        else:
            if not np.isfinite(r.risk_frac) or r.risk_frac<=0:skip+=1;continue
            risk_dollars=risk_budget*eq;notional=risk_dollars/float(r.risk_frac);margin=notional/lev
            gross=sum(v['notional'] for v in active.values());heat=sum(v['risk'] for v in active.values());marg=sum(v['margin'] for v in active.values())
            if len(active)>=maxpos or gross+notional>gcap*eq+1e-12 or heat+risk_dollars>heatcap*eq+1e-12 or marg+margin>eq+1e-12:
                skip+=1;continue
            active[i]={'notional':notional,'risk':risk_dollars,'margin':margin};acc+=1
            peakgross=max(peakgross,(gross+notional)/eq);peakheat=max(peakheat,(heat+risk_dollars)/eq);peakmargin=max(peakmargin,(marg+margin)/eq)
    return {'ret':(eq/100-1)*100,'dd':dd*100,'acc':acc,'skip':skip,'skip_pct':100*skip/max(1,acc+skip),'peakgross':peakgross*100,'peakheat':peakheat*100,'peakmargin':peakmargin*100,'bankrupt':0}

rows=[];combos=list(itertools.product(RISK_BUDGETS,LEVS,HEAT_CAPS,GROSS_CAPS,MAX_POS))
for j,(rb,lev,hc,gc,mp) in enumerate(combos,1):
    d={'risk_pct':rb*100,'lev':lev,'heat_cap_pct':hc*100,'gross_cap_pct':gc*100,'max_pos':mp}
    for label,(a,b) in PERIODS.items():
        s=sim(t[(t.entry_time>=a)&(t.entry_time<b)].copy(),rb,lev,hc,gc,mp)
        for k,v in s.items():d[label+'_'+k]=v
    rows.append(d)
    if j%1000==0:print('DONE',j,'/',len(combos),flush=True)
out=pd.DataFrame(rows)
out['eligible']=(out.YTD_2026_dd>-40)&(out.RECENT_dd>-45)&(out.FULL_dd>-60)&(out.YTD_2026_skip_pct<=20)&(out.FULL_bankrupt==0)
out['score']=out.YTD_2026_ret+0.4*out.RECENT_ret+0.1*out.FULL_ret+out.YTD_2026_dd+0.4*out.RECENT_dd-0.3*out.YTD_2026_skip_pct
out.to_csv('donchian_v2_stop_risk_grid.csv',index=False)
cols=['risk_pct','lev','heat_cap_pct','gross_cap_pct','max_pos','YTD_2026_ret','YTD_2026_dd','YTD_2026_skip_pct','YTD_2026_peakgross','YTD_2026_peakheat','YTD_2026_peakmargin','RECENT_ret','RECENT_dd','FULL_ret','FULL_dd','score']
print('\nTOP YTD ELIGIBLE');print(out[out.eligible].sort_values('YTD_2026_ret',ascending=False).head(30)[cols].to_string(index=False))
print('\nTOP SCORE');print(out[out.eligible].sort_values('score',ascending=False).head(30)[cols].to_string(index=False))
