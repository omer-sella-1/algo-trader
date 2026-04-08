# Tech Stack

> Technologies, libraries, and project layout.

## Runtime

- **Python 3.10** (system Python on VM at `/usr/bin/python3`)
- **Virtualenv**: `~/algo-trader/venv/` on VM, `.venv/` locally

## Key Libraries

| Library | Purpose |
|---------|---------|
| `ib_insync` | IBKR API client (connects to IB Gateway on port 4001) |
| `pandas` | OHLCV data manipulation |
| `requests` | Alpaca API + Telegram API calls |
| `python-dotenv` | Load `.env` secrets |

Note: `pandas-ta` is listed in requirements but **not used** — all indicators (SMA, BB, RSI) are implemented with pure pandas math in `main.py`.

## External APIs

| API | Used For | Auth |
|-----|----------|------|
| Alpaca Markets | Daily OHLCV bars (free tier) | API key in `.env` |
| Telegram Bot API | Trade alerts + approval buttons | Bot token in `.env` |
| IBKR (IB Gateway) | Order execution, account data | Local socket :4001 |

## Project Structure

```
algo-trader/
├── main.py                  # Main scanner + position manager
├── telegram_bot.py      # Telegram bot (commands + approvals)
├── requirements.txt
├── trades.csv               # Open positions log
├── .env                     # Secrets (never commit)
├── CLAUDE.md
├── deploy/
│   └── start-gateway.sh     # IB Gateway startup script (deployed to ~/ibc/)
├── docs/
│   ├── context/             # This documentation
│   └── plans/               # Implementation plans
└── scripts/
    ├── health_check.sh      # Gateway health check (runs on VM)
    ├── get_sp500.py
    ├── test_ibkr_connection.py
    ├── test_buy.py
    └── test_brackets.py
```

## Local vs VM

| Item | Local (Mac) | VM (Oracle Cloud) |
|------|-------------|-------------------|
| Code editing | ✓ | — |
| Bot execution | — | ✓ (cron) |
| IB Gateway | — | ✓ |
| venv path | `.venv/` | `venv/` |

Deploy changes to VM:
```bash
scp -i ~/Downloads/"ssh-key-2026-04-04 (1).key" main.py ubuntu@129.159.139.113:~/algo-trader/
```

---
Last updated: 2026-04-08
