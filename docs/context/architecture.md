# Architecture

> End-to-end flow from market data to live IBKR orders.

## Component Overview

```
Alpaca API (data)
    ↓
main.py (scanner + signal engine)
    ↓ pending_orders.json
telegram_bot.py (Telegram bot, systemd service)
    ↓ user approves via Telegram
IB Gateway :4001 (ib_insync)
    ↓
IBKR Live Account U11801478
```

## main.py — Daily Scanner

Runs at 16:30 ET via cron. Steps:
1. Connect to IB Gateway (port 4001)
2. Load `trades.csv` to find bot-managed open positions
3. Check TP/SL hit for existing positions → close if triggered
4. Check holding days → force-close if > 45 days
5. If slots available (max 10): scan top 50 S&P 500 stocks
6. For each stock: fetch daily OHLCV from Alpaca, compute signals
7. If signal fires: write to `pending_orders.json`, send Telegram approval request
8. Disconnect

## telegram_bot.py — Order Executor

Long-lived systemd service (`approval-handler.service`). Steps:
1. Polls Telegram for inline button callbacks
2. On "Approve": connects to IB Gateway (clientId=2), places bracket order
3. On "Reject": discards pending order
4. Logs all activity to `activity.log`

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Scanner, signal engine, position manager |
| `telegram_bot.py` | Telegram listener, order executor |
| `trades.csv` | Source of truth for bot-managed positions |
| `pending_orders.json` | Queue between scanner and approval handler |
| `activity.log` | Full audit log |
| `cron.log` | Cron + health check output |
| `.env` | All secrets and config (never commit) |

## Connection IDs

- `main.py` uses `clientId=1`
- `telegram_bot.py` uses `clientId=2`
- Both connect to `127.0.0.1:4001`

## Position Safety

- `trades.csv` tracks every bot-opened position
- On startup, main.py only manages symbols in `trades.csv`
- Manually-held positions (e.g. VOO) are never touched

---
Last updated: 2026-04-08
