from __future__ import annotations

import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

EVAL_START = pd.Timestamp('2020-01-01', tz='UTC')
DEV_START = pd.Timestamp('2021-01-01', tz='UTC')
DEV_END = pd.Timestamp('2024-01-01', tz='UTC')
VAL_END = pd.Timestamp('2025-01-01', tz='UTC')
END = pd.Timestamp('2026-10-01', tz='UTC')
WARM_START = pd.Timestamp('2019-01-01', tz='UTC')
BASE_COST = 0.0012
STRESS_COST = 0.0024
ALLOC = 0.10
SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','BNBUSDT','DOGEUSDT','ADAUSDT','LINKUSDT']
OUT = Path('donchian_v2_repo_inspired_exact_output')
OUT.mkdir(exist_ok=True)

# Match the frozen v1 pipeline: download 1H Binance USD-M bars and resample to 4H.
KURL = 'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip'
FURL = 'https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip'


def months(a, b):
    x = pd.Timestamp(a.year, a.month, 1, tz='UTC')
    while x < b:
        yield x
        x = x + pd.offsets.MonthBegin(1)


def getzip(url):
    last = None
    for k in range(4):
        try:
            r = requests.get(url, timeout=45)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = next(n for n in z.namelist() if n.endswith('.csv'))
                return z.read(name)
        except Exception as e:
            last = e
            time.sleep(0.35 * (k + 1))
    raise RuntimeError(f'{url}: {last}')


def _bar(sym, m):
    ym = m.strftime('%Y-%m')
    raw = getzip(KURL.format(sym=sym, ym=ym))
    if raw is None:
        return ym, None
    d = pd.read_csv(io.BytesIO(raw), header=None)
    for c in range(6):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=list(range(6)))
    if d.empty:
        return ym, None
    unit = 'us' if float(d.iloc[0, 0]) >= 1e14 else 'ms'
    return ym, pd.DataFrame({
        'time':pd.to_datetime(d[0], unit=unit, utc=True, errors='coerce'),
        'open':d[1], 'high':d[2], 'low':d[3], 'close':d[4], 'volume':d[5]
    }).dropna()


def loadbars(sym):
    ms = list(months(WARM_START, END))
    pieces, missing = [], []
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs = [ex.submit(_bar, sym, m) for m in ms]
        for f in as_completed(fs):
            ym, p = f.result()
            if p is None: missing.append(ym)
            else: pieces.append(p)
    if not pieces:
        return pd.DataFrame(), sorted(missing)
    x = pd.concat(pieces, ignore_index=True).drop_duplicates('time').sort_values('time')
    x = x[(x.time >= WARM_START) & (x.time < END)].set_index('time')
    return x[['open','high','low','close','volume']], sorted(missing)


def _fund(sym, m):
    ym = m.strftime('%Y-%m')
    raw = getzip(FURL.format(sym=sym, ym=ym))
    if raw is None: return ym, None
    d = pd.read_csv(io.BytesIO(raw))
    d.columns = [str(c).strip().lower() for c in d.columns]
    if 'calc_time' not in d.columns or 'last_funding_rate' not in d.columns:
        d = pd.read_csv(io.BytesIO(raw), header=None, names=['calc_time','funding_interval_hours','last_funding_rate'])
    d['calc_time'] = pd.to_numeric(d.calc_time, errors='coerce')
    d['last_funding_rate'] = pd.to_numeric(d.last_funding_rate, errors='coerce')
    d = d.dropna(subset=['calc_time','last_funding_rate'])
    if d.empty: return ym, None
    unit = 'us' if float(d.iloc[0].calc_time) >= 1e14 else 'ms'
    d['time'] = pd.to_datetime(d.calc_time, unit=unit, utc=True, errors='coerce')
    return ym, d[['time','last_funding_rate']].dropna()


def loadfund(sym):
    ms = list(months(WARM_START, END))
    pieces, missing = [], []
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs = [ex.submit(_fund, sym, m) for m in ms]
        for f in as_completed(fs):
            ym, p = f.result()
            if p is None: missing.append(ym)
            else: pieces.append(p)
    if not pieces:
        return pd.DataFrame(columns=['time','last_funding_rate']), sorted(missing)
    d = pd.concat(pieces, ignore_index=True).drop_duplicates('time').sort_values('time')
    d = d[(d.time >= WARM_START) & (d.time < END)].copy()
    return d, sorted(missing)


def rma(s, n):
    return s.ewm(alpha=1/n, adjust=False, min_periods=n).mean()


def full_daily_features(raw):
    d = raw.resample('1D', label='left', closed='left').agg({'close':'last'}).dropna()
    d['ema20'] = d.close.ewm(span=20, adjust=False).mean()
    d['ema50'] = d.close.ewm(span=50, adjust=False).mean()
    d['ema200'] = d.close.ewm(span=200, adjust=False).mean()
    d['ema200_20ago'] = d.ema200.shift(20)
    # At any intraday signal, only the previous completed UTC daily bar is allowed.
    return d[['ema20','ema50','ema200','ema200_20ago']].shift(1)


def prep_segment(raw, funding, seg_start, seg_end, daily):
    # Frozen v1 starts each research segment with exactly 20 days of warmup.
    r = raw[(raw.index >= seg_start - pd.Timedelta(days=20)) & (raw.index < seg_end)].copy()
    q = r.resample('4h', origin='epoch', label='left', closed='left').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()
    pc = q.close.shift(1)
    tr = pd.concat([q.high-q.low, (q.high-pc).abs(), (q.low-pc).abs()], axis=1).max(axis=1)
    q['atr'] = rma(tr, 14)
    q['ema200'] = q.close.ewm(span=200, adjust=False).mean()
    q['volavg20_prior'] = q.volume.shift(1).rolling(20, min_periods=20).mean()
    for c in daily.columns:
        q['d_' + c] = daily[c].reindex(q.index, method='ffill')

    if funding.empty:
        q['last_funding'] = np.nan
    else:
        bt = pd.DataFrame({'bar_index':q.index, 'bar_close':q.index + pd.Timedelta(hours=4)}).sort_values('bar_close')
        ff = funding.rename(columns={'time':'fund_time'}).sort_values('fund_time')
        mg = pd.merge_asof(bt, ff[['fund_time','last_funding_rate']], left_on='bar_close', right_on='fund_time', direction='backward')
        mg.index = q.index
        q['last_funding'] = mg.last_funding_rate.to_numpy()
    return q[(q.index >= seg_start) & (q.index < seg_end)].copy()


def fund_arrays(f):
    if f.empty: return np.array([], dtype=np.int64), np.array([], float)
    return np.array([pd.Timestamp(t).value for t in f.time], dtype=np.int64), f.last_funding_rate.to_numpy(float)


def fsum(ft, fr, a, b):
    if len(ft) == 0: return 0.0
    ai = np.searchsorted(ft, pd.Timestamp(a).value, side='right')
    bi = np.searchsorted(ft, pd.Timestamp(b).value, side='right')
    return float(fr[ai:bi].sum()) if bi > ai else 0.0


@dataclass(frozen=True)
class V:
    name: str
    atrbuf: float = 0.0
    volmult: float = 0.0
    daily_slope: bool = False
    btc_macro: bool = False
    funding_gate: bool = False


def variants():
    return [
        V('BASE_V1'),
        V('ATRBUF_025', atrbuf=0.25),
        V('VOL_100', volmult=1.00),
        V('VOL_150', volmult=1.50),
        V('ATRBUF_025_VOL_100', atrbuf=0.25, volmult=1.00),
        V('DAILY_EMA200_SLOPE20', daily_slope=True),
        V('BTC_MACRO_20_50', btc_macro=True),
        V('FUNDING_GATE_5BP', funding_gate=True),
    ]


def simulate(sym, x, f, v, btc_daily_bull, btc_daily_bear):
    if x.empty: return pd.DataFrame()
    eh = x.high.shift(1).rolling(40, min_periods=40).max()
    el = x.low.shift(1).rolling(40, min_periods=40).min()
    atr_prior = x.atr.shift(1)
    long = (x.close > eh + v.atrbuf * atr_prior) & (x.close > x.ema200)
    short = (x.close < el - v.atrbuf * atr_prior) & (x.close < x.ema200)

    if v.volmult > 0:
        vok = x.volume >= v.volmult * x.volavg20_prior
        long &= vok; short &= vok
    if v.daily_slope:
        long &= x.d_ema200 > x.d_ema200_20ago
        short &= x.d_ema200 < x.d_ema200_20ago
    if v.btc_macro:
        long &= btc_daily_bull.reindex(x.index, method='ffill').fillna(False)
        short &= btc_daily_bear.reindex(x.index, method='ffill').fillna(False)
    if v.funding_gate:
        long &= ~(x.last_funding > 0.0005)
        short &= ~(x.last_funding < -0.0005)

    xh = x.high.shift(1).rolling(20, min_periods=20).max()
    xl = x.low.shift(1).rolling(20, min_periods=20).min()
    la = long.fillna(False).to_numpy(bool); sa = short.fillna(False).to_numpy(bool)
    o=x.open.to_numpy(float); h=x.high.to_numpy(float); l=x.low.to_numpy(float)
    c=x.close.to_numpy(float); a=x.atr.to_numpy(float); ix=x.index
    ft,fr = fund_arrays(f); out=[]; pos=None; pend=None

    for i in range(len(x)):
        if pos is None and pend is not None:
            si,side,a0 = pend
            if i > si and np.isfinite(a0) and a0 > 0:
                e=o[i]; pos={'side':side,'e':e,'et':ix[i],'sl':e-side*2*a0,'bars':0}
            pend=None
        if pos is not None:
            pos['bars'] += 1; side=pos['side']; xp=None; reason=None
            if side==1 and l[i] <= pos['sl']: xp=pos['sl']; reason='SL'
            elif side==-1 and h[i] >= pos['sl']: xp=pos['sl']; reason='SL'
            elif side==1 and np.isfinite(xl.iloc[i]) and c[i] < xl.iloc[i]: xp=c[i]; reason='CHANNEL'
            elif side==-1 and np.isfinite(xh.iloc[i]) and c[i] > xh.iloc[i]: xp=c[i]; reason='CHANNEL'
            elif pos['bars'] >= 60: xp=c[i]; reason='TIME'
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=4)
                rawret=side*(xp-pos['e'])/pos['e']
                fundret=-side*fsum(ft,fr,pos['et'],xt)
                out.append({'symbol':sym,'variant':v.name,'side':'LONG' if side==1 else 'SHORT',
                            'entry_time':pos['et'],'exit_time':xt,'raw_ret':rawret,'funding_ret':fundret,
                            'hold_hours':(xt-pos['et']).total_seconds()/3600,'reason':reason})
                pos=None
        if pos is None and pend is None and i+1 < len(x):
            if la[i] and not sa[i]: pend=(i,1,a[i])
            elif sa[i] and not la[i]: pend=(i,-1,a[i])
    return pd.DataFrame(out)


def metrics(t,a,b,cost=BASE_COST,remove=0):
    empty={'trades':0,'wr':None,'pf':None,'ret':0.0,'dd':0.0,'tpw':0.0,'exp':None,'avg_hold':None,'max_loss_streak':0,'calmar_proxy':0.0}
    if t.empty: return empty
    et=pd.to_datetime(t.entry_time,utc=True); z=t[(et>=a)&(et<b)].copy()
    if z.empty: return empty
    z['net']=z.raw_ret+z.funding_ret-cost
    if remove: z=z.sort_values('net',ascending=False).iloc[remove:].copy()
    if z.empty: return empty
    eq=1.0; ps=[]; curve=[]; streak=mx=0
    for r in z.sort_values(['exit_time','entry_time']).itertuples():
        p=ALLOC*eq*float(r.net); eq+=p; ps.append(p); curve.append(eq)
        streak=0 if p>0 else streak+1; mx=max(mx,streak)
    p=np.asarray(ps); gp=p[p>0].sum(); gl=-p[p<0].sum(); arr=np.asarray(curve)
    dd=float((arr/np.maximum.accumulate(arr)-1).min()*100); ret=float((eq-1)*100)
    weeks=max((b-a).total_seconds()/604800,1e-9)
    return {'trades':len(z),'wr':float((p>0).mean()*100),'pf':float(gp/gl) if gl>0 else None,
            'ret':ret,'dd':dd,'tpw':float(len(z)/weeks),'exp':float(z.net.mean()*100),
            'avg_hold':float(z.hold_hours.mean()),'max_loss_streak':mx,
            'calmar_proxy':float(ret/abs(dd)) if dd<0 else None}


def evaluate_pass(row,base):
    reasons=[]
    if row['test_pf'] is None or row['test_pf'] < base['test_pf']: reasons.append('test_pf<baseline')
    if row['test_stress_pf'] is None or row['test_stress_pf'] < 1.10: reasons.append('stress_pf<1.10')
    if row['val_pf'] is None or row['val_pf'] < 1.15: reasons.append('val_pf<1.15')
    if row['pre_pf'] is None or row['pre_pf'] < 1.10: reasons.append('pre2020_pf<1.10')
    if row['variant']!='DAILY_EMA200_SLOPE20' and row['pre_trades'] < 0.70*base['pre_trades']: reasons.append('pre2020_trades<70%')
    if row['full_trades'] < 0.70*base['full_trades']: reasons.append('full_trades<70%')
    if row['test_remove_top3_pf'] is None or row['test_remove_top3_pf'] < 1.05: reasons.append('remove_top3_pf<1.05')
    if row['pf_2022'] is None or row['pf_2022'] < 1.0: reasons.append('PF2022<1')
    if row['pf_2025'] is None or row['pf_2025'] < 1.0: reasons.append('PF2025<1')
    if row['test_dd'] < base['test_dd']*1.10: reasons.append('test_dd>10% worse')
    return len(reasons)==0,';'.join(reasons)


def main():
    raw_map={}; fund_map={}; daily_map={}; meta={}
    for sym in SYMS:
        print('LOAD',sym,flush=True)
        raw,km=loadbars(sym); f,fm=loadfund(sym)
        raw_map[sym]=raw; fund_map[sym]=f; daily_map[sym]=full_daily_features(raw) if not raw.empty else pd.DataFrame()
        meta[sym]={'bars1h':len(raw),'first':str(raw.index.min()) if len(raw) else None,'last':str(raw.index.max()) if len(raw) else None,
                   'fund_rows':len(f),'kline_missing':km,'funding_missing':fm}

    btc_daily=daily_map['BTCUSDT']
    btc_bull=(btc_daily.ema20>btc_daily.ema50).fillna(False)
    btc_bear=(btc_daily.ema20<btc_daily.ema50).fillna(False)

    pools={v.name:[] for v in variants()}
    for sym in SYMS:
        raw=raw_map[sym]
        if raw.empty: continue
        # Reproduce the two original independent indicator states exactly.
        segs=[prep_segment(raw,fund_map[sym],EVAL_START,DEV_START,daily_map[sym]),
              prep_segment(raw,fund_map[sym],DEV_START,END,daily_map[sym])]
        for seg_no,x in enumerate(segs):
            if seg_no==0 and len(x)<250:
                continue  # exact holdout availability rule
            for v in variants():
                t=simulate(sym,x,fund_map[sym],v,btc_bull,btc_bear)
                if not t.empty: pools[v.name].append(t)

    rows=[]; yearly=[]; pair=[]; alltr=[]
    for v in variants():
        t=pd.concat(pools[v.name],ignore_index=True) if pools[v.name] else pd.DataFrame()
        if not t.empty: alltr.append(t)
        pre=metrics(t,EVAL_START,DEV_START); dev=metrics(t,DEV_START,DEV_END); val=metrics(t,DEV_END,VAL_END)
        test=metrics(t,VAL_END,END); full=metrics(t,DEV_START,END); stress=metrics(t,VAL_END,END,STRESS_COST); rm=metrics(t,VAL_END,END,BASE_COST,3)
        yr={}
        for y in range(2020,2027):
            aa=max(EVAL_START,pd.Timestamp(f'{y}-01-01',tz='UTC')); bb=min(END,pd.Timestamp(f'{y+1}-01-01',tz='UTC'))
            if aa<bb:
                m=metrics(t,aa,bb); yr[y]=m; yearly.append({'variant':v.name,'year':y,**m})
        row={'variant':v.name,**{'pre_'+k:q for k,q in pre.items()},**{'dev_'+k:q for k,q in dev.items()},
             **{'val_'+k:q for k,q in val.items()},**{'test_'+k:q for k,q in test.items()},**{'full_'+k:q for k,q in full.items()},
             'test_stress_pf':stress['pf'],'test_stress_ret':stress['ret'],'test_remove_top3_pf':rm['pf'],'test_remove_top3_ret':rm['ret'],
             'pf_2022':yr.get(2022,{}).get('pf'),'pf_2025':yr.get(2025,{}).get('pf')}
        rows.append(row)
        if not t.empty:
            for s in SYMS: pair.append({'variant':v.name,'symbol':s,**metrics(t[t.symbol==s],VAL_END,END)})

    rank=pd.DataFrame(rows); base=rank[rank.variant=='BASE_V1'].iloc[0].to_dict(); ok=[]; why=[]
    for r in rank.to_dict('records'):
        a,b=evaluate_pass(r,base); ok.append(a); why.append(b)
    rank['eligible']=ok; rank['fail_reasons']=why; rank['delta_test_pf']=rank.test_pf-float(base['test_pf']); rank['delta_test_ret']=rank.test_ret-float(base['test_ret']); rank['delta_test_dd']=rank.test_dd-float(base['test_dd'])
    rank=rank.sort_values(['eligible','delta_test_pf','test_calmar_proxy'],ascending=[False,False,False])
    rank.to_csv(OUT/'ranking.csv',index=False); pd.DataFrame(yearly).to_csv(OUT/'yearly.csv',index=False); pd.DataFrame(pair).to_csv(OUT/'test_by_pair.csv',index=False)
    if alltr: pd.concat(alltr,ignore_index=True).to_csv(OUT/'all_trades.csv',index=False)
    (OUT/'meta.json').write_text(json.dumps(meta,indent=2)); (OUT/'prereg_snapshot.json').write_text(json.dumps({'variants':[v.__dict__ for v in variants()]},indent=2))
    cols=['variant','eligible','pre_trades','pre_pf','dev_trades','dev_pf','dev_ret','val_trades','val_pf','val_ret','test_trades','test_pf','test_ret','test_dd','test_calmar_proxy','test_stress_pf','test_remove_top3_pf','pf_2022','pf_2025','delta_test_pf','fail_reasons']
    print(rank[cols].to_string(index=False)); print('\nBASELINE:',{k:base[k] for k in ['pre_trades','pre_pf','dev_trades','dev_pf','val_trades','val_pf','test_trades','test_pf']}); print('ELIGIBLE:',rank.loc[rank.eligible,'variant'].tolist())

if __name__=='__main__': main()
