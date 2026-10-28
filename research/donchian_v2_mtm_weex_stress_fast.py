from __future__ import annotations

import json
import itertools
import requests
import numpy as np
import pandas as pd

import donchian_v2_repo_inspired_exact as eng

START = pd.Timestamp('2021-01-01', tz='UTC')
END = pd.Timestamp('2026-10-01', tz='UTC')
INITIAL = 100.0
FALLBACK_TAKER = 0.0008
CLOSE_FEE_RESERVE = 0.0008

TIERS = {
    'CONTROLLED': dict(risk=0.0050, lev=3.0, heat=0.04, gross=2.50, max_pos=8),
    'AGGRESSIVE': dict(risk=0.0075, lev=4.0, heat=0.06, gross=3.00, max_pos=8),
    'VERY_AGGRESSIVE': dict(risk=0.0100, lev=5.0, heat=0.08, gross=4.00, max_pos=8),
}
SLIPPAGE_BPS = [0.0, 2.0, 5.0, 10.0]
PERIODS = {
    'FULL_2021_SEP26': (pd.Timestamp('2021-01-01', tz='UTC'), END),
    'RECENT_2025_SEP26': (pd.Timestamp('2025-01-01', tz='UTC'), END),
    'YTD_2026': (pd.Timestamp('2026-01-01', tz='UTC'), END),
}

# Live public WEEX configuration probe. These endpoints need no API key.
def get_weex_live_config():
    mmr = {}
    taker = {}
    raw = {}
    for sym in eng.SYMS:
        try:
            r = requests.get('https://api-contract.weex.com/capi/v3/market/riskLimits',
                             params={'symbol': sym}, timeout=15)
            r.raise_for_status(); j = r.json(); raw[sym] = {'riskLimits': j}
            row = next((x for x in j if str(x.get('symbol','')).upper() == sym), j[0] if j else None)
            if row and row.get('brackets'):
                b = sorted(row['brackets'], key=lambda x: float(x.get('notionalFloor',0)))[0]
                mmr[sym] = float(b['maintMarginRatio'])
        except Exception as e:
            raw.setdefault(sym, {})['riskLimits_error'] = repr(e)
        try:
            r = requests.get('https://api-contract.weex.com/capi/v3/market/exchangeInfo',
                             params={'symbol': sym}, timeout=15)
            r.raise_for_status(); j = r.json(); raw.setdefault(sym,{})['exchangeInfo'] = j
            ss = j.get('symbols', []) if isinstance(j, dict) else []
            row = next((x for x in ss if str(x.get('symbol','')).upper() == sym), ss[0] if ss else None)
            if row:
                taker[sym] = float(row.get('apiTakerFeeRate', row.get('takerFeeRate', FALLBACK_TAKER)))
        except Exception as e:
            raw.setdefault(sym, {})['exchangeInfo_error'] = repr(e)
    # Conservative fallbacks only if live public endpoints fail.
    for sym in eng.SYMS:
        if sym not in mmr:
            mmr[sym] = 0.0015 if sym in ('BTCUSDT','ETHUSDT') else 0.005
        if sym not in taker:
            taker[sym] = FALLBACK_TAKER
    return mmr, taker, raw

MMR_LIVE, TAKER_LIVE, WEEX_RAW = get_weex_live_config()
with open('weex_live_risk_config_20261028.json','w') as f:
    json.dump({'mmr_first_tier': MMR_LIVE, 'api_taker_fee': TAKER_LIVE, 'raw': WEEX_RAW}, f, indent=2, default=str)
print('WEEX MMR', MMR_LIVE, flush=True)
print('WEEX API TAKER', TAKER_LIVE, flush=True)

raw_map = {}; fund_map = {}; daily_map = {}
for sym in eng.SYMS:
    print('LOAD', sym, flush=True)
    raw, _ = eng.loadbars(sym); fund, _ = eng.loadfund(sym)
    raw_map[sym] = raw; fund_map[sym] = fund; daily_map[sym] = eng.full_daily_features(raw)

# Frozen Donchian v2 signal templates. Stop/channel/time logic is unchanged.
def templates_for(sym):
    x = eng.prep_segment(raw_map[sym], fund_map[sym], START, END, daily_map[sym])
    eh=x.high.shift(1).rolling(40,min_periods=40).max(); el=x.low.shift(1).rolling(40,min_periods=40).min(); ap=x.atr.shift(1)
    la=((x.close>eh+0.25*ap)&(x.close>x.ema200)).fillna(False).to_numpy(bool)
    sa=((x.close<el-0.25*ap)&(x.close<x.ema200)).fillna(False).to_numpy(bool)
    xh=x.high.shift(1).rolling(20,min_periods=20).max(); xl=x.low.shift(1).rolling(20,min_periods=20).min()
    o=x.open.to_numpy(float); h=x.high.to_numpy(float); l=x.low.to_numpy(float); c=x.close.to_numpy(float); a=x.atr.to_numpy(float); ix=x.index
    out=[]; pos=None; pend=None
    for i in range(len(x)):
        if pos is None and pend is not None:
            si,side,a0=pend
            if i>si and np.isfinite(a0) and a0>0:
                e=o[i]; pos={'side':side,'e':e,'et':ix[i],'stop':e-side*2*a0,'atr':a0,'bars':0}
            pend=None
        if pos is not None:
            pos['bars']+=1; side=pos['side']; xp=None; reason=None
            if side==1 and l[i]<=pos['stop']: xp=pos['stop']; reason='SL'
            elif side==-1 and h[i]>=pos['stop']: xp=pos['stop']; reason='SL'
            elif side==1 and np.isfinite(xl.iloc[i]) and c[i]<xl.iloc[i]: xp=c[i]; reason='CHANNEL'
            elif side==-1 and np.isfinite(xh.iloc[i]) and c[i]>xh.iloc[i]: xp=c[i]; reason='CHANNEL'
            elif pos['bars']>=60: xp=c[i]; reason='TIME'
            if xp is not None:
                out.append((sym,side,pos['et'],pos['e'],pos['stop'],pos['atr'],ix[i]+pd.Timedelta(hours=4),reason))
                pos=None
        if pos is None and pend is None and i+1<len(x):
            if la[i] and not sa[i]: pend=(i,1,a[i])
            elif sa[i] and not la[i]: pend=(i,-1,a[i])
    return out

TPL=[]
for sym in eng.SYMS: TPL.extend(templates_for(sym))
tpl=pd.DataFrame(TPL,columns=['symbol','side','entry_time','intended_entry','stop','atr','planned_exit_time','planned_reason'])
tpl=tpl.sort_values(['entry_time','symbol']).reset_index(drop=True); tpl['id']=np.arange(len(tpl))
tpl['risk_frac']=abs(tpl.intended_entry-tpl.stop)/tpl.intended_entry
tpl.to_csv('donchian_v2_mtm_templates_fast.csv',index=False)
print('TEMPLATES',len(tpl),'stop median%',tpl.risk_frac.median()*100,'p90%',tpl.risk_frac.quantile(.9)*100,'max%',tpl.risk_frac.max()*100,flush=True)

H=pd.date_range(START, END-pd.Timedelta(hours=1), freq='1h', tz='UTC')
N=len(H); HVAL=H.asi8; HMAP={int(v):i for i,v in enumerate(HVAL)}
S={s:i for i,s in enumerate(eng.SYMS)}; NS=len(S)
O=np.full((NS,N),np.nan); HI=np.full((NS,N),np.nan); LO=np.full((NS,N),np.nan); C=np.full((NS,N),np.nan)
for sym,si in S.items():
    z=raw_map[sym].reindex(H)
    O[si]=z.open.to_numpy(float); HI[si]=z.high.to_numpy(float); LO[si]=z.low.to_numpy(float); C[si]=z.close.to_numpy(float)

entries=[[] for _ in range(N)]
for r in tpl.itertuples():
    ei=HMAP.get(int(pd.Timestamp(r.entry_time).value)); xi=HMAP.get(int((pd.Timestamp(r.planned_exit_time)-pd.Timedelta(hours=1)).value))
    if ei is not None and xi is not None:
        entries[ei].append((int(r.id),S[r.symbol],int(r.side),float(r.intended_entry),float(r.stop),xi,str(r.planned_reason)))

funds=[[] for _ in range(N)]
for sym,f in fund_map.items():
    si=S[sym]
    if f.empty: continue
    z=f[(f.time>=START)&(f.time<END)]
    for r in z.itertuples():
        ii=HMAP.get(int(pd.Timestamp(r.time).value))
        if ii is not None: funds[ii].append((si,float(r.last_funding_rate)))

# Position dict fields: tid,si,side,qty,entry,stop,entry_i,exit_i,reason,risk,notional,margin,iso_margin,mmr,taker

def eq_at(balance, active, i, adverse=False):
    u=0.0
    for p in active.values():
        si=p['si']; px=(LO[si,i] if p['side']==1 else HI[si,i]) if adverse else C[si,i]
        if np.isfinite(px): u += p['side']*p['qty']*(px-p['entry'])
    return balance+u

def gross_at(active,i):
    g=0.0
    for p in active.values():
        px=O[p['si'],i]
        if np.isfinite(px): g+=p['qty']*px
    return g

def iso_liq(p):
    req=p['mmr']+p['taker']
    mq=p['iso_margin']/p['qty']
    if p['side']==1: return (p['entry']-mq)/max(1e-12,1-req)
    return (p['entry']+mq)/(1+req)

def xfill(px,side,slip): return px*(1-side*slip)

def closep(balance,p,rawpx,reason,slip):
    fill=xfill(rawpx,p['side'],slip); pnl=p['side']*p['qty']*(fill-p['entry']); fee=p['qty']*fill*p['taker']
    return balance+pnl-fee, pnl-fee, fill

def sim(tier,cfg,slip_bps,mmr_mode,margin_mode,a,b):
    ai=HMAP[int(a.value)]; bi=HMAP.get(int(b.value),N)
    slip=slip_bps/10000.; balance=INITIAL; active={}; acc=skip=liq=gap=0
    pg=ph=pm=0.; peak=INITIAL; ddc=dda=0.; mineq=INITIAL; maxgapR=0.; fees=0.; fundp=0.; closed=0
    for i in range(ai,bi):
        # entries
        for tid,si,side,intended,stop,exit_i,preason in entries[i]:
            if si in active: continue
            eq=eq_at(balance,active,i,False)
            op=O[si,i]
            if eq<=0 or not np.isfinite(op): continue
            entry=op*(1+side*slip); stopfrac=abs(entry-stop)/entry
            if stopfrac<=0: continue
            risk=cfg['risk']*eq; notional=risk/stopfrac; qty=notional/entry; margin=notional/cfg['lev']
            gross=gross_at(active,i); heat=sum(p['risk'] for p in active.values()); marg=sum(p['margin'] for p in active.values())
            sym=eng.SYMS[si]; taker=TAKER_LIVE[sym]; efee=notional*taker
            if len(active)>=cfg['max_pos'] or gross+notional>cfg['gross']*eq+1e-12 or heat+risk>cfg['heat']*eq+1e-12 or marg+margin+efee>eq+1e-12:
                skip+=1; continue
            mmr=0.01 if mmr_mode=='STRESS_1PCT' else MMR_LIVE[sym]
            active[si]={'tid':tid,'si':si,'side':side,'qty':qty,'entry':entry,'stop':stop,'entry_i':i,'exit_i':exit_i,'reason':preason,
                        'risk':risk,'notional':notional,'margin':margin,'iso_margin':margin-efee,'mmr':mmr,'taker':taker}
            balance-=efee; fees+=efee; acc+=1
            pg=max(pg,(gross+notional)/max(eq,1e-12)); ph=max(ph,(heat+risk)/max(eq,1e-12)); pm=max(pm,(marg+margin)/max(eq,1e-12))
        # funding proxy, excluding exact entry timestamp
        for si,rate in funds[i]:
            p=active.get(si)
            if p is None or p['entry_i']>=i: continue
            px=O[si,i]
            if not np.isfinite(px): continue
            f=-p['side']*rate*p['qty']*px; balance+=f; fundp+=f
            if margin_mode=='ISOLATED': p['iso_margin']+=f
        # risk/exits
        rem=[]
        for si,p in list(active.items()):
            op,hi,lo,cl=O[si,i],HI[si,i],LO[si,i],C[si,i]
            if not np.all(np.isfinite([op,hi,lo,cl])): continue
            lp=iso_liq(p) if margin_mode=='ISOLATED' else np.nan
            if margin_mode=='ISOLATED' and ((p['side']==1 and op<=lp) or (p['side']==-1 and op>=lp)):
                balance,net,_=closep(balance,p,op,'LIQ_GAP',slip); liq+=1; closed+=1; rem.append(si); continue
            if (p['side']==1 and op<=p['stop']) or (p['side']==-1 and op>=p['stop']):
                pre=balance; balance,net,_=closep(balance,p,op,'STOP_GAP',slip); gap+=1; closed+=1
                maxgapR=max(maxgapR,max(0.,pre-balance)/max(p['risk'],1e-12)); rem.append(si); continue
            stopt=(p['side']==1 and lo<=p['stop']) or (p['side']==-1 and hi>=p['stop'])
            liqt=margin_mode=='ISOLATED' and ((p['side']==1 and lo<=lp) or (p['side']==-1 and hi>=lp))
            if liqt and ((p['side']==1 and lp>=p['stop']) or (p['side']==-1 and lp<=p['stop'])):
                balance,net,_=closep(balance,p,lp,'LIQ',slip); liq+=1; closed+=1; rem.append(si); continue
            if stopt:
                balance,net,_=closep(balance,p,p['stop'],'SL',slip); closed+=1; rem.append(si); continue
            if i>=p['exit_i']:
                balance,net,_=closep(balance,p,cl,p['reason'],slip); closed+=1; rem.append(si); continue
        for si in rem: active.pop(si,None)
        # conservative cross-margin hourly-extreme diagnostic
        if margin_mode=='CROSS' and active:
            weq=eq_at(balance,active,i,True); maint=0.
            for p in active.values():
                px=LO[p['si'],i] if p['side']==1 else HI[p['si'],i]
                if np.isfinite(px): maint += p['qty']*px*(p['mmr']+p['taker'])
            if weq<=maint:
                for si,p in list(active.items()):
                    px=LO[si,i] if p['side']==1 else HI[si,i]
                    balance,_,_=closep(balance,p,px,'CROSS_LIQ_STRESS',slip); liq+=1; closed+=1
                active.clear()
        ec=eq_at(balance,active,i,False); ea=eq_at(balance,active,i,True)
        peak=max(peak,ec); ddc=min(ddc,ec/max(peak,1e-12)-1); dda=min(dda,ea/max(peak,1e-12)-1); mineq=min(mineq,ec,ea)
    final=eq_at(balance,active,bi-1,False) if bi>ai else balance
    tot=acc+skip
    return dict(period='',tier=tier,risk_pct=cfg['risk']*100,leverage=cfg['lev'],slip_bps_side=slip_bps,mmr_mode=mmr_mode,margin_mode=margin_mode,
                return_pct=(final/INITIAL-1)*100,final_equity=final,mtm_dd_close_pct=ddc*100,mtm_dd_adverse_pct=dda*100,min_mtm_equity=mineq,
                accepted=acc,skipped=skip,skip_pct=100*skip/max(1,tot),closed=closed,liquidations=liq,gap_stops=gap,max_gap_loss_R=maxgapR,
                peak_gross_pct=pg*100,peak_heat_pct=ph*100,peak_margin_pct=pm*100,funding_pnl=fundp)

rows=[]
for pname,(a,b) in PERIODS.items():
    for tname,cfg in TIERS.items():
        for slip,mmr,mode in itertools.product(SLIPPAGE_BPS,['LIVE','STRESS_1PCT'],['ISOLATED','CROSS']):
            print('RUN',pname,tname,slip,mmr,mode,flush=True)
            d=sim(tname,cfg,slip,mmr,mode,a,b); d['period']=pname; rows.append(d)
out=pd.DataFrame(rows); out.to_csv('donchian_v2_mtm_weex_stress_fast.csv',index=False)
cols=['period','tier','slip_bps_side','mmr_mode','margin_mode','return_pct','mtm_dd_close_pct','mtm_dd_adverse_pct','liquidations','gap_stops','max_gap_loss_R','skip_pct','peak_gross_pct','peak_margin_pct']
print('\nLIVE MMR / ISOLATED'); print(out[(out.mmr_mode=='LIVE')&(out.margin_mode=='ISOLATED')][cols].to_string(index=False))
print('\n1% MMR / ISOLATED'); print(out[(out.mmr_mode=='STRESS_1PCT')&(out.margin_mode=='ISOLATED')][cols].to_string(index=False))
print('\nLIVE MMR / CROSS'); print(out[(out.mmr_mode=='LIVE')&(out.margin_mode=='CROSS')][cols].to_string(index=False))
