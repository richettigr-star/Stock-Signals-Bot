from __future__ import annotations
import subprocess, random
from pathlib import Path
import pandas as pd
import numpy as np

COSTS=[0.0012,0.0024,0.0036]
MMR=0.005
PERIODS={
'Q1_2026':('2026-01-01','2026-04-01'),
'Q2_2026':('2026-04-01','2026-07-01'),
'Q3_2026':('2026-07-01','2026-10-01'),
'YTD_2026':('2026-01-01','2026-10-01'),
'RECENT_2025_2026':('2025-01-01','2026-10-01'),
'FULL_2021_2026':('2021-01-01','2026-10-01')}
PERIODS={k:(pd.Timestamp(a,tz='UTC'),pd.Timestamp(b,tz='UTC')) for k,(a,b) in PERIODS.items()}

subprocess.run(['python','research/donchian_v2_repo_inspired_exact.py'],check=True,stdout=subprocess.DEVNULL)
t=pd.read_csv(Path('donchian_v2_repo_inspired_exact_output/all_trades.csv'))
t=t[t.variant=='ATRBUF_025'].copy(); t['entry_time']=pd.to_datetime(t.entry_time,utc=True); t['exit_time']=pd.to_datetime(t.exit_time,utc=True)
t=t.sort_values(['entry_time','symbol','exit_time']).reset_index(drop=True)

# Core configs plus fine 2x scan around the short-term frontier.
configs=[
 ('SAFE_12P5_NOTIONAL',0.125,1,8,1.00),
 ('BAL_15_NOTIONAL',0.075,2,8,1.50),
 ('MID_17P5_NOTIONAL',0.0875,2,8,1.50),
 ('AGG_20_CAP150',0.10,2,8,1.50),
 ('AGG_20_FULL',0.10,2,8,2.00),
 ('AGG_22P5_CAP175',0.1125,2,8,1.75),
 ('AGG_22P5_FULL',0.1125,2,8,2.00),
 ('AGG_25_CAP150',0.125,2,8,1.50),
 ('AGG_25_FULL',0.125,2,8,2.00),
]
# Also test equivalent notionals at higher leverage/lower margin to see if liquidation risk changes.
configs += [('EQ15_5M_3X',0.05,3,8,1.50),('EQ20_5M_4X',0.05,4,8,1.50),('EQ20_6P67M_3X',2/30,3,8,1.50)]

def build(z,cost,priority='alpha',seed=0):
 z=z.copy(); z['net']=z.raw_ret.astype(float)+z.funding_ret.astype(float)-cost
 records=[]
 for i,r in z.iterrows(): records.append({'net':float(r.net),'raw':float(r.raw_ret),'reason':str(r.reason),'symbol':str(r.symbol),'et':r.entry_time,'xt':r.exit_time})
 # group entries/exits by timestamp, exits always first. priority only affects same-time entries.
 by={}
 for i,r in enumerate(records):
  by.setdefault(r['xt'].value,{'x':[],'e':[]})['x'].append(i); by.setdefault(r['et'].value,{'x':[],'e':[]})['e'].append(i)
 rng=random.Random(seed)
 events=[]
 for ts in sorted(by):
  for i in by[ts]['x']: events.append((ts,0,i))
  es=by[ts]['e']
  if priority=='alpha': es.sort(key=lambda i:records[i]['symbol'])
  elif priority=='reverse': es.sort(key=lambda i:records[i]['symbol'],reverse=True)
  elif priority=='random': rng.shuffle(es)
  for i in es: events.append((ts,1,i))
 return records,events

def sim(records,events,m,lev,mp,gcap):
 eq=100.; peak=100.; dd=0.; active={}; accepted=[]; skipped=0; liq=0; peakm=peakg=0.
 for _,typ,i in events:
  r=records[i]
  if typ==0:
   p=active.pop(i,None)
   if p is None: continue
   pnl=p['notional']*r['net']; eq+=pnl; accepted.append((i,pnl,r['symbol']))
   if eq<=0: return {'eq':0.,'ret':-100.,'dd':-100.,'acc':len(accepted),'skip':skipped,'skip_pct':100*skipped/max(1,len(accepted)+skipped),'liq':liq,'peakm':peakm*100,'peakg':peakg*100,'bankrupt':1,'accepted':accepted}
   peak=max(peak,eq); dd=min(dd,eq/peak-1)
  else:
   margin=m*eq; notional=margin*lev
   rm=sum(v['margin'] for v in active.values()); rg=sum(v['notional'] for v in active.values())
   if len(active)>=mp or rm+margin>eq+1e-12 or rg+notional>gcap*eq+1e-12:
    skipped+=1; continue
   active[i]={'margin':margin,'notional':notional}; peakm=max(peakm,(rm+margin)/eq); peakg=max(peakg,(rg+notional)/eq)
   if r['reason']=='SL' and abs(r['raw'])>=max(0.,1/lev-MMR): liq+=1
 return {'eq':eq,'ret':(eq/100-1)*100,'dd':dd*100,'acc':len(accepted),'skip':skipped,'skip_pct':100*skipped/max(1,len(accepted)+skipped),'liq':liq,'peakm':peakm*100,'peakg':peakg*100,'bankrupt':0,'accepted':accepted}

rows=[]
for name,m,lev,mp,gc in configs:
 for cost in COSTS:
  for per,(a,b) in PERIODS.items():
   z=t[(t.entry_time>=a)&(t.entry_time<b)].copy()
   rr,ev=build(z,cost,'alpha'); s=sim(rr,ev,m,lev,mp,gc)
   rows.append({'config':name,'margin_pct':m*100,'lev':lev,'max_pos':mp,'gross_cap_pct':gc*100,'cost_pct':cost*100,'period':per,**{k:v for k,v in s.items() if k!='accepted'}})
res=pd.DataFrame(rows); res.to_csv('donchian_v2_finalist_stress.csv',index=False)
print('BASE/STRESS TABLE'); print(res[(res.period=='YTD_2026')].sort_values(['cost_pct','ret'],ascending=[True,False]).to_string(index=False))

# Priority sensitivity only for cap-binding candidates; 200 random tie-break seeds on YTD and recent.
pr=[]
for name,m,lev,mp,gc in configs:
 if name not in ['AGG_20_CAP150','AGG_22P5_CAP175','AGG_25_CAP150']: continue
 for per in ['YTD_2026','RECENT_2025_2026']:
  a,b=PERIODS[per]; z=t[(t.entry_time>=a)&(t.entry_time<b)].copy()
  for mode,seed in [('alpha',0),('reverse',0)]+[('random',s) for s in range(200)]:
   rr,ev=build(z,0.0012,mode,seed); x=sim(rr,ev,m,lev,mp,gc)
   pr.append({'config':name,'period':per,'priority':mode,'seed':seed,'ret':x['ret'],'dd':x['dd'],'skip_pct':x['skip_pct'],'liq':x['liq']})
prd=pd.DataFrame(pr); prd.to_csv('donchian_v2_priority_stress.csv',index=False)
print('\nPRIORITY SUMMARY')
print(prd.groupby(['config','period']).agg(ret_min=('ret','min'),ret_p05=('ret',lambda x:np.quantile(x,.05)),ret_median=('ret','median'),ret_p95=('ret',lambda x:np.quantile(x,.95)),ret_max=('ret','max'),dd_worst=('dd','min'),skip_med=('skip_pct','median')).reset_index().to_string(index=False))

# Drawdown-tier winners from base cost, YTD plus recent/full sanity.
y=res[(res.cost_pct==0.12)&(res.period=='YTD_2026')].copy()
r=res[(res.cost_pct==0.12)&(res.period=='RECENT_2025_2026')][['config','ret','dd']].rename(columns={'ret':'recent_ret','dd':'recent_dd'})
f=res[(res.cost_pct==0.12)&(res.period=='FULL_2021_2026')][['config','ret','dd']].rename(columns={'ret':'full_ret','dd':'full_dd'})
y=y.merge(r,on='config').merge(f,on='config')
print('\nRISK TIERS')
for lim in [20,25,30,35,40,50]:
 q=y[(y.dd>=-lim)&(y.recent_dd>=-lim*1.25)&(y.liq==0)&(y.bankrupt==0)].sort_values('ret',ascending=False).head(3)
 print('\nDD_LIMIT',lim); print(q[['config','margin_pct','lev','gross_cap_pct','ret','dd','recent_ret','recent_dd','full_ret','full_dd','skip_pct']].to_string(index=False))
