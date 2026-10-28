from __future__ import annotations
import subprocess,itertools
from pathlib import Path
import pandas as pd

BASE_COST=0.0012
NOTIONALS=[0.125,0.15,0.175,0.20,0.225,0.25]
SIDE_CAPS=[2,3,4,5,8]
TOTAL_CAPS=[4,5,6,8]
GROSS_CAPS=[1.0,1.25,1.5,1.75,2.0]
PERIODS={'YTD_2026':('2026-01-01','2026-10-01'),'RECENT':('2025-01-01','2026-10-01'),'FULL':('2021-01-01','2026-10-01')}
PERIODS={k:(pd.Timestamp(a,tz='UTC'),pd.Timestamp(b,tz='UTC')) for k,(a,b) in PERIODS.items()}
subprocess.run(['python','research/donchian_v2_repo_inspired_exact.py'],check=True,stdout=subprocess.DEVNULL)
t=pd.read_csv(Path('donchian_v2_repo_inspired_exact_output/all_trades.csv'));t=t[t.variant=='ATRBUF_025'].copy()
t['entry_time']=pd.to_datetime(t.entry_time,utc=True);t['exit_time']=pd.to_datetime(t.exit_time,utc=True);t['net']=t.raw_ret+t.funding_ret-BASE_COST;t=t.sort_values(['entry_time','symbol']).reset_index(drop=True)

def build(a,b):
 z=t[(t.entry_time>=a)&(t.entry_time<b)].copy().reset_index(drop=True);rec=[];ev=[]
 for i,r in z.iterrows():
  rec.append((float(r.net),str(r.side)));ev.append((r.exit_time.value,0,i));ev.append((r.entry_time.value,1,i))
 ev.sort(key=lambda q:(q[0],q[1]));return rec,ev
BUILT={k:build(*v) for k,v in PERIODS.items()}

def sim(rec,ev,n,sc,tc,gc):
 eq=100.;peak=100.;dd=0.;act={};acc=skip=0
 for _,typ,i in ev:
  net,side=rec[i]
  if typ==0:
   notion=act.pop(i,None)
   if notion is None:continue
   eq += notion[0]*net;peak=max(peak,eq);dd=min(dd,eq/peak-1)
  else:
   gross=sum(v[0] for v in act.values());same=sum(1 for v in act.values() if v[1]==side);notional=n*eq
   if len(act)>=tc or same>=sc or gross+notional>gc*eq+1e-12:skip+=1;continue
   act[i]=(notional,side);acc+=1
 return (eq/100-1)*100,dd*100,acc,skip,100*skip/max(1,acc+skip)
rows=[]
for n,sc,tc,gc in itertools.product(NOTIONALS,SIDE_CAPS,TOTAL_CAPS,GROSS_CAPS):
 d={'notional_pct':n*100,'side_cap':sc,'total_cap':tc,'gross_cap_pct':gc*100}
 for label,(rec,ev) in BUILT.items():
  vals=sim(rec,ev,n,sc,tc,gc)
  for k,v in zip(['ret','dd','acc','skip','skip_pct'],vals):d[label+'_'+k]=v
 rows.append(d)
out=pd.DataFrame(rows);out['eligible']=(out.YTD_2026_dd>-40)&(out.RECENT_dd>-45)&(out.FULL_dd>-60)&(out.YTD_2026_skip_pct<=20)
out['score']=out.YTD_2026_ret+0.4*out.RECENT_ret+0.1*out.FULL_ret+out.YTD_2026_dd+0.4*out.RECENT_dd-0.3*out.YTD_2026_skip_pct
out.to_csv('donchian_v2_directional_caps_fast.csv',index=False)
cols=['notional_pct','side_cap','total_cap','gross_cap_pct','YTD_2026_ret','YTD_2026_dd','YTD_2026_skip_pct','RECENT_ret','RECENT_dd','FULL_ret','FULL_dd','score']
print('TOP ELIGIBLE RETURN');print(out[out.eligible].sort_values('YTD_2026_ret',ascending=False).head(30)[cols].to_string(index=False))
print('\nTOP SCORE');print(out[out.eligible].sort_values('score',ascending=False).head(30)[cols].to_string(index=False))
