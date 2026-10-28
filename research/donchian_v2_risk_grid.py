from __future__ import annotations

import subprocess
from pathlib import Path
import itertools
import numpy as np
import pandas as pd

BASE_COST = 0.0012
MARGINS = [0.05,0.075,0.10,0.125,0.15,0.20,0.25,0.30,0.40,0.50]
LEVS = [1,2,3,4,5,6,7,8,10]
MAX_POS = [2,3,4,5,6,8]
GROSS_CAPS = [1.0,1.5,2.0,2.5,3.0,4.0,5.0]
MMR = 0.005
PERIODS = {
    'YTD_2026': (pd.Timestamp('2026-01-01',tz='UTC'), pd.Timestamp('2026-10-01',tz='UTC')),
    'RECENT_2025_2026': (pd.Timestamp('2025-01-01',tz='UTC'), pd.Timestamp('2026-10-01',tz='UTC')),
    'FULL_2021_2026': (pd.Timestamp('2021-01-01',tz='UTC'), pd.Timestamp('2026-10-01',tz='UTC')),
}

subprocess.run(['python','research/donchian_v2_repo_inspired_exact.py'],check=True)
p=Path('donchian_v2_repo_inspired_exact_output/all_trades.csv')
t=pd.read_csv(p)
t=t[t.variant=='ATRBUF_025'].copy()
t['entry_time']=pd.to_datetime(t.entry_time,utc=True)
t['exit_time']=pd.to_datetime(t.exit_time,utc=True)
t['net_ret']=t.raw_ret.astype(float)+t.funding_ret.astype(float)-BASE_COST

# deterministic priority for simultaneous entries: strongest historical-neutral order by symbol name.
# We will later run alternate priority diagnostics on top finalists.
t=t.sort_values(['entry_time','symbol','exit_time']).reset_index(drop=True)


def simulate(z, margin_frac, lev, max_pos, gross_cap):
    events=[]
    for idx,r in z.iterrows():
        events.append((r.exit_time,0,idx))
        events.append((r.entry_time,1,idx))
    events.sort(key=lambda x:(x[0],x[1])) # exits before entries
    eq=100.0; peak=100.0; dd=0.0; active={}; accepted=skipped=0
    peak_margin=0.0; peak_gross=0.0; liq_flags=0; worst_trade=0.0
    for ts,typ,idx in events:
        r=z.loc[idx]
        if typ==0:
            if idx not in active: continue
            pos=active.pop(idx)
            pnl=pos['notional']*float(r.net_ret)
            eq += pnl
            worst_trade=min(worst_trade,pnl)
            if eq <= 0:
                return dict(end_eq=0.0,ret=-100.0,dd=-100.0,accepted=accepted,skipped=skipped,skip_pct=100*skipped/max(1,accepted+skipped),peak_margin_pct=peak_margin*100,peak_gross_pct=peak_gross*100,liq_flags=liq_flags,bankrupt=True,worst_trade_pct=-100.0)
            peak=max(peak,eq); dd=min(dd,eq/peak-1)
        else:
            margin=margin_frac*eq
            notional=margin*lev
            reserved=sum(v['margin'] for v in active.values())
            gross=sum(v['notional'] for v in active.values())
            if len(active)>=max_pos or reserved+margin>eq+1e-12 or gross+notional>gross_cap*eq+1e-12:
                skipped+=1; continue
            active[idx]={'margin':margin,'notional':notional}; accepted+=1
            peak_margin=max(peak_margin,(reserved+margin)/eq)
            peak_gross=max(peak_gross,(gross+notional)/eq)
            if str(r.reason)=='SL':
                liq_dist=max(0.0,1.0/lev-MMR)
                if abs(float(r.raw_ret)) >= liq_dist:
                    liq_flags += 1
    return dict(end_eq=eq,ret=(eq/100-1)*100,dd=dd*100,accepted=accepted,skipped=skipped,skip_pct=100*skipped/max(1,accepted+skipped),peak_margin_pct=peak_margin*100,peak_gross_pct=peak_gross*100,liq_flags=liq_flags,bankrupt=False,worst_trade_pct=worst_trade)

rows=[]
combos=list(itertools.product(MARGINS,LEVS,MAX_POS,GROSS_CAPS))
for n,(m,l,mp,gc) in enumerate(combos,1):
    rec={'margin_pct':m*100,'leverage':l,'max_pos':mp,'gross_cap_pct':gc*100}
    for label,(a,b) in PERIODS.items():
        z=t[(t.entry_time>=a)&(t.entry_time<b)].copy()
        s=simulate(z,m,l,mp,gc)
        for k,v in s.items(): rec[f'{label}_{k}']=v
    rows.append(rec)
    if n%500==0: print('DONE',n,'/',len(combos),flush=True)

out=pd.DataFrame(rows)
# hard safety filters used only for ranking, not deletion of raw grid
out['safe_basic']=(~out['FULL_2021_2026_bankrupt'])&(out['FULL_2021_2026_liq_flags']==0)&(out['YTD_2026_dd']>-50)&(out['RECENT_2025_2026_dd']>-50)&(out['FULL_2021_2026_dd']>-60)
out['practical'] = out['safe_basic'] & (out['YTD_2026_skip_pct']<=25) & (out['RECENT_2025_2026_skip_pct']<=25)
out['short_score']=out['YTD_2026_ret'] + 0.35*out['RECENT_2025_2026_ret'] + 0.10*out['FULL_2021_2026_ret'] + 0.75*out['YTD_2026_dd'] + 0.30*out['RECENT_2025_2026_dd'] - 0.35*out['YTD_2026_skip_pct']
out['robust_score']=out['YTD_2026_ret'] + 0.50*out['RECENT_2025_2026_ret'] + 0.20*out['FULL_2021_2026_ret'] + 1.25*out['YTD_2026_dd'] + 0.75*out['RECENT_2025_2026_dd'] + 0.25*out['FULL_2021_2026_dd'] - 0.5*out['YTD_2026_skip_pct']
out.to_csv('donchian_v2_risk_grid_all.csv',index=False)

print('\nTOP RAW YTD RETURN')
print(out.sort_values('YTD_2026_ret',ascending=False).head(20).to_string(index=False))
print('\nTOP PRACTICAL SHORT SCORE')
print(out[out.practical].sort_values('short_score',ascending=False).head(30).to_string(index=False))
print('\nTOP PRACTICAL ROBUST SCORE')
print(out[out.practical].sort_values('robust_score',ascending=False).head(30).to_string(index=False))

# Save concise finalist table: union top 30 across key objectives.
parts=[]
for col in ['YTD_2026_ret','RECENT_2025_2026_ret','short_score','robust_score']:
    x=out[out.practical].sort_values(col,ascending=False).head(30).copy(); x['selected_by']=col; parts.append(x)
fin=pd.concat(parts,ignore_index=True).drop_duplicates(['margin_pct','leverage','max_pos','gross_cap_pct'])
fin.to_csv('donchian_v2_risk_grid_finalists.csv',index=False)
print('\nGRID',len(out),'PRACTICAL',int(out.practical.sum()),'FINALISTS',len(fin))
