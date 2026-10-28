from pathlib import Path
p=Path(__file__).with_name('combined_portfolio_4strategies.py')
src=p.read_text()
a=src.index('def momentum_trades(sym):')
b=src.index('\ndef eth_squeeze_trades():')
fn=r'''def momentum_trades(sym):
    q=B[sym].resample('6h',origin='epoch',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    q['atr']=atr(q); q['ema100']=q.close.ewm(span=100,adjust=False).mean(); q['mom']=100*(q.close/q.close.shift(10)-1)
    q['slope']=q.ema100-q.ema100.shift(3); q['atrp']=q.atr/q.close; q['volmed']=q.atrp.rolling(100,min_periods=100).quantile(.5,interpolation='nearest')
    long=(q.mom>=2.0)&(q.close>q.ema100)&(q.slope>0)&(q.atrp>=q.volmed)
    short=(q.mom<=-2.0)&(q.close<q.ema100)&(q.slope<0)&(q.atrp>=q.volmed)
    o=q.open.to_numpy(float); h=q.high.to_numpy(float); l=q.low.to_numpy(float); c=q.close.to_numpy(float); av=q.atr.to_numpy(float); ix=q.index
    la=long.fillna(False).to_numpy(bool); sa=short.fillna(False).to_numpy(bool); out=[]; pos=None; pending_side=None
    for i in range(len(q)):
        # market entry/reversal ordered on prior 6H close, filled at this 6H open
        if pending_side is not None and np.isfinite(av[i]):
            if pos is not None and pos['side']!=pending_side:
                out.append(mk_trade('MOM6H',sym,pos['side'],pos['et'],ix[i],pos['e'],o[i],2.5*pos['a0']/pos['e']))
                pos=None
            if pos is None:
                e=o[i]; a0=av[i]; pos={'side':pending_side,'e':e,'et':ix[i],'stop':e-pending_side*2.5*a0,'a0':a0}
            pending_side=None
        # protective stop active intrabar; trailing from this completed candle becomes effective after the bar
        if pos is not None:
            side=pos['side']; xp=None
            if side==1 and l[i]<=pos['stop']: xp=pos['stop']
            elif side==-1 and h[i]>=pos['stop']: xp=pos['stop']
            if xp is not None:
                xt=ix[i]+pd.Timedelta(hours=6); out.append(mk_trade('MOM6H',sym,side,pos['et'],xt,pos['e'],xp,2.5*pos['a0']/pos['e'])); pos=None
            else:
                if side==1: pos['stop']=max(pos['stop'],h[i]-2.5*av[i])
                else: pos['stop']=min(pos['stop'],l[i]+2.5*av[i])
        # strategy.entry with pyramiding=0: same-side signal does nothing; opposite signal reverses next open
        if i+1<len(q):
            if la[i] and (pos is None or pos['side']<=0): pending_side=1
            elif sa[i] and (pos is None or pos['side']>=0): pending_side=-1
    return out
'''
src=src[:a]+fn+src[b:]
exec(compile(src,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
