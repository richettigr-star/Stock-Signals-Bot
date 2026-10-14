# Stock Signals Bot

Nightly signal scanner for a fixed universe of 20 US-listed stocks.

## Strategy

The bot runs after the regular US market close and evaluates:

- AAPL
- MSFT
- NVDA
- AMZN
- META
- GOOGL
- TSLA
- AMD
- AVGO
- NFLX
- JPM
- BAC
- XOM
- CVX
- UNH
- LLY
- COST
- WMT
- PLTR
- COIN

Rules:

- Daily bars
- Momentum lookback: 10 trading days
- Entry filter: Momentum10 > +2%
- Trend filter: Close > EMA100
- ATR14 using Wilder smoothing
- Ranking: `Momentum10 / (ATR14 / Close)`
- Reference stop distance: `2.5 × ATR14`
- Long-only
- No leverage
- Maximum of 3 nightly entry candidates
- Signal is calculated after the close
- Intended execution is the next market open

## Risk profiles

The report shows both profiles:

- `LIVE Small`: 7.5% account risk target per trade
- `LIVE Small Aggressive`: 8.0% account risk target per trade

Default reference account size is C$100.

## Capital allocation

The account cash is now split equally across the candidates selected in that nightly scan:

- 1 selected candidate: up to 100% of account cash
- 2 selected candidates: up to 50% each
- 3 selected candidates: up to 33.33% each

For each candidate, the final recommended position is the smaller of:

1. the risk-based position size; and
2. that candidate's equal cash slot.

Example with a C$100 account and 3 selected candidates: each candidate receives a maximum cash slot of approximately C$33.33.

## Files produced

Every run creates/updates:

- `signals.json` — machine-readable signal data
- `report.md` — easy-to-read nightly report

## Twelve Data API key

Create this GitHub Actions secret:

`TWELVE_DATA_API_KEY`

Do not put the API key inside `scanner.py`, `README.md`, or any other committed file.

GitHub path:

`Repository → Settings → Secrets and variables → Actions → New repository secret`

## Automatic run

The workflow runs automatically Monday-Friday at 22:30 UTC, after the regular US market close.

You can also run it manually from:

`Repository → Actions → Nightly Stock Signals → Run workflow`

## Account size

The workflow currently contains:

`ACCOUNT_EQUITY_CAD: "100"`

Change that value later when your account size changes.

## Manual Wealthsimple execution

When a stock appears under `candidates`:

1. The signal was generated from the completed daily bar.
2. The intended strategy entry is the next regular market open.
3. Use `recommended_position_cad` as the suggested cash amount for that candidate.
4. Never exceed your actual available cash if you are staying unleveraged.
5. The reference stop shown is based on the signal close.
6. After a real fill, a more accurate initial stop reference is:
   `fill price - 2.5 × ATR14 from the signal bar`.

## Important limitation

This version does not connect to Wealthsimple and does not yet know your real positions, fills, or remaining cash. Capital is split across the candidates selected in the current nightly scan only.

If you already hold positions, you must account for them manually until portfolio-state tracking is added.

## Local test

macOS/Linux:

```bash
export TWELVE_DATA_API_KEY="your_key_here"
export ACCOUNT_EQUITY_CAD="100"
pip install -r requirements.txt
python scanner.py
```

Never commit your real API key.
