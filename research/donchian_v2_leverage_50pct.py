from __future__ import annotations

import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

BASE_COST = 0.0012
MARGIN_FRAC = 0.50
LEVERAGES = [1, 2, 3, 5, 7, 10]
MMR = 0.005  # approximate maintenance-margin rate for a conservative isolated-liq diagnostic
START_2026 = pd.Timestamp('2026-01-01', tz='UTC')
END = pd.Timestamp('2026-10-01', tz='UTC')
FULL_START = pd.Timestamp('2021-01-01', tz='UTC')

# Generate the exact candidate trade set using the already-audited research engine.
subprocess.run(['python', 'research/donchian_v2_repo_inspired_exact.py'], check=True)
p = Path('donchian_v2_repo_inspired_exact_output/all_trades.csv')
t = pd.read_csv(p)
t = t[t['variant'] == 'ATRBUF_025'].copy()
t['entry_time'] = pd.to_datetime(t['entry_time'], utc=True)
t['exit_time'] = pd.to_datetime(t['exit_time'], utc=True)
t['net_ret'] = t['raw_ret'].astype(float) + t['funding_ret'].astype(float) - BASE_COST


def peak_concurrency(z):
    ev=[]
    for r in z.itertuples():
        ev.append((r.entry_time, 1))
        ev.append((r.exit_time, -1))
    # exits first at identical timestamp
    ev.sort(key=lambda x:(x[0], x[1]))
    n=mx=0
    for _,d in ev:
        n += d
        mx=max(mx,n)
    return mx


def capped_portfolio(z, lev):
    z=z.sort_values(['entry_time','symbol']).copy()
    events=[]
    for idx,r in z.iterrows():
        events.append((r.entry_time, 1, idx))
        events.append((r.exit_time, 0, idx))
    # exits before entries at same time
    events.sort(key=lambda x:(x[0], x[1]))
    eq=100.0
    peak=100.0
    max_dd=0.0
    active={}
    skipped=0
    accepted=0
    min_definite_liq=0
    max_margin_used_pct=0.0
    realized_losses=[]
    for ts,typ,idx in events:
        r=z.loc[idx]
        if typ==0:  # exit
            if idx not in active:
                continue
            pos=active.pop(idx)
            pnl=pos['notional']*float(r.net_ret)
            eq += pnl
            realized_losses.append(pnl)
            if eq <= 0:
                return {
                    'ending_equity':0.0,'return_pct':-100.0,'max_dd_pct':-100.0,
                    'accepted':accepted,'skipped':skipped,'max_margin_used_pct':max_margin_used_pct,
                    'min_definite_liq':min_definite_liq,'bankrupt':True,
                    'worst_realized_trade_pct': min(realized_losses)/100*100 if realized_losses else 0.0,
                }
            peak=max(peak,eq)
            max_dd=min(max_dd, eq/peak-1)
        else:  # entry
            reserved=sum(v['margin'] for v in active.values())
            margin=MARGIN_FRAC*eq
            if reserved + margin > eq + 1e-12:
                skipped += 1
                continue
            notional=margin*lev
            active[idx]={'margin':margin,'notional':notional}
            accepted += 1
            max_margin_used_pct=max(max_margin_used_pct,(reserved+margin)/eq*100)
            # Lower-bound isolated-liquidation diagnostic: if a stop-loss trade's
            # realized adverse move exceeds approximate liq distance, liquidation
            # would have occurred before its modeled stop.
            if str(r['reason'])=='SL':
                liq_dist=max(0.0,1.0/lev - MMR)
                if abs(float(r['raw_ret'])) >= liq_dist:
                    min_definite_liq += 1
    # Mark remaining open positions at their modeled exit is not needed because all generated trades exit before END.
    return {
        'ending_equity':eq,'return_pct':(eq/100-1)*100,'max_dd_pct':max_dd*100,
        'accepted':accepted,'skipped':skipped,'max_margin_used_pct':max_margin_used_pct,
        'min_definite_liq':min_definite_liq,'bankrupt':False,
        'worst_realized_trade_pct': min(realized_losses)/100*100 if realized_losses else 0.0,
    }


def uncapped_compound(z,lev):
    # Research-style realized-equity compounding using all trades, ignoring margin feasibility.
    eq=100.0; peak=100.0; dd=0.0
    for r in z.sort_values(['exit_time','entry_time']).itertuples():
        eq += MARGIN_FRAC*eq*lev*float(r.net_ret)
        if eq <= 0:
            return 0.0,-100.0,True
        peak=max(peak,eq); dd=min(dd,eq/peak-1)
    return eq,dd*100,False

rows=[]
for label,a,b in [('YTD_2026',START_2026,END),('FULL_2021_2026',FULL_START,END)]:
    z=t[(t.entry_time>=a)&(t.entry_time<b)].copy()
    pc=peak_concurrency(z)
    for lev in LEVERAGES:
        cap=capped_portfolio(z,lev)
        ueq,udd,ub=uncapped_compound(z,lev)
        rows.append({
            'period':label,'leverage':lev,'margin_per_entry_pct':50,
            'source_trades':len(z),'peak_source_concurrency':pc,
            'margin_required_if_all_signals_pct':pc*50,
            **cap,
            'uncapped_ending_equity':ueq,
            'uncapped_return_pct':ueq-100,
            'uncapped_max_dd_pct':udd,
            'uncapped_bankrupt':ub,
        })

out=pd.DataFrame(rows)
out.to_csv('donchian_v2_leverage_50pct.csv',index=False)
print(out.to_string(index=False))
