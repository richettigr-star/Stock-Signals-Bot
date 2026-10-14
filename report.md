# Stock Signals Bot — Daily Report

Generated: 2026-10-14T20:51:32.744120+00:00
Latest market bar: 2026-10-14
Account reference: C$100.00

## 3 candidate(s) for the next market open

### 1. COST
- Momentum10: 7.895%
- Close: US$982.2100
- EMA100: US$944.7537
- ATR14 (Wilder): US$15.4699
- Score: 5.012574
- Entry: next market open
- Reference stop from signal close: US$943.5353
- Stop distance: 3.938% (= 2.5×ATR)

**LIVE Small**
- Target risk: C$7.50
- Risk-based position: C$190.48
- Cash-capped position (no leverage): C$100.00

**LIVE Small Aggressive**
- Target risk: C$8.00
- Risk-based position: C$203.17
- Cash-capped position (no leverage): C$100.00

### 2. XOM
- Momentum10: 8.750%
- Close: US$176.9900
- EMA100: US$157.9461
- ATR14 (Wilder): US$3.4547
- Score: 4.482549
- Entry: next market open
- Reference stop from signal close: US$168.3532
- Stop distance: 4.880% (= 2.5×ATR)

**LIVE Small**
- Target risk: C$7.50
- Risk-based position: C$153.69
- Cash-capped position (no leverage): C$100.00

**LIVE Small Aggressive**
- Target risk: C$8.00
- Risk-based position: C$163.94
- Cash-capped position (no leverage): C$100.00

### 3. CVX
- Momentum10: 8.770%
- Close: US$222.1200
- EMA100: US$198.7867
- ATR14 (Wilder): US$4.3608
- Score: 4.467228
- Entry: next market open
- Reference stop from signal close: US$211.2180
- Stop distance: 4.908% (= 2.5×ATR)

**LIVE Small**
- Target risk: C$7.50
- Risk-based position: C$152.81
- Cash-capped position (no leverage): C$100.00

**LIVE Small Aggressive**
- Target risk: C$8.00
- Risk-based position: C$162.99
- Cash-capped position (no leverage): C$100.00

## Data warnings

- Failed to fetch AVGO: 429 Client Error: Too Many Requests for url: https://api.twelvedata.com/time_series?symbol=AVGO&interval=1day&outputsize=180&adjust=splits&apikey=6377f9dc796e42d7a2886c16388cea19
- Failed to fetch WMT: 429 Client Error: Too Many Requests for url: https://api.twelvedata.com/time_series?symbol=WMT&interval=1day&outputsize=180&adjust=splits&apikey=6377f9dc796e42d7a2886c16388cea19
- Failed to fetch PLTR: 429 Client Error: Too Many Requests for url: https://api.twelvedata.com/time_series?symbol=PLTR&interval=1day&outputsize=180&adjust=splits&apikey=6377f9dc796e42d7a2886c16388cea19
- Failed to fetch COIN: 429 Client Error: Too Many Requests for url: https://api.twelvedata.com/time_series?symbol=COIN&interval=1day&outputsize=180&adjust=splits&apikey=6377f9dc796e42d7a2886c16388cea19

## Execution note

The signal is calculated after the daily bar is complete. Intended entry is the next market open.
The stop shown is a reference based on the signal close. After a real fill, the practical stop reference is fill price minus 2.5×ATR from the signal bar.

This is a signal tool, not an automated broker connection.
