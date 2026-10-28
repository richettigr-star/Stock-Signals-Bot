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
t=pd.read_csv(Path('donchian_v2_repo_inspired_exact_output/all_trades.csv')); t=t[t.variant=='ATRBUF_025'].copy()
t['entry_time']=pd.to_datetime(t.entry_time,utc=True);t['exit_time']=pd.to_datetime(t.exit_time,utc=True);t['net']=t.raw_ret+t.funding_ret-BASE_COST
t=t.sort_values(['entry_time','symbol']).reset_index(drop=True)

def sim(z,notional_frac,sidecap,totalcap,gcap):
 z=z.reset_index(drop=True); ev=[]
 for i,r in z.iterrows():ev.extend([(r.exit_time,0,i),(r.entry_time,1,i)])
 ev.sort(key=lambda x:(x[0],x[1]));eq=100.;peak=100.;dd=0.;act={};acc=skip=0
 for _,typ,i in ev:
  r=z.loc[i]
  if typ==0:
   p=act.pop(i,None)
   if p is None:continue
   eq+=p['notional']*float(r.net);peak=max(peak,eq);dd=min(dd,eq/peak-1)
  else:
   gross=sum(v['notional'] for v in act.values()); same=sum(1 for v in act.values() if v['side']==r.side);notional=notional_frac*eq
   if len(act)>=totalcap or same>=sidecap or gross+notional>gcap*eq+1e-12:skip+=1;continue
   act[i]={'notional':notional,'side':r.side};acc+=1
 return {'ret':(eq/100-1)*100,'dd':dd*100,'acc':acc,'skip':skip,'skip_pct':100*skip/max(1,acc+skip)}
rows=[]
for n,sc,tc,gc in itertools.product(NOTIONALS,SIDE_CAPS,TOTAL_CAPS,GROSS_CAPS):
 d={'notional_pct':n*100,'side_cap':sc,'total_cap':tc,'gross_cap_pct':gc*100}
 for label,(a,b) in PERIODS.items():
  s=sim(t[(t.entry_time>=a)&(t.entry_time<b)].copy(),n,sc,tc,gc)
  for k,v in s.items():d[label+'_'+k]=v
 rows.append(d)
out=pd.DataFrame(rows)
out['eligible']=(out.YTD_2026_dd>-40)&(out.RECENT_dd>-45)&(out.FULL_dd>-60)&(out.YTD_2026_skip_pct<=20)
out.to_csv('donchian_v2_directional_caps.csv',index=False)
cols=['notional_pct','side_cap','total_cap','gross_cap_pct','YTD_2026_ret','YTD_2026_dd','YTD_2026_skip_pct','RECENT_ret','RECENT_dd','FULL_ret','FULL_dd']
print('TOP ELIGIBLE RETURN');print(out[out.eligible].sort_values('YTD_2026_ret',ascending=False).head(30)[cols].to_string(index=False))
print('\nTOP RET/DD');x=out[out.eligible].copy();x['score']=x.YTD_2026_ret+0.4*x.RECENT_ret+0.1*x.FULL_ret+x.YTD_2026_dd+0.4*x.RECENT_dd-0.3*x.YTD_2026_skip_pct;print(x.sort_values('score',ascending=False).head(30)[cols+['score']].to_string(index=False))
