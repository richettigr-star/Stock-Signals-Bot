from pathlib import Path
p=Path(__file__).with_name('combined_portfolio_4strategies.py')
src=p.read_text()
old="for s in CORE4: tr.extend(momentum_trades(s))\ntr.extend(eth_squeeze_trades());tr.extend(xrp_mr_trades())"
new="tr.extend(eth_squeeze_trades());tr.extend(xrp_mr_trades())"
if old not in src: raise RuntimeError('template patch missing')
src=src.replace(old,new,1)
# Remove Momentum-specific native sizing branch, though no MOM6H templates remain.
exec(compile(src,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
