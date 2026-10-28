from __future__ import annotations

import io, zipfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd
import requests

START = pd.Timestamp('2025-01-01', tz='UTC')
END = pd.Timestamp('2026-10-01', tz='UTC')
WARM = pd.Timestamp('2024-01-01', tz='UTC')
INITIAL = 100.0
COST = 0.0012
SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','BNBUSDT','DOGEUSDT','ADAUSDT','LINKUSDT']
CORE4 = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT']
KURL='https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip'
FURL='https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip'
OUT=Path('combined_portfolio_output'); OUT.mkdir(exist_ok=True)


def months(a,b):
    x=pd.Timestamp(a.year,a.month,1,tz='UTC')
    while x<b:
        yield x; x=x+pd.offsets.MonthBegin(1)

def getzip(url):
    for k in range(4):
        try:
            r=requests.get(url,timeout=45)
            if r.status_code==404:return None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                n=next(n for n in z.namelist() if n.endswith('.csv'))
                return z.read(n)
        except Exception:
            if k==3: raise
            time.sleep(.35*(k+1))

def _bar(sym,m):
    ym=m.strftime('%Y-%m'); raw=getzip(KURL.format(sym=sym,ym=ym))
    if raw is None:return None
    d=pd.read_csv(io.BytesIO(raw),header=None)
    for c in range(6): d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.dropna(subset=list(range(6)))
    if d.empty:return None
    unit='us' if float(d.iloc[0,0])>=1e14 else 'ms'
    return pd.DataFrame({'time':pd.to_datetime(d[0],unit=unit,utc=True),'open':d[1],'high':d[2],'low':d[3],'close':d[4],'volume':d[5]})

def loadbars(sym):
    parts=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs=[ex.submit(_bar,sym,m) for m in months(WARM,END)]
        for f in as_completed(fs):
            p=f.result()
            if p is not None: parts.append(p)
    x=pd.concat(parts,ignore_index=True).drop_duplicates('time').sort_values('time').set_index('time')
    return x[(x.index>=WARM)&(x.index<END)]

def _fund(sym,m):
    ym=m.strftime('%Y-%m'); raw=getzip(FURL.format(sym=sym,ym=ym))
    if raw is None:return None
    d=pd.read_csv(io.BytesIO(raw)); d.columns=[str(c).strip().lower() for c in d.columns]
    if 'calc_time' not in d.columns or 'last_funding_rate' not in d.columns:
        d=pd.read_csv(io.BytesIO(raw),header=None,names=['calc_time','funding_interval_hours','last_funding_rate'])
    d['calc_time']=pd.to_numeric(d.calc_time,errors='coerce'); d['last_funding_rate']=pd.to_numeric(d.last_funding_rate,errors='coerce')
    d=d.dropna(subset=['calc_time','last_funding_rate'])
    if d.empty:return None
    unit='us' if float(d.iloc[0].calc_time)>=1e14 else 'ms'
    return pd.DataFrame({'time':pd.to_datetime(d.calc_time,unit=unit,utc=True),'rate':d.last_funding_rate.astype(float)})

def loadfund(sym):
    parts=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs=[ex.submit(_fund,sym,m) for m in months(WARM,END)]
        for f in as_completed(fs):
            p=f.result()
            if p is not None:parts.append(p)
    if not parts:return pd.DataFrame(columns=['time','rate'])
    return pd.concat(parts,ignore_index=True).drop_duplicates('time').sort_values('time')

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def atr(df,n=14):
    pc=df.close.shift(1)
    tr=pd.concat([df.high-df.low,(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
    return rma(tr,n)
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    au=rma(up,n); ad=rma(dn,n); rs=au/ad.replace(0,np.nan)
    return 100-(100/(1+rs))

def fsum(f,a,b):
    if f.empty:return 0.0
    t=f.time.astype('int64').to_numpy(); r=f.rate.to_numpy(float)
    av=pd.Timestamp(a).value; bv=pd.Timestamp(b).value
    i=np.searchsorted(t,av,side='right'); j=np.searchsorted(t,bv,side='right')
    return float(r[i:j].sum()) if j>i else 0.0

print('loading data',flush=True)
B={}; F={}
for s in SYMS:
    print('LOAD',s,flush=True); B[s]=loadbars(s); F[s]=loadfund(s)


def mk_trade(strategy,sym,side,et,xt,e,xp,stopfrac):
    raw=side*(xp-e)/e; fund=-side*fsum(F[sym],et,xt); net=raw+fund-COST
    return dict(strategy=strategy,symbol=sym,side=side,entry_time=et,exit_time=xt,entry=e,exit=xp,raw_ret=raw,funding_ret=fund,net_ret=net,stop_frac=stopfrac)


def momentum_trades(sym):
    q=B[sym].resample('6h',origin='epoch',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    q['atr']=atr(q); q['ema100']=q.close.ewm(span=100,adjust=False).mean(); q['mom']=q.close/q.close.shift(10)-1
    q['slope']=q.ema100-q.ema100.shift(3); q['atrp']=q.atr/q.close; q['volmed']=q.atrp.rolling(100,min_periods=100).median()
    long=(q.mom>0.02)&(q.close>q.ema100)&(q.slope>0)&(q.atrp>=q.volmed)
    short=(q.mom<-0.02)&(q.close<q.ema100)&(q.slope<0)&(q.atrp>=q.volmed)
    o=q.open.to_numpy(float); h=q.high.to_numpy(float); l=q.low.to_numpy(float); c=q.close.to_numpy(float); a=q.atr.to_numpy(float); ix=q.index
    la=long.fillna(False).to_numpy(bool); sa=short.fillna(False).to_numpy(bool); out=[]; pos=None; pend=None
    for i in range(len(q)):
        if pos is None and pend is not None:
            si,side,a0=pend
            if i>si and np.isfinite(a0):
                e=o[i]; st=e-side*2.5*a0; pos={'side':side,'e':e,'et':ix[i],'stop':st,'a0':a0}
            pend=None
        if pos is not None:
            side=pos['side']; xp=None
            if side==1 and l[i]<=pos['stop']: xp=pos['stop']
            elif side==-1 and h[i]>=pos['stop']: xp=pos['stop']
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=6); out.append(mk_trade('MOM6H',sym,side,pos['et'],xt,pos['e'],xp,2.5*pos['a0']/pos['e'])); pos=None
            else:
                cand=c[i]-side*2.5*a[i]
                if side==1: pos['stop']=max(pos['stop'],cand)
                else: pos['stop']=min(pos['stop'],cand)
        if pos is None and pend is None and i+1<len(q):
            if la[i] and not sa[i]:pend=(i,1,a[i])
            elif sa[i] and not la[i]:pend=(i,-1,a[i])
    return out


def eth_squeeze_trades():
    x=B['ETHUSDT'].copy(); btc=B['BTCUSDT'].reindex(x.index)
    x['atr']=atr(x); x['ema100']=x.close.ewm(span=100,adjust=False).mean(); btcema=btc.close.ewm(span=100,adjust=False).mean()
    basis=x.close.rolling(20).mean(); sd=x.close.rolling(20).std(ddof=0); bbu=basis+2*sd; bbl=basis-2*sd
    ema20=x.close.ewm(span=20,adjust=False).mean(); kcu=ema20+1.5*x.atr; kcl=ema20-1.5*x.atr
    sq=(bbu<kcu)&(bbl>kcl); recent=sq.shift(1).rolling(8,min_periods=1).max().fillna(0)>0
    hi20=x.high.shift(1).rolling(20).max(); vavg=x.volume.shift(1).rolling(20).mean(); quality=(x.close-x.low)/(x.high-x.low).replace(0,np.nan)
    sig=recent&(x.close>x.ema100)&(x.volume>1.2*vavg)&(x.close>hi20+0.15*x.atr)&(quality>=0.70)&(btc.close>btcema)
    o=x.open.to_numpy(float);h=x.high.to_numpy(float);l=x.low.to_numpy(float);c=x.close.to_numpy(float);a=x.atr.to_numpy(float);ix=x.index; sg=sig.fillna(False).to_numpy(bool)
    out=[];pos=None;pend=None
    for i in range(len(x)):
        if pos is None and pend is not None:
            si,a0=pend
            if i>si and np.isfinite(a0):
                e=o[i];pos={'e':e,'et':ix[i],'stop':e-1.5*a0,'a0':a0,'bars':0}
            pend=None
        if pos is not None:
            pos['bars']+=1;xp=None
            if l[i]<=pos['stop']:xp=pos['stop']
            elif pos['bars']>=64:xp=c[i]
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=1);out.append(mk_trade('ETH_SQ_V3','ETHUSDT',1,pos['et'],xt,pos['e'],xp,1.5*pos['a0']/pos['e']));pos=None
            else: pos['stop']=max(pos['stop'],c[i]-2*a[i])
        if pos is None and pend is None and i+1<len(x) and sg[i]:pend=(i,a[i])
    return out


def xrp_mr_trades():
    x=B['XRPUSDT'].copy(); x['atr']=atr(x);x['ema200']=x.close.ewm(span=200,adjust=False).mean();x['rsi']=rsi(x.close)
    lo=(x.rsi<30)&(x.close>x.ema200); sh=(x.rsi>70)&(x.close<x.ema200)
    o=x.open.to_numpy(float);h=x.high.to_numpy(float);l=x.low.to_numpy(float);c=x.close.to_numpy(float);a=x.atr.to_numpy(float);rv=x.rsi.to_numpy(float);ix=x.index
    la=lo.fillna(False).to_numpy(bool);sa=sh.fillna(False).to_numpy(bool);out=[];pos=None;pend=None
    for i in range(len(x)):
        if pos is None and pend is not None:
            si,side,a0=pend
            if i>si and np.isfinite(a0):
                e=o[i];pos={'side':side,'e':e,'et':ix[i],'stop':e-side*2*a0,'a0':a0,'bars':0}
            pend=None
        if pos is not None:
            pos['bars']+=1;side=pos['side'];xp=None
            if side==1 and l[i]<=pos['stop']:xp=pos['stop']
            elif side==-1 and h[i]>=pos['stop']:xp=pos['stop']
            elif side==1 and rv[i]>=50:xp=c[i]
            elif side==-1 and rv[i]<=50:xp=c[i]
            elif pos['bars']>=24:xp=c[i]
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=1);out.append(mk_trade('XRP_MR_V1','XRPUSDT',side,pos['et'],xt,pos['e'],xp,2*pos['a0']/pos['e']));pos=None
        if pos is None and pend is None and i+1<len(x):
            if la[i] and not sa[i]:pend=(i,1,a[i])
            elif sa[i] and not la[i]:pend=(i,-1,a[i])
    return out


def donchian_trades(sym):
    q=B[sym].resample('4h',origin='epoch',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    q['atr']=atr(q);q['ema200']=q.close.ewm(span=200,adjust=False).mean();eh=q.high.shift(1).rolling(40).max();el=q.low.shift(1).rolling(40).min();xh=q.high.shift(1).rolling(20).max();xl=q.low.shift(1).rolling(20).min()
    lo=(q.close>eh)&(q.close>q.ema200);sh=(q.close<el)&(q.close<q.ema200)
    o=q.open.to_numpy(float);h=q.high.to_numpy(float);l=q.low.to_numpy(float);c=q.close.to_numpy(float);a=q.atr.to_numpy(float);ix=q.index
    la=lo.fillna(False).to_numpy(bool);sa=sh.fillna(False).to_numpy(bool);out=[];pos=None;pend=None
    for i in range(len(q)):
        if pos is None and pend is not None:
            si,side,a0=pend
            if i>si and np.isfinite(a0):
                e=o[i];pos={'side':side,'e':e,'et':ix[i],'stop':e-side*2*a0,'a0':a0,'bars':0}
            pend=None
        if pos is not None:
            pos['bars']+=1;side=pos['side'];xp=None
            if side==1 and l[i]<=pos['stop']:xp=pos['stop']
            elif side==-1 and h[i]>=pos['stop']:xp=pos['stop']
            elif side==1 and np.isfinite(xl.iloc[i]) and c[i]<xl.iloc[i]:xp=c[i]
            elif side==-1 and np.isfinite(xh.iloc[i]) and c[i]>xh.iloc[i]:xp=c[i]
            elif pos['bars']>=60:xp=c[i]
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=4);out.append(mk_trade('DONCHIAN_V1',sym,side,pos['et'],xt,pos['e'],xp,2*pos['a0']/pos['e']));pos=None
        if pos is None and pend is None and i+1<len(q):
            if la[i] and not sa[i]:pend=(i,1,a[i])
            elif sa[i] and not la[i]:pend=(i,-1,a[i])
    return out

print('generate templates',flush=True)
tr=[]
for s in CORE4: tr.extend(momentum_trades(s))
tr.extend(eth_squeeze_trades());tr.extend(xrp_mr_trades())
for s in SYMS: tr.extend(donchian_trades(s))
T=pd.DataFrame(tr);T=T[(T.entry_time>=START)&(T.entry_time<END)].sort_values(['entry_time','strategy','symbol']).reset_index(drop=True);T['id']=np.arange(len(T))
T.to_csv(OUT/'trade_templates.csv',index=False)
print(T.groupby('strategy').size(),flush=True)
print('Donchian locked-window count',len(T[T.strategy=='DONCHIAN_V1']),'expected approx 505',flush=True)

# Hourly close matrix for MTM.
H=pd.date_range(START,END-pd.Timedelta(hours=1),freq='1h',tz='UTC')
C={s:B[s].close.reindex(H).ffill() for s in SYMS}
entries={}; exits={}
for r in T.itertuples():
    entries.setdefault(pd.Timestamp(r.entry_time),[]).append(r); exits.setdefault(pd.Timestamp(r.exit_time),[]).append(r)


def run_portfolio(mode):
    bal=INITIAL; active={}; realized_by_strategy={}; accepted={}; skipped={}; conflicts=0
    peak=INITIAL; dd=0.; peakgross=0.; peakmargin=0.; peakheat=0.; maxpos=0; eqrows=[]; closed=[]
    day=None; day_start=INITIAL; day_realized=0.
    priority={'MOM6H':0,'ETH_SQ_V3':1,'XRP_MR_V1':2,'DONCHIAN_V1':3}
    for t in H:
        if day!=t.date(): day=t.date(); day_start=max(1e-9,bal+sum(p['notional']*p['side']*(float(C[p['symbol']].loc[t])-p['entry'])/p['entry'] for p in active.values())); day_realized=0.
        # exits first if exact hour
        for r in sorted(exits.get(t,[]),key=lambda z:priority[z.strategy]):
            p=active.pop(int(r.id),None)
            if p is None: continue
            pnl=p['notional']*float(r.net_ret); bal+=pnl; day_realized+=pnl
            realized_by_strategy[r.strategy]=realized_by_strategy.get(r.strategy,0)+pnl
            closed.append((r.strategy,r.symbol,t,pnl))
        # current mtm before entries
        def eq_now():
            u=0.
            for p in active.values():
                px=float(C[p['symbol']].loc[t]); u+=p['notional']*p['side']*(px-p['entry'])/p['entry']
            return bal+u
        for r in sorted(entries.get(t,[]),key=lambda z:priority[z.strategy]):
            eq=max(eq_now(),1e-9)
            same=[p for p in active.values() if p['symbol']==r.symbol]
            if same and any(p['side']!=r.side for p in same): conflicts+=1
            if mode=='NATIVE':
                if r.strategy=='MOM6H':
                    if day_realized <= -0.03*day_start: skipped[r.strategy]=skipped.get(r.strategy,0)+1; continue
                    mom=[p for p in active.values() if p['strategy']=='MOM6H']
                    if len(mom)>=4 or sum(p['risk'] for p in mom)+0.03*eq>0.12*eq+1e-12: skipped[r.strategy]=skipped.get(r.strategy,0)+1; continue
                    risk=.03*eq; notional=risk/max(float(r.stop_frac),1e-9); lev=5.; irisk=risk
                elif r.strategy in ('ETH_SQ_V3','XRP_MR_V1'):
                    notional=.20*eq; lev=1.; irisk=notional*float(r.stop_frac)
                else:
                    notional=.10*eq; lev=1.; irisk=notional*float(r.stop_frac)
                # executable shared account constraint
                gross=sum(p['notional'] for p in active.values()); margin=sum(p['margin'] for p in active.values())
                if gross+notional>4.0*eq+1e-12 or margin+notional/lev>eq+1e-12:
                    skipped[r.strategy]=skipped.get(r.strategy,0)+1; continue
            else:
                risk=.005*eq; notional=risk/max(float(r.stop_frac),1e-9); lev=3.; irisk=risk
                gross=sum(p['notional'] for p in active.values()); margin=sum(p['margin'] for p in active.values()); heat=sum(p['risk'] for p in active.values())
                if len(active)>=8 or gross+notional>2.5*eq+1e-12 or heat+risk>0.04*eq+1e-12 or margin+notional/lev>0.80*eq+1e-12:
                    skipped[r.strategy]=skipped.get(r.strategy,0)+1; continue
            active[int(r.id)]={'strategy':r.strategy,'symbol':r.symbol,'side':int(r.side),'entry':float(r.entry),'notional':notional,'margin':notional/lev,'risk':irisk}
            accepted[r.strategy]=accepted.get(r.strategy,0)+1
        eq=eq_now(); peak=max(peak,eq); dd=min(dd,eq/peak-1); maxpos=max(maxpos,len(active))
        gross=sum(p['notional'] for p in active.values()); margin=sum(p['margin'] for p in active.values()); heat=sum(p['risk'] for p in active.values())
        peakgross=max(peakgross,gross/max(eq,1e-9));peakmargin=max(peakmargin,margin/max(eq,1e-9));peakheat=max(peakheat,heat/max(eq,1e-9))
        eqrows.append((t,eq,len(active),gross/max(eq,1e-9),margin/max(eq,1e-9),heat/max(eq,1e-9)))
    # force mark last, no artificial close for return; final equity includes unrealized
    eq=eqrows[-1][1]
    E=pd.DataFrame(eqrows,columns=['time','equity','positions','gross_frac','margin_frac','heat_frac'])
    E['ret']=E.equity.pct_change().fillna(0)
    ann=[]
    for y,g in E.groupby(E.time.dt.year):
        start=float(g.equity.iloc[0]);end=float(g.equity.iloc[-1]);pk=g.equity.cummax();yd=float((g.equity/pk-1).min()*100);ann.append((y,(end/start-1)*100,yd))
    return {'mode':mode,'final_equity':eq,'return_pct':(eq/INITIAL-1)*100,'dd_pct':dd*100,'peak_gross_pct':peakgross*100,'peak_margin_pct':peakmargin*100,'peak_heat_pct':peakheat*100,'max_positions':maxpos,'conflicts':conflicts,'accepted':accepted,'skipped':skipped,'contrib':realized_by_strategy,'equity':E,'annual':ann}

results=[]
for mode in ['NATIVE','EQUAL_RISK']:
    R=run_portfolio(mode);R['equity'].to_csv(OUT/f'equity_{mode}.csv',index=False)
    results.append({k:v for k,v in R.items() if k not in ('equity',)})
    print('\n',mode,R['final_equity'],R['return_pct'],R['dd_pct'],'maxpos',R['max_positions'],'gross',R['peak_gross_pct'],'margin',R['peak_margin_pct'],'heat',R['peak_heat_pct'],flush=True)
    print('accepted',R['accepted'],'skipped',R['skipped'],'contrib',R['contrib'],'conflicts',R['conflicts'],flush=True)
    print('annual',R['annual'],flush=True)

# YTD 2026 from portfolio equity path without resetting capital.
for mode in ['NATIVE','EQUAL_RISK']:
    e=pd.read_csv(OUT/f'equity_{mode}.csv',parse_dates=['time']); z=e[e.time>=pd.Timestamp('2026-01-01',tz='UTC')]
    if len(z):
        a=float(z.equity.iloc[0]); b=float(z.equity.iloc[-1]); dd=float((z.equity/z.equity.cummax()-1).min()*100); print('YTD2026',mode,(b/a-1)*100,dd,'start',a,'end',b,flush=True)

# Daily return correlations and realized contribution share.
eds={}
for mode in ['NATIVE','EQUAL_RISK']:
    e=pd.read_csv(OUT/f'equity_{mode}.csv',parse_dates=['time']).set_index('time').equity
    d=e.resample('1D').last().pct_change();eds[mode]=d

pd.DataFrame([{k:(v if not isinstance(v,(dict,list)) else str(v)) for k,v in r.items()} for r in results]).to_csv(OUT/'portfolio_summary.csv',index=False)
print('done',flush=True)
