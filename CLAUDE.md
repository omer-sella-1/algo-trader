# algo-trader

> Live IBKR algorithmic trading bot — scans S&P 500 daily after market close, places bracket orders with Telegram approval.

## Quick Reference

- **Runs**: 16:30 ET Mon–Fri on Oracle Cloud VM (after US market close)
- **Broker**: Interactive Brokers live account U11801478, port 4001
- **Data**: Alpaca Markets API (free tier, read-only)
- **Approval**: All trades require Telegram confirmation before execution
- **Safety**: Bot only manages positions it opened (`trades.csv` is source of truth)

## Documentation

- [architecture.md](docs/context/architecture.md) — System design, data flow, components
- [strategy.md](docs/context/strategy.md) — Trading strategy, signals, risk rules
- [deployment.md](docs/context/deployment.md) — VM setup, IBC/gateway, cron, systemd
- [techstack.md](docs/context/techstack.md) — Libraries, env vars, file layout

## Common Tasks

**Run bot manually on VM:**
```bash
ssh -i ~/Downloads/"ssh-key-2026-04-04 (1).key" ubuntu@129.159.139.113
cd ~/algo-trader && source venv/bin/activate && python main.py
```

**Check gateway is up:**
```bash
nc -z 127.0.0.1 4001 && echo UP || echo DOWN
```

**VNC into VM (for gateway UI):**
```bash
# Terminal 1: tunnel
ssh -i ~/Downloads/"ssh-key-2026-04-04 (1).key" -L 5900:localhost:5900 -N ubuntu@129.159.139.113
# Then connect VNC to localhost:5900, password: trader123
```

**Restart gateway:**
```bash
screen -dmS gateway ~/ibc/start-gateway.sh
```
