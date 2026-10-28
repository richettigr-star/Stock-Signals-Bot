from pathlib import Path

p=Path(__file__).with_name('combined_portfolio_4strategies.py')
src=p.read_text()
old="""                cand=c[i]-side*2.5*a[i]\n                if side==1: pos['stop']=max(pos['stop'],cand)\n                else: pos['stop']=min(pos['stop'],cand)"""
new="""                if side==1:\n                    cand=h[i]-2.5*a[i]\n                    pos['stop']=max(pos['stop'],cand)\n                else:\n                    cand=l[i]+2.5*a[i]\n                    pos['stop']=min(pos['stop'],cand)"""
if old not in src:
    raise RuntimeError('Momentum trailing patch target not found')
src=src.replace(old,new,1)
exec(compile(src,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
