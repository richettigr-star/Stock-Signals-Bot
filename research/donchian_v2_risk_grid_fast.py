from __future__ import annotations
import subprocess, itertools
from pathlib import Path
import pandas as pd

BASE_COST=0.0012
MARGINS=[0.05,0.075,0.10,0.125,0.15,0.20,0.25,0.30,0.40,0.50]
LEVS=[1,2,3,4,5,6,7,8,10]
MAX_POS=[2,3,4,5,6,8]
GROSS_CAPS=[1.0,1.5,2.0,2.5,3.0,4.0,5.0]
MMR=0.005
PERIODS={
'YTD_2026':(pd.Timestamp('2026-01-01',tz='UTC'),pd.Timestamp('2026-10-01',tz='UTC')),
'RECENT_2025_2026':(pd.Timestamp('2025-01-01',tz='UTC'),pd.Timestamp('2026-10-01',tz='UTC')),
'FULL_2021_2026':(pd.Timestamp('2021-01-01',tz='UTC'),pd.Timestamp('2026-10-01',tz='UTC'))}
subprocess.run(['python','research/donchian_v2_repo_inspired_exact.py'],check=True,stdout=subprocess.DEVNULL)
t=pd.read_csv(Path('donchian_v2_repo_inspired_exact_output/all_trades.csv'))
t=t[t.variant=='ATRBUF_025'].copy()
t['entry_time']=pd.to_datetime(t.entry_time,utc=True); t['exit_time']=pd.to_datetime(t.exit_time,utc=True)
t['net_ret']=t.raw_ret.astype(float)+t.funding_ret.astype(float)-BASE_COST
t=t.sort_values(['entry_time','symbol','exit_time']).reset_index(drop=True)

def build(a,b):
 z=t[(t.entry_time>=a)&(t.entry_time<b)].copy().reset_index(drop=True)
 rec=[]; ev=[]
 for i,r in z.iterrows():
  rec.append((float(r.net_ret),float(r.raw_ret),str(r.reason)))
  ev.append((r.exit_time.value,0,i)); ev.append((r.entry_time.value,1,i))
 ev.sort(key=lambda x:(x[0],x[1]))
 return rec,ev,len(z)
BUILT={k:build(*v) for k,v in PERIODS.items()}

def sim(rec,ev,ntr,m,lev,mp,gcap):
 eq=100.; peak=100.; dd=0.; active={}; acc=skip=0; pm=pg=0.; liq=0
 for _,typ,i in ev:
  nr,rr,reason=rec[i]
  if typ==0:
   p=active.pop(i,None)
   if p is None: continue
   eq += p[1]*nr
   if eq<=0: return (0.,-100.,-100.,acc,skip,100*skip/max(1,acc+skip),pm*100,pg*100,liq,1)
   peak=max(peak,eq); dd=min(dd,eq/peak-1)
  else:
   margin=m*eq; notion=margin*lev
   reserved=sum(v[0] for v in active.values()); gross=sum(v[1] for v in active.values())
   if len(active)>=mp or reserved+margin>eq+1e-12 or gross+notion>gcap*eq+1e-12:
    skip+=1; continue
   active[i]=(margin,notion); acc+=1
   pm=max(pm,(reserved+margin)/eq); pg=max(pg,(gross+notion)/eq)
   if reason=='SL' and abs(rr)>=max(0.,1/lev-MMR): liq+=1
 return (eq,(eq/100-1)*100,dd*100,acc,skip,100*skip/max(1,acc+skip),pm*100,pg*100,liq,0)

rows=[]; combos=list(itertools.product(MARGINS,LEVS,MAX_POS,GROSS_CAPS))
for n,(m,l,mp,gc) in enumerate(combos,1):
 d={'margin_pct':m*100,'leverage':l,'max_pos':mp,'gross_cap_pct':gc*100}
 for label,(rec,ev,ntr) in BUILT.items():
  vals=sim(rec,ev,ntr,m,l,mp,gc)
  for k,v in zip(['end_eq','ret','dd','accepted','skipped','skip_pct','peak_margin_pct','peak_gross_pct','liq_flags','bankrupt'],vals): d[label+'_'+k]=v
 rows.append(d)
 if n%1000==0: print('DONE',n,'/',len(combos),flush=True)
out=pd.DataFrame(rows)
out['safe_basic']=(out.FULL_2021_2026_bankrupt==0)&(out.FULL_2021_2026_liq_flags==0)&(out.YTD_2026_dd>-50)&(out.RECENT_2025_2026_dd>-50)&(out.FULL_2021_2026_dd>-60)
out['practical']=out.safe_basic&(out.YTD_2026_skip_pct<=25)&(out.RECENT_2025_2026_skip_pct<=25)
out['short_score']=out.YTD_2026_ret+0.35*out.RECENT_2025_2026_ret+0.10*out.FULL_2021_2026_ret+0.75*out.YTD_2026_dd+0.30*out.RECENT_2025_2026_dd-0.35*out.YTD_2026_skip_pct
out['robust_score']=out.YTD_2026_ret+0.50*out.RECENT_2025_2026_ret+0.20*out.FULL_2021_2026_ret+1.25*out.YTD_2026_dd+0.75*out.RECENT_2025_2026_dd+0.25*out.FULL_2021_2026_dd-0.50*out.YTD_2026_skip_pct
out.to_csv('donchian_v2_risk_grid_fast_all.csv',index=False)
print('GRID',len(out),'PRACTICAL',int(out.practical.sum()))
cols=['margin_pct','leverage','max_pos','gross_cap_pct','YTD_2026_end_eq','YTD_2026_ret','YTD_2026_dd','YTD_2026_skip_pct','RECENT_2025_2026_ret','RECENT_2025_2026_dd','FULL_2021_2026_ret','FULL_2021_2026_dd','FULL_2021_2026_liq_flags','short_score','robust_score']
for title,sub in [
 ('MAX_RAW_YTD',out.sort_values('YTD_2026_ret',ascending=False).head(20)),
 ('TOP_PRACTICAL_YTD',out[out.practical].sort_values('YTD_2026_ret',ascending=False).head(30)),
 ('TOP_SHORT_SCORE',out[out.practical].sort_values('short_score',ascending=False).head(30)),
 ('TOP_ROBUST_SCORE',out[out.practical].sort_values('robust_score',ascending=False).head(30))]:
 print('\n'+title); print(sub[cols].to_string(index=False))
parts=[]
for c in ['YTD_2026_ret','short_score','robust_score']:
 x=out[out.practical].sort_values(c,ascending=False).head(40).copy(); x['selected_by']=c; parts.append(x)
fin=pd.concat(parts).drop_duplicates(['margin_pct','leverage','max_pos','gross_cap_pct'])
fin.to_csv('donchian_v2_risk_grid_fast_finalists.csv',index=False)
print('\nFINALISTS',len(fin))
