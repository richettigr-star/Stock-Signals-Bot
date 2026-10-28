from __future__ import annotations
import itertools
import numpy as np
import pandas as pd
import donchian_v2_repo_inspired_exact as eng

END=pd.Timestamp('2026-10-01',tz='UTC'); BASE_COST=eng.BASE_COST
RISK_BUDGETS=[0.005,0.0075,0.01,0.0125,0.015,0.02,0.025,0.03]
LEVS=[2,3,4,5,7,10]; HEAT_CAPS=[0.04,0.06,0.08,0.10,0.12,0.16]; GROSS_CAPS=[1.0,1.5,2.0,2.5,3.0,4.0]; MAX_POS=[4,6,8]
PERIODS={'YTD_2026':('2026-01-01','2026-10-01'),'RECENT':('2025-01-01','2026-10-01'),'FULL':('2021-01-01','2026-10-01')}
PERIODS={k:(pd.Timestamp(a,tz='UTC'),pd.Timestamp(b,tz='UTC')) for k,(a,b) in PERIODS.items()}
raw_map={};fund_map={};daily_map={}
for sym in eng.SYMS:
 print('LOAD',sym,flush=True);raw,_=eng.loadbars(sym);f,_=eng.loadfund(sym);raw_map[sym]=raw;fund_map[sym]=f;daily_map[sym]=eng.full_daily_features(raw)

def gen(sym,x,f):
 eh=x.high.shift(1).rolling(40,min_periods=40).max();el=x.low.shift(1).rolling(40,min_periods=40).min();ap=x.atr.shift(1)
 la=((x.close>eh+0.25*ap)&(x.close>x.ema200)).fillna(False).to_numpy(bool);sa=((x.close<el-0.25*ap)&(x.close<x.ema200)).fillna(False).to_numpy(bool)
 xh=x.high.shift(1).rolling(20,min_periods=20).max();xl=x.low.shift(1).rolling(20,min_periods=20).min();o=x.open.to_numpy(float);h=x.high.to_numpy(float);l=x.low.to_numpy(float);c=x.close.to_numpy(float);a=x.atr.to_numpy(float);ix=x.index
 ft,fr=eng.fund_arrays(f);out=[];pos=None;pend=None
 for i in range(len(x)):
  if pos is None and pend is not None:
   si,side,a0=pend
   if i>si and np.isfinite(a0) and a0>0:
    e=o[i];pos={'side':side,'e':e,'et':ix[i],'sl':e-side*2*a0,'bars':0,'risk_frac':2*a0/e}
   pend=None
  if pos is not None:
   pos['bars']+=1;side=pos['side'];xp=None;reason=None
   if side==1 and l[i]<=pos['sl']:xp=pos['sl'];reason='SL'
   elif side==-1 and h[i]>=pos['sl']:xp=pos['sl'];reason='SL'
   elif side==1 and np.isfinite(xl.iloc[i]) and c[i]<xl.iloc[i]:xp=c[i];reason='CHANNEL'
   elif side==-1 and np.isfinite(xh.iloc[i]) and c[i]>xh.iloc[i]:xp=c[i];reason='CHANNEL'
   elif pos['bars']>=60:xp=c[i];reason='TIME'
   if xp is not None:
    xt=ix[i]+pd.Timedelta(hours=4);rawret=side*(xp-pos['e'])/pos['e'];fund=-side*eng.fsum(ft,fr,pos['et'],xt);out.append((sym,pos['et'],xt,rawret+fund-BASE_COST,pos['risk_frac']));pos=None
  if pos is None and pend is None and i+1<len(x):
   if la[i] and not sa[i]:pend=(i,1,a[i])
   elif sa[i] and not la[i]:pend=(i,-1,a[i])
 return out
tr=[]
for sym in eng.SYMS:
 x=eng.prep_segment(raw_map[sym],fund_map[sym],eng.DEV_START,END,daily_map[sym]);tr.extend(gen(sym,x,fund_map[sym]))
t=pd.DataFrame(tr,columns=['symbol','entry_time','exit_time','net','risk_frac']).sort_values(['entry_time','symbol']).reset_index(drop=True)
print('TRADES',len(t),'risk median',t.risk_frac.median(),'p10',t.risk_frac.quantile(.1),'p90',t.risk_frac.quantile(.9),flush=True)
t.to_csv('donchian_v2_stop_risk_trades_fast.csv',index=False)

def build(a,b):
 z=t[(t.entry_time>=a)&(t.entry_time<b)].reset_index(drop=True);rec=[];ev=[]
 for i,r in z.iterrows():rec.append((float(r.net),float(r.risk_frac)));ev.append((r.exit_time.value,0,i));ev.append((r.entry_time.value,1,i))
 ev.sort(key=lambda q:(q[0],q[1]));return rec,ev
BUILT={k:build(*v) for k,v in PERIODS.items()}

def sim(rec,ev,rb,lev,hc,gc,mp):
 eq=100.;peak=100.;dd=0.;act={};acc=skip=0;pg=ph=pm=0.
 for _,typ,i in ev:
  net,rf=rec[i]
  if typ==0:
   p=act.pop(i,None)
   if p is None:continue
   eq+=p[0]*net
   if eq<=0:return (-100.,-100.,acc,skip,100*skip/max(1,acc+skip),pg*100,ph*100,pm*100,1)
   peak=max(peak,eq);dd=min(dd,eq/peak-1)
  else:
   risk=rb*eq;notional=risk/rf;margin=notional/lev;gross=sum(v[0] for v in act.values());heat=sum(v[1] for v in act.values());marg=sum(v[2] for v in act.values())
   if len(act)>=mp or gross+notional>gc*eq+1e-12 or heat+risk>hc*eq+1e-12 or marg+margin>eq+1e-12:skip+=1;continue
   act[i]=(notional,risk,margin);acc+=1;pg=max(pg,(gross+notional)/eq);ph=max(ph,(heat+risk)/eq);pm=max(pm,(marg+margin)/eq)
 return ((eq/100-1)*100,dd*100,acc,skip,100*skip/max(1,acc+skip),pg*100,ph*100,pm*100,0)
rows=[];combos=list(itertools.product(RISK_BUDGETS,LEVS,HEAT_CAPS,GROSS_CAPS,MAX_POS))
for j,(rb,lev,hc,gc,mp) in enumerate(combos,1):
 d={'risk_pct':rb*100,'lev':lev,'heat_cap_pct':hc*100,'gross_cap_pct':gc*100,'max_pos':mp}
 for label,(rec,ev) in BUILT.items():
  vals=sim(rec,ev,rb,lev,hc,gc,mp)
  for k,v in zip(['ret','dd','acc','skip','skip_pct','peakgross','peakheat','peakmargin','bankrupt'],vals):d[label+'_'+k]=v
 rows.append(d)
 if j%1000==0:print('DONE',j,'/',len(combos),flush=True)
out=pd.DataFrame(rows);out['eligible']=(out.YTD_2026_dd>-40)&(out.RECENT_dd>-45)&(out.FULL_dd>-60)&(out.YTD_2026_skip_pct<=20)&(out.FULL_bankrupt==0)
out['score']=out.YTD_2026_ret+0.4*out.RECENT_ret+0.1*out.FULL_ret+out.YTD_2026_dd+0.4*out.RECENT_dd-0.3*out.YTD_2026_skip_pct
out.to_csv('donchian_v2_stop_risk_grid_fast.csv',index=False)
cols=['risk_pct','lev','heat_cap_pct','gross_cap_pct','max_pos','YTD_2026_ret','YTD_2026_dd','YTD_2026_skip_pct','YTD_2026_peakgross','YTD_2026_peakheat','YTD_2026_peakmargin','RECENT_ret','RECENT_dd','FULL_ret','FULL_dd','score']
print('\nTOP YTD ELIGIBLE');print(out[out.eligible].sort_values('YTD_2026_ret',ascending=False).head(30)[cols].to_string(index=False));print('\nTOP SCORE');print(out[out.eligible].sort_values('score',ascending=False).head(30)[cols].to_string(index=False))
