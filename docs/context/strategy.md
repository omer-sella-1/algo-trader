# Trading Strategy

> End-of-day momentum + mean-reversion scanner on S&P 500 stocks.

## Signal Logic

Entry fires when ALL conditions are true:
1. **Price > SMA(150)** — stock is in long-term uptrend
2. **Price < Bollinger Lower Band (20, 1.5σ)** — short-term oversold
3. **RSI(14) < 40** — momentum confirms oversold

## Order Structure

- **Entry**: Market order, DAY (expires if unfilled by close)
- **Take Profit**: Limit order at upper Bollinger Band, GTC
- **Stop Loss**: Limit order at configurable % below entry, GTC
- Orders placed as bracket (entry + TP + SL together)

## Risk Rules

| Parameter | Value |
|-----------|-------|
| Max positions | 10 |
| Max holding days | 45 (force-close at market) |
| Position sizing | Cash-only (`TotalCashValue / MAX_POSITIONS`) |
| Leverage | None |

## Universe

- Top 50 S&P 500 stocks by market cap (fetched via `scripts/get_sp500.py`)
- Scanned daily after close

## Parameters

```python
SMA_PERIOD = 150
BB_LENGTH = 20
BB_STD = 1.5
RSI_PERIOD = 14
RSI_THRESH = 40
MAX_POSITIONS = 10
MAX_HOLDING_DAYS = 45
```

## Approval Flow

When a signal fires:
1. Bot writes to `pending_orders.json`
2. Sends Telegram message with symbol, qty, entry, TP, SL
3. User taps Approve/Reject on phone
4. `approval_handler.py` executes or discards

Set `REQUIRE_APPROVAL=false` in `.env` to trade autonomously (not recommended for live).

---
Last updated: 2026-04-08
