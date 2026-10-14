# Stock Signals Bot

Signal-only stock scanner for a fixed universe of 20 US-listed stocks.

## Strategy

The bot evaluates:

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
- Maximum of 3 entry candidates
- Entry signal is confirmed only after the completed daily close
- Intended execution is the next regular market open

## Risk profiles

The report shows both profiles:

- `LIVE Small`: 7.5% account risk target per trade
- `LIVE Small Aggressive`: 8.0% account risk target per trade

Default reference account size is C$100.

## Capital allocation

Account cash is split equally across candidates selected by the completed daily scan:

- 1 selected candidate: up to 100% of account cash
- 2 selected candidates: up to 50% each
- 3 selected candidates: up to 33.33% each

For each candidate, the final recommended position is the smaller of:

1. the risk-based position size; and
2. that candidate's equal cash slot.

Example with a C$100 account and 3 selected candidates: each candidate receives a maximum cash slot of approximately C$33.33.

## Daily entry scan

The after-close workflow targets approximately **16:10 New York time**, Monday-Friday.

Because GitHub cron schedules use UTC and New York changes between daylight-saving and standard time, the workflow has two UTC schedules plus a New York-time gate. Only the run that occurs after 16:05 New York time performs the scan.

The daily scan uses the completed regular-session daily bar. It does not generate intraday entries because that would be a different strategy from the daily strategy being tested.

## Trailing stop

For a strategy signal that remains active, the trailing stop is updated after each completed daily bar using:

`new stop = max(previous stop, completed daily close - 2.5 × ATR14)`

The stop never moves down.

A Telegram `STOP UPDATE` alert is sent only when the stop actually increases.

## Intraday exit monitoring

During the regular US session, the intraday workflow checks active signal stops approximately every 5 minutes.

It uses 1-minute bars and creates an `EXIT` event when a bar trades at or below the stored stop.

This is signal-only monitoring. It does not place a broker order. For fractional Wealthsimple positions, the user sells manually after receiving the emergency alert.

## Telegram notifications

Telegram is the primary operational notification channel.

Alerts:

- `ENTRY` — new confirmed daily signal for the next regular market open
- `STOP UPDATE` — trailing stop increased after a completed daily bar
- `EXIT` — stop was crossed intraday; urgent manual sell alert

Create these GitHub Actions secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not commit either value to the repository.

GitHub path:

`Repository → Settings → Secrets and variables → Actions`

There is also a manual workflow called `Test Emergency Telegram` for verifying the Telegram connection.

## Twelve Data API key

Create this GitHub Actions secret:

`TWELVE_DATA_API_KEY`

Do not put the API key inside committed files.

## Files produced

The system maintains:

- `signals.json` — latest scanner output
- `report.md` — human-readable daily report
- `signal_state.json` — strategy-only memory of pending/active signals and current stops
- `signal_events.json` — ENTRY, STOP_UPDATE and EXIT event history

## Manual Wealthsimple execution

For an `ENTRY` alert:

1. The signal was confirmed from the completed daily bar.
2. Intended execution is the next regular market open.
3. Use `recommended_position_cad` as the suggested cash amount.
4. The purchase is manual in Wealthsimple.

For an `EXIT` alert:

1. The stored stop was crossed during the regular session.
2. The Telegram message is an urgent signal-only alert.
3. Sell the corresponding fractional position manually in Wealthsimple as soon as practical.

## Important limitation

The bot does not connect to Wealthsimple and does not know actual broker fills or holdings. It maintains only strategy signal state so it can avoid duplicate entries, update stops, and generate exits.

## Local test

macOS/Linux:

```bash
export TWELVE_DATA_API_KEY="your_key_here"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export ACCOUNT_EQUITY_CAD="100"
pip install -r requirements.txt
python scanner.py
python manage_state.py
```

Never commit real API keys or Telegram credentials.
