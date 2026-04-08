# Deployment

> Everything runs on Oracle Cloud VM — no dependency on local machine.

## VM Details

| Property | Value |
|----------|-------|
| Provider | Oracle Cloud Free Tier |
| IP | 129.159.139.113 |
| User | ubuntu |
| OS | Ubuntu 22.04 |
| RAM | 1GB + 2GB swap |
| SSH key | `~/Downloads/ssh-key-2026-04-04 (1).key` |

## SSH Access

```bash
ssh -i ~/Downloads/"ssh-key-2026-04-04 (1).key" ubuntu@129.159.139.113
```

## VNC Access (for IB Gateway UI)

```bash
# Open tunnel in a separate terminal:
ssh -i ~/Downloads/"ssh-key-2026-04-04 (1).key" -L 5900:localhost:5900 -N ubuntu@129.159.139.113
# Connect VNC viewer to localhost:5900, password: trader123
```

## IB Gateway

- **Software**: IB Gateway 1037 + IBC 3.19
- **Port**: 4001 (live trading)
- **Display**: Xvfb :1 (virtual framebuffer, no monitor needed)
- **Start script**: `~/ibc/start-gateway.sh`
- **IBC config**: `~/ibc/config.ini`
- **Logs**: `~/ibc/logs/`

### Gateway Startup

```bash
screen -dmS gateway ~/ibc/start-gateway.sh
DISPLAY=:1 x11vnc -display :1 -passwd trader123 -forever -shared -quiet -bg
```

### IBC Config (`~/ibc/config.ini`)

Key settings:
```ini
AutoRestartTime=03:00 AM   # Daily warm restart (ET) = 10:00 AM Jerusalem
TradingMode=live
AcceptIncomingConnectionAction=accept
ReadOnlyApi=no
OverrideTwsApiPort=4001
```

## 2FA / Weekly Authentication

- IBKR resets session tokens every **Sunday 1:00 AM ET (8:00 AM Jerusalem)**
- IBC auto-restarts at 3:00 AM ET (10:00 AM Jerusalem Sunday)
- **Action required**: tap **Approve** on IBKR Mobile push notification
- Mon–Sat restarts are fully automatic (no 2FA)
- If gateway goes down unexpectedly → Telegram alert within 15 minutes

## Systemd Services

| Service | Purpose |
|---------|---------|
| `ib-gateway.service` | Starts gateway on boot, restarts on crash |
| `x11vnc.service` | Starts VNC on boot, restarts on crash |
| `approval-handler.service` | Telegram bot (commands + approvals) |

```bash
sudo systemctl status ib-gateway x11vnc approval-handler
```

## Cron Jobs

```
30 16 * * 1-5   # Run bot at 16:30 ET Mon–Fri
*/15 * * * *    # Health check every 15 min
```

## Health Check

Script: `~/algo-trader/scripts/health_check.sh`
- Checks port 4001 every 15 minutes
- Sends Telegram alert if gateway is down
- Sends Telegram recovery message when gateway comes back up
- Uses sentinel file `/tmp/gw_alert_sent` to avoid alert spam

## Environment Variables (`.env`)

```
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4001
IB_CLIENT_ID=1
TELEGRAM_BOT_KEY=...
TELEGRAM_CHAT_ID=...
REQUIRE_APPROVAL=true
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

## Bot Directory

```
~/algo-trader/
├── main.py
├── telegram_bot.py
├── trades.csv          # Source of truth for open positions
├── pending_orders.json # Pending approval queue
├── activity.log        # Audit log
├── cron.log            # Cron + health check output
├── .env                # Secrets
├── venv/               # Python virtualenv
└── scripts/
    ├── health_check.sh
    └── get_sp500.py
```

---
Last updated: 2026-04-08
