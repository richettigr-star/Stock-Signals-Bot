from __future__ import annotations
import io,zipfile,requests
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np,pandas as pd
import donchian_v2_repo_inspired_exact as eng

OCT=pd.Timestamp('2026-10-01',tz='UTC');END=pd.Timestamp('2026-10-28',tz='UTC');eng.END=END
KDAY='https://data.binance.vision/data/futures/um/daily/klines/{sym}/1h/{sym}-1h-{day}.zip'

def getraw(u):
 r=requests.get(u,timeout=30)
 if r.status_code==404:return None
 r.raise_for_status()
 with zipfile.ZipFile(io.BytesIO(r.content)) as z:return z.read(next(n for n in z.namelist() if n.endswith('.csv')))
def pbar(raw):
 if raw is None:return pd.DataFrame(columns=['open','high','low','close','volume'])
 d=pd.read_csv(io.BytesIO(raw),header=None)
 for c in range(6):d[c]=pd.to_numeric(d[c],errors='coerce')
 d=d.dropna(subset=list(range(6)));unit='us' if len(d) and float(d.iloc[0,0])>=1e14 else 'ms'
 if d.empty:return pd.DataFrame(columns=['open','high','low','close','volume'])
 x=pd.DataFrame({'time':pd.to_datetime(d[0],unit=unit,utc=True),'open':d[1],'high':d[2],'low':d[3],'close':d[4],'volume':d[5]});return x.set_index('time')
def octbars(sym):
 ds=list(pd.date_range(OCT,END-pd.Timedelta(days=1),freq='1D',tz='UTC'));pieces=[]
 with ThreadPoolExecutor(max_workers=16) as ex:
  fs=[ex.submit(lambda d:(d,pbar(getraw(KDAY.format(sym=sym,day=d.strftime('%Y-%m-%d'))))),d) for d in ds]
  for f in as_completed(fs):
   _,x=f.result()
   if not x.empty:pieces.append(x)
 return pd.concat(pieces).sort_index() if pieces else pd.DataFrame()

def gen(sym,x):
 eh=x.high.shift(1).rolling(40,min_periods=40).max();el=x.low.shift(1).rolling(40,min_periods=40).min();ap=x.atr.shift(1)
 la=((x.close>eh+.25*ap)&(x.close>x.ema200)).fillna(False).to_numpy(bool);sa=((x.close<el-.25*ap)&(x.close<x.ema200)).fillna(False).to_numpy(bool)
 xh=x.high.shift(1).rolling(20,min_periods=20).max();xl=x.low.shift(1).rolling(20,min_periods=20).min();o=x.open.to_numpy(float);h=x.high.to_numpy(float);l=x.low.to_numpy(float);c=x.close.to_numpy(float);a=x.atr.to_numpy(float);ix=x.index
 out=[];pos=None;pend=None
 for i in range(len(x)):
  if pos is None and pend is not None:
   si,side,a0=pend
   if i>si and np.isfinite(a0) and a0>0:
    e=o[i];pos={'side':side,'e':e,'et':ix[i],'sl':e-side*2*a0,'bars':0,'rf':2*a0/e}
   pend=None
  if pos is not None:
   pos['bars']+=1;side=pos['side'];xp=None
   if side==1 and l[i]<=pos['sl']:xp=pos['sl']
   elif side==-1 and h[i]>=pos['sl']:xp=pos['sl']
   elif side==1 and np.isfinite(xl.iloc[i]) and c[i]<xl.iloc[i]:xp=c[i]
   elif side==-1 and np.isfinite(xh.iloc[i]) and c[i]>xh.iloc[i]:xp=c[i]
   elif pos['bars']>=60:xp=c[i]
   if xp is not None:
    xt=ix[i]+pd.Timedelta(hours=4);out.append((sym,pos['et'],xt,side*(xp-pos['e'])/pos['e']-eng.BASE_COST,pos['rf']));pos=None
  if pos is None and pend is None and i+1<len(x):
   if la[i] and not sa[i]:pend=(i,1,a[i])
   elif sa[i] and not la[i]:pend=(i,-1,a[i])
 return out

tr=[]
for sym in eng.SYMS:
 print('LOAD',sym,flush=True);raw,_=eng.loadbars(sym);ob=octbars(sym);raw=pd.concat([raw,ob]).sort_index();raw=raw[~raw.index.duplicated(keep='last')];daily=eng.full_daily_features(raw);x=eng.prep_segment(raw,pd.DataFrame(columns=['time','last_funding_rate']),eng.DEV_START,END,daily);tr.extend(gen(sym,x))
t=pd.DataFrame(tr,columns=['symbol','entry_time','exit_time','net','rf']);t=t[(t.entry_time>=OCT)&(t.entry_time<END)].sort_values(['entry_time','symbol']).reset_index(drop=True)
print('OCT TRADES',len(t),'RF median',t.rf.median(),flush=True)

def sim(rb,lev,heat,gross,maxp=8):
 ev=[]
 for i,r in t.iterrows():ev.extend([(r.exit_time,0,i),(r.entry_time,1,i)])
 ev.sort(key=lambda q:(q[0],q[1]));eq=100.;peak=100.;dd=0.;act={};acc=skip=0;pg=ph=pm=0.
 for _,typ,i in ev:
  r=t.loc[i]
  if typ==0:
   p=act.pop(i,None)
   if p is None:continue
   eq+=p[0]*float(r.net);peak=max(peak,eq);dd=min(dd,eq/peak-1)
  else:
   risk=rb*eq;notional=risk/float(r.rf);margin=notional/lev;g=sum(v[0] for v in act.values());h=sum(v[1] for v in act.values());m=sum(v[2] for v in act.values())
   if len(act)>=maxp or g+notional>gross*eq+1e-12 or h+risk>heat*eq+1e-12 or m+margin>eq+1e-12:skip+=1;continue
   act[i]=(notional,risk,margin);acc+=1;pg=max(pg,(g+notional)/eq);ph=max(ph,(h+risk)/eq);pm=max(pm,(m+margin)/eq)
 return {'risk_pct':rb*100,'lev':lev,'heat_pct':heat*100,'gross_pct':gross*100,'eq':eq,'ret':eq-100,'dd':dd*100,'acc':acc,'skip':skip,'skip_pct':100*skip/max(1,acc+skip),'peakgross':pg*100,'peakheat':ph*100,'peakmargin':pm*100}
configs=[(.005,3,.04,2.5),(.005,4,.04,2.5),(.0075,4,.06,3.0),(.0075,5,.06,3.0),(.01,5,.08,4.0),(.01,7,.08,4.0)]
out=pd.DataFrame([sim(*x) for x in configs]);out.to_csv('donchian_v2_october_stoprisk.csv',index=False);print(out.to_string(index=False));print('\nPAIR');print(t.groupby('symbol').agg(trades=('net','size'),sum_net=('net','sum')).to_string())
