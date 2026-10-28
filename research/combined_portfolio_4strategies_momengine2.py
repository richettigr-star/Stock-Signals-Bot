from pathlib import Path
p=Path(__file__).with_name('combined_portfolio_4strategies.py')
src=p.read_text()
old_entry="""                e=o[i]; st=e-side*2.5*a0; pos={'side':side,'e':e,'et':ix[i],'stop':st,'a0':a0}"""
new_entry="""                entry_atr=a[i]; e=o[i]; st=e-side*2.5*entry_atr; pos={'side':side,'e':e,'et':ix[i],'stop':st,'a0':entry_atr}"""
old_block="""            side=pos['side']; xp=None\n            if side==1 and l[i]<=pos['stop']: xp=pos['stop']\n            elif side==-1 and h[i]>=pos['stop']: xp=pos['stop']\n            if xp is not None:\n                xt=ix[i]+pd.Timedelta(hours=6); out.append(mk_trade('MOM6H',sym,side,pos['et'],xt,pos['e'],xp,2.5*pos['a0']/pos['e'])); pos=None\n            else:\n                cand=c[i]-side*2.5*a[i]\n                if side==1: pos['stop']=max(pos['stop'],cand)\n                else: pos['stop']=min(pos['stop'],cand)"""
new_block="""            side=pos['side']; xp=None\n            if side==1:\n                pos['stop']=max(pos['stop'],h[i]-2.5*a[i])\n                if l[i]<=pos['stop']: xp=pos['stop']\n            else:\n                pos['stop']=min(pos['stop'],l[i]+2.5*a[i])\n                if h[i]>=pos['stop']: xp=pos['stop']\n            if xp is not None:\n                xt=ix[i]+pd.Timedelta(hours=6); out.append(mk_trade('MOM6H',sym,side,pos['et'],xt,pos['e'],xp,2.5*pos['a0']/pos['e'])); pos=None"""
if old_entry not in src or old_block not in src: raise RuntimeError('patch target missing')
src=src.replace(old_entry,new_entry,1).replace(old_block,new_block,1)
exec(compile(src,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
