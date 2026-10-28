from pathlib import Path

p = Path(__file__).with_name('donchian_v2_mtm_weex_stress_fast.py')
s = p.read_text()
s = s.replace(
    "H=pd.date_range(START, END-pd.Timedelta(hours=1), freq='1h', tz='UTC')\nN=len(H); HVAL=H.asi8; HMAP={int(v):i for i,v in enumerate(HVAL)}",
    "H=pd.date_range(START, END-pd.Timedelta(hours=1), freq='1h', tz='UTC')\nN=len(H); HMAP={pd.Timestamp(t):i for i,t in enumerate(H)}"
)
s = s.replace(
    "ei=HMAP.get(int(pd.Timestamp(r.entry_time).value)); xi=HMAP.get(int((pd.Timestamp(r.planned_exit_time)-pd.Timedelta(hours=1)).value))",
    "ei=HMAP.get(pd.Timestamp(r.entry_time)); xi=HMAP.get(pd.Timestamp(r.planned_exit_time)-pd.Timedelta(hours=1))"
)
s = s.replace(
    "ii=HMAP.get(int(pd.Timestamp(r.time).value))",
    "ii=HMAP.get(pd.Timestamp(r.time))"
)
s = s.replace(
    "ai=HMAP[int(a.value)]; bi=HMAP.get(int(b.value),N)",
    "ai=int(H.searchsorted(a)); bi=int(H.searchsorted(b))"
)
exec(compile(s, str(p), 'exec'), {'__name__':'__main__','__file__':str(p)})
