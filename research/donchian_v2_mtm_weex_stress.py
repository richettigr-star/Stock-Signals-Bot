from __future__ import annotations

import itertools
from dataclasses import dataclass
import numpy as np
import pandas as pd

import donchian_v2_repo_inspired_exact as eng

START = pd.Timestamp('2021-01-01', tz='UTC')
END = pd.Timestamp('2026-10-01', tz='UTC')
INITIAL = 100.0
WEEX_TAKER = 0.0008
CLOSE_FEE_RESERVE = 0.0008

# Public WEEX current first-tier MMR is 0.15% for BTC/ETH small positions.
# Public current pair-specific tables were not found for the six alts; 0.50%
# is used as a conservative small-position assumption and 1.00% as stress.
MMR_BASE = {
    'BTCUSDT': 0.0015, 'ETHUSDT': 0.0015,
    'SOLUSDT': 0.0050, 'XRPUSDT': 0.0050, 'BNBUSDT': 0.0050,
    'DOGEUSDT': 0.0050, 'ADAUSDT': 0.0050, 'LINKUSDT': 0.0050,
}

TIERS = {
    'CONTROLLED': dict(risk=0.0050, lev=3.0, heat=0.04, gross=2.50, max_pos=8),
    'AGGRESSIVE': dict(risk=0.0075, lev=4.0, heat=0.06, gross=3.00, max_pos=8),
    'VERY_AGGRESSIVE': dict(risk=0.0100, lev=5.0, heat=0.08, gross=4.00, max_pos=8),
}
SLIPPAGE_BPS = [0.0, 2.0, 5.0, 10.0]
MMR_SCENARIOS = ['BASE', 'STRESS_1PCT']
MARGIN_MODES = ['ISOLATED', 'CROSS']

raw_map = {}
fund_map = {}
daily_map = {}
for sym in eng.SYMS:
    print('LOAD', sym, flush=True)
    raw, _ = eng.loadbars(sym)
    f, _ = eng.loadfund(sym)
    raw_map[sym] = raw
    fund_map[sym] = f
    daily_map[sym] = eng.full_daily_features(raw)


def make_templates(sym: str):
    x = eng.prep_segment(raw_map[sym], fund_map[sym], START, END, daily_map[sym])
    eh = x.high.shift(1).rolling(40, min_periods=40).max()
    el = x.low.shift(1).rolling(40, min_periods=40).min()
    ap = x.atr.shift(1)
    la = ((x.close > eh + 0.25 * ap) & (x.close > x.ema200)).fillna(False).to_numpy(bool)
    sa = ((x.close < el - 0.25 * ap) & (x.close < x.ema200)).fillna(False).to_numpy(bool)
    xh = x.high.shift(1).rolling(20, min_periods=20).max()
    xl = x.low.shift(1).rolling(20, min_periods=20).min()
    o = x.open.to_numpy(float); h = x.high.to_numpy(float); l = x.low.to_numpy(float)
    c = x.close.to_numpy(float); a = x.atr.to_numpy(float); ix = x.index
    out = []
    pos = None; pend = None
    for i in range(len(x)):
        if pos is None and pend is not None:
            si, side, a0 = pend
            if i > si and np.isfinite(a0) and a0 > 0:
                e = o[i]
                pos = dict(side=side, entry=e, entry_time=ix[i], stop=e - side * 2.0 * a0,
                           atr=a0, bars=0)
            pend = None
        if pos is not None:
            pos['bars'] += 1
            side = pos['side']; xp = None; reason = None
            if side == 1 and l[i] <= pos['stop']:
                xp = pos['stop']; reason = 'SL'
            elif side == -1 and h[i] >= pos['stop']:
                xp = pos['stop']; reason = 'SL'
            elif side == 1 and np.isfinite(xl.iloc[i]) and c[i] < xl.iloc[i]:
                xp = c[i]; reason = 'CHANNEL'
            elif side == -1 and np.isfinite(xh.iloc[i]) and c[i] > xh.iloc[i]:
                xp = c[i]; reason = 'CHANNEL'
            elif pos['bars'] >= 60:
                xp = c[i]; reason = 'TIME'
            if xp is not None:
                out.append(dict(symbol=sym, side=side, entry_time=pos['entry_time'],
                                intended_entry=pos['entry'], stop=pos['stop'], atr=pos['atr'],
                                planned_exit_time=ix[i] + pd.Timedelta(hours=4),
                                planned_exit_price=xp, planned_reason=reason,
                                risk_frac=abs(pos['entry'] - pos['stop']) / pos['entry']))
                pos = None
        if pos is None and pend is None and i + 1 < len(x):
            if la[i] and not sa[i]: pend = (i, 1, a[i])
            elif sa[i] and not la[i]: pend = (i, -1, a[i])
    return pd.DataFrame(out)


templates = pd.concat([make_templates(s) for s in eng.SYMS], ignore_index=True)
templates = templates.sort_values(['entry_time', 'symbol']).reset_index(drop=True)
templates['id'] = np.arange(len(templates), dtype=int)
print('TEMPLATES', len(templates), 'median stop%', templates.risk_frac.median() * 100,
      'max stop%', templates.risk_frac.max() * 100, flush=True)
templates.to_csv('donchian_v2_mtm_templates.csv', index=False)

# 1H bars, synchronized on the actual Binance USD-M trade-price archive used by the research.
bars = {}
all_hours = set()
for sym in eng.SYMS:
    b = raw_map[sym][(raw_map[sym].index >= START) & (raw_map[sym].index < END)].copy()
    bars[sym] = b
    all_hours.update(b.index.tolist())
HOURS = sorted(all_hours)

entries_at = {}
for r in templates.itertuples():
    entries_at.setdefault(pd.Timestamp(r.entry_time), []).append(r)

# Funding event lookup. Binance historical funding is retained as the historical proxy;
# this is intentionally not labelled as WEEX historical funding.
fund_at = {}
for sym, f in fund_map.items():
    if f.empty: continue
    z = f[(f.time >= START) & (f.time < END)]
    for rr in z.itertuples():
        fund_at.setdefault(pd.Timestamp(rr.time), []).append((sym, float(rr.last_funding_rate)))


@dataclass
class Position:
    tid: int
    symbol: str
    side: int
    qty: float
    entry_fill: float
    intended_entry: float
    stop: float
    entry_time: pd.Timestamp
    planned_exit_time: pd.Timestamp
    planned_reason: str
    risk_dollars: float
    init_notional: float
    margin: float
    iso_margin_balance: float
    mmr: float


def slip_entry(px, side, slip):
    return px * (1.0 + side * slip)


def slip_exit(px, side, slip):
    return px * (1.0 - side * slip)


def mmr_for(sym, scenario):
    if scenario == 'STRESS_1PCT': return 0.01
    return MMR_BASE[sym]


def iso_liq_price(p: Position):
    req = p.mmr + CLOSE_FEE_RESERVE
    m_per_q = p.iso_margin_balance / p.qty
    if p.side == 1:
        den = max(1e-12, 1.0 - req)
        return (p.entry_fill - m_per_q) / den
    den = 1.0 + req
    return (p.entry_fill + m_per_q) / den


def current_price(sym, t, field='close'):
    b = bars[sym]
    if t in b.index:
        return float(b.at[t, field])
    # Rare missing hour: use last completed trade-price bar.
    q = b.loc[:t]
    if q.empty: return np.nan
    return float(q.iloc[-1][field])


def equity_at(balance, active, t, adverse=False):
    u = 0.0
    for p in active.values():
        if t not in bars[p.symbol].index: continue
        row = bars[p.symbol].loc[t]
        if adverse:
            px = float(row.low if p.side == 1 else row.high)
        else:
            px = float(row.close)
        u += p.side * p.qty * (px - p.entry_fill)
    return balance + u


def gross_now(active, t):
    g = 0.0
    for p in active.values():
        px = current_price(p.symbol, t, 'open')
        if np.isfinite(px): g += p.qty * px
    return g


def heat_now(active):
    return sum(p.risk_dollars for p in active.values())


def margin_now(active):
    return sum(p.margin for p in active.values())


def close_position(p, px_raw, reason, slip, balance, trades, t):
    fill = slip_exit(float(px_raw), p.side, slip)
    pnl = p.side * p.qty * (fill - p.entry_fill)
    fee = p.qty * fill * WEEX_TAKER
    balance += pnl - fee
    trades.append(dict(tid=p.tid, symbol=p.symbol, side=p.side, entry_time=p.entry_time,
                       exit_time=t, entry_fill=p.entry_fill, exit_fill=fill, reason=reason,
                       pnl=pnl, exit_fee=fee, net_dollars=pnl-fee,
                       init_notional=p.init_notional, risk_dollars=p.risk_dollars))
    return balance


def simulate(name, cfg, slip_bps, mmr_scenario, margin_mode):
    slip = slip_bps / 10000.0
    balance = INITIAL
    active = {}
    accepted = skipped = liquidations = gap_stops = 0
    peak_gross = peak_margin = peak_heat = 0.0
    peak_eq = INITIAL
    dd_close = dd_adverse = 0.0
    min_eq = INITIAL
    max_single_gap_R = 0.0
    total_entry_fees = total_funding = 0.0
    trades = []

    for t in HOURS:
        # Entries occur on the next 4H open. Position sizing uses current MTM equity.
        for r in entries_at.get(t, []):
            if r.symbol in active: continue
            eq = equity_at(balance, active, t, adverse=False)
            if eq <= 0: continue
            raw_open = current_price(r.symbol, t, 'open')
            if not np.isfinite(raw_open): continue
            entry_fill = slip_entry(raw_open, int(r.side), slip)
            stop_dist_frac = abs(entry_fill - float(r.stop)) / entry_fill
            if stop_dist_frac <= 0: continue
            risk_dollars = cfg['risk'] * eq
            notional = risk_dollars / stop_dist_frac
            qty = notional / entry_fill
            margin = notional / cfg['lev']
            gross = gross_now(active, t)
            heat = heat_now(active)
            used_margin = margin_now(active)
            entry_fee = notional * WEEX_TAKER
            if (len(active) >= cfg['max_pos'] or gross + notional > cfg['gross'] * eq + 1e-12 or
                heat + risk_dollars > cfg['heat'] * eq + 1e-12 or used_margin + margin + entry_fee > eq + 1e-12):
                skipped += 1
                continue
            mmr = mmr_for(r.symbol, mmr_scenario)
            p = Position(int(r.id), r.symbol, int(r.side), qty, entry_fill, float(r.intended_entry),
                         float(r.stop), pd.Timestamp(r.entry_time), pd.Timestamp(r.planned_exit_time),
                         str(r.planned_reason), risk_dollars, notional, margin,
                         margin - entry_fee, mmr)
            balance -= entry_fee
            total_entry_fees += entry_fee
            active[p.symbol] = p
            accepted += 1
            peak_gross = max(peak_gross, (gross + notional) / max(eq, 1e-12))
            peak_heat = max(peak_heat, (heat + risk_dollars) / max(eq, 1e-12))
            peak_margin = max(peak_margin, (used_margin + margin) / max(eq, 1e-12))

        # Funding at exact published event times from Binance historical data (proxy only).
        for sym, rate in fund_at.get(t, []):
            p = active.get(sym)
            if p is None or not (p.entry_time < t): continue
            px = current_price(sym, t, 'open')
            if not np.isfinite(px): continue
            fund = -p.side * rate * p.qty * px
            balance += fund
            total_funding += fund
            if margin_mode == 'ISOLATED':
                p.iso_margin_balance += fund

        # Hourly risk/execution checks.
        to_remove = []
        for sym, p in list(active.items()):
            if t not in bars[sym].index: continue
            row = bars[sym].loc[t]
            op, hi, lo, cl = map(float, [row.open, row.high, row.low, row.close])

            # Isolated liquidation uses WEEX public formula boundary MMR + close-fee reserve.
            liq = iso_liq_price(p) if margin_mode == 'ISOLATED' else None
            if margin_mode == 'ISOLATED':
                gap_liq = (p.side == 1 and op <= liq) or (p.side == -1 and op >= liq)
                if gap_liq:
                    balance = close_position(p, op, 'LIQ_GAP', slip, balance, trades, t)
                    liquidations += 1; to_remove.append(sym); continue

            # Gap through stop: fill at the worse hour open, not at the stop.
            gap_stop = (p.side == 1 and op <= p.stop) or (p.side == -1 and op >= p.stop)
            if gap_stop:
                pre = balance
                balance = close_position(p, op, 'STOP_GAP', slip, balance, trades, t)
                gap_stops += 1
                loss = max(0.0, pre - balance)
                max_single_gap_R = max(max_single_gap_R, loss / max(p.risk_dollars, 1e-12))
                to_remove.append(sym); continue

            # Intrahour: the nearer adverse trigger is reached first.
            stop_touch = (p.side == 1 and lo <= p.stop) or (p.side == -1 and hi >= p.stop)
            liq_touch = False
            if margin_mode == 'ISOLATED':
                liq_touch = (p.side == 1 and lo <= liq) or (p.side == -1 and hi >= liq)
            if liq_touch:
                liq_first = (p.side == 1 and liq >= p.stop) or (p.side == -1 and liq <= p.stop)
                if liq_first:
                    balance = close_position(p, liq, 'LIQ', slip, balance, trades, t)
                    liquidations += 1; to_remove.append(sym); continue
            if stop_touch:
                balance = close_position(p, p.stop, 'SL', slip, balance, trades, t)
                to_remove.append(sym); continue

            # Frozen channel/time exit happens at the planned 4H close.
            if t + pd.Timedelta(hours=1) >= p.planned_exit_time:
                balance = close_position(p, cl, p.planned_reason, slip, balance, trades,
                                         t + pd.Timedelta(hours=1))
                to_remove.append(sym); continue

        for sym in to_remove:
            active.pop(sym, None)

        # Conservative cross-margin liquidation diagnostic after stops have had priority.
        if margin_mode == 'CROSS' and active:
            worst_eq = equity_at(balance, active, t, adverse=True)
            maint = 0.0
            for p in active.values():
                if t not in bars[p.symbol].index: continue
                row = bars[p.symbol].loc[t]
                px = float(row.low if p.side == 1 else row.high)
                maint += p.qty * px * (p.mmr + CLOSE_FEE_RESERVE)
            if worst_eq <= maint:
                # Conservative all-position forced close at each symbol's adverse hourly extreme.
                for sym, p in list(active.items()):
                    row = bars[sym].loc[t]
                    px = float(row.low if p.side == 1 else row.high)
                    balance = close_position(p, px, 'CROSS_LIQ_STRESS', slip, balance, trades, t)
                    liquidations += 1
                active.clear()

        eq_close = equity_at(balance, active, t, adverse=False)
        eq_adv = equity_at(balance, active, t, adverse=True)
        min_eq = min(min_eq, eq_close, eq_adv)
        peak_eq = max(peak_eq, eq_close)
        dd_close = min(dd_close, eq_close / max(peak_eq, 1e-12) - 1.0)
        dd_adverse = min(dd_adverse, eq_adv / max(peak_eq, 1e-12) - 1.0)

        if balance <= 0 or eq_adv <= 0:
            # Keep the scenario as failed/bankrupt; no need to continue opening new risk.
            pass

    # Mark any positions still open at cutoff to final close for reporting only.
    final_t = HOURS[-1]
    final_eq = equity_at(balance, active, final_t, adverse=False)
    total = accepted + skipped
    td = pd.DataFrame(trades)
    return dict(tier=name, risk_pct=cfg['risk']*100, leverage=cfg['lev'], heat_cap_pct=cfg['heat']*100,
                gross_cap_pct=cfg['gross']*100, slip_bps_side=slip_bps, mmr_scenario=mmr_scenario,
                margin_mode=margin_mode, accepted=accepted, skipped=skipped,
                skip_pct=100*skipped/max(total,1), closed_trades=len(td), final_equity=final_eq,
                return_pct=(final_eq/INITIAL-1)*100, mtm_dd_close_pct=dd_close*100,
                mtm_dd_adverse_pct=dd_adverse*100, min_mtm_equity=min_eq,
                liquidations=liquidations, gap_stops=gap_stops, max_gap_loss_R=max_single_gap_R,
                peak_gross_pct=peak_gross*100, peak_heat_pct=peak_heat*100,
                peak_margin_pct=peak_margin*100, entry_fees=total_entry_fees,
                funding_pnl=total_funding)


rows = []
for tier_name, cfg in TIERS.items():
    for slip_bps, mmr_scenario, margin_mode in itertools.product(SLIPPAGE_BPS, MMR_SCENARIOS, MARGIN_MODES):
        print('RUN', tier_name, slip_bps, mmr_scenario, margin_mode, flush=True)
        rows.append(simulate(tier_name, cfg, slip_bps, mmr_scenario, margin_mode))

out = pd.DataFrame(rows)
out.to_csv('donchian_v2_mtm_weex_stress.csv', index=False)

cols = ['tier','slip_bps_side','mmr_scenario','margin_mode','return_pct','mtm_dd_close_pct',
        'mtm_dd_adverse_pct','liquidations','gap_stops','max_gap_loss_R','skip_pct',
        'peak_gross_pct','peak_margin_pct','funding_pnl']
print('\nBASE MMR / ISOLATED')
print(out[(out.mmr_scenario=='BASE') & (out.margin_mode=='ISOLATED')][cols].to_string(index=False))
print('\nSTRESS 1% MMR / ISOLATED')
print(out[(out.mmr_scenario=='STRESS_1PCT') & (out.margin_mode=='ISOLATED')][cols].to_string(index=False))
print('\nBASE MMR / CROSS')
print(out[(out.mmr_scenario=='BASE') & (out.margin_mode=='CROSS')][cols].to_string(index=False))
