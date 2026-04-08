# IBKR Migration Design

## Overview

Migrate algo-trader from Alpaca (paper) to Interactive Brokers (live) for real-money swing trading. Deploy on Oracle Cloud free tier ARM VM.

## Architecture

```
┌──────────────────────────────────────────────┐
│            Oracle Cloud VM (1GB ARM)          │
│                                               │
│  IBC + IB Gateway (always on, auto-login)     │
│                                               │
│  Cron: 16:30 ET, Mon-Fri                      │
│    python main.py                             │
│      1. AlphaVantage → S&P 500 universe       │
│      2. Alpaca data API → OHLCV bars (free)   │
│      3. Strategy: SMA/BB/RSI (unchanged)      │
│      4. ib_insync → IB Gateway → execute      │
│      5. Disconnect                            │
└──────────────────────────────────────────────┘
```

## What stays the same

- `get_sp500_tickers()` — AlphaVantage lookup, unchanged
- `get_market_data()` — Alpaca free data API, unchanged
- Strategy math — SMA(150), BB(20, 1.5), RSI(14), unchanged
- Position sizing — 10% of equity per trade, unchanged
- Logging — trades.csv and activity.log, unchanged

## What changes (Alpaca → ib_insync)

### Connection management

Connect at start of run, disconnect at end. No persistent connection needed.

```python
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)  # 4002 = IB Gateway paper, 4001 = live
# ... do all work ...
ib.disconnect()
```

### Account snapshot

**Before (Alpaca):**
```python
acct = requests.get(f"{BASE_URL}/v2/account", headers=HEADERS).json()
equity = float(acct['equity'])
buying_power = float(acct['buying_power'])
```

**After (IBKR):**
```python
values = {av.tag: float(av.value) for av in ib.accountValues() if av.currency == 'USD'}
equity = values['NetLiquidation']
buying_power = values['BuyingPower']
```

### Get positions

**Before (Alpaca):**
```python
positions = requests.get(f"{BASE_URL}/v2/positions", headers=HEADERS).json()
```

**After (IBKR):**
```python
positions = ib.positions()
# Each: pos.contract.symbol, pos.position, pos.avgCost
```

### Get open orders

**Before (Alpaca):**
```python
open_orders = requests.get(f"{BASE_URL}/v2/orders", headers=HEADERS, params={"status": "open"}).json()
```

**After (IBKR):**
```python
open_trades = ib.openTrades()
# Each: trade.contract.symbol, trade.order.action, trade.orderStatus.status
```

### Submit bracket order (DAY entry + GTC TP/SL)

**Before (Alpaca):** Single POST with order_class=bracket, all GTC.

**After (IBKR):**
```python
contract = Stock(symbol, 'SMART', 'USD')
ib.qualifyContracts(contract)

bracket = ib.bracketOrder(
    action='BUY',
    quantity=qty,
    limitPrice=round(entry_price, 2),
    takeProfitPrice=round(tp_price, 2),
    stopLossPrice=round(sl_price, 2)
)

# Parent (entry): DAY — expires if not filled
bracket[0].tif = 'DAY'
# Take profit: GTC — stays until hit
bracket[1].tif = 'GTC'
# Stop loss: GTC — stays until hit
bracket[2].tif = 'GTC'

for order in bracket:
    ib.placeOrder(contract, order)
```

### Close position (stale trade)

**Before (Alpaca):** POST market sell order.

**After (IBKR):**
```python
contract = Stock(symbol, 'SMART', 'USD')
ib.qualifyContracts(contract)
order = MarketOrder('SELL', qty)
ib.placeOrder(contract, order)
```

### Get position age (for stale trade detection)

**Before (Alpaca):** Query closed buy orders, parse filled_at timestamp.

**After (IBKR):**
```python
fills = ib.fills()
# Find the oldest buy fill for this symbol
# Calculate days held from fill.execution.time
```

Alternative: track entry dates locally in trades.csv (already logged). This is more reliable than querying IBKR execution history which may be limited.

**Decision: use trades.csv as source of truth for entry dates.** The log_trade() call already records timestamps. Parse the CSV to find the most recent BUY_BRACKET entry for a symbol and calculate days since then.

## Configuration

Environment variables (in .env):
```
# Data (keep existing)
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPHAVANTAGE_API_KEY=...

# IBKR
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4002        # 4002=paper, 4001=live
IB_CLIENT_ID=1
```

## Deployment: Oracle Cloud Free Tier

### VM Setup
- Shape: VM.Standard.A1.Flex (ARM, 1 OCPU, 1GB RAM)
- OS: Ubuntu 22.04 aarch64
- Java: OpenJDK 11+ (for IB Gateway)
- Python: 3.10+

### Software stack
1. **IB Gateway** — headless IBKR trading app (download from IBKR)
2. **IBC** — auto-starts IB Gateway, handles login and daily restarts
3. **Python + ib_insync** — our trading script
4. **Cron** — triggers main.py at 16:30 ET Mon-Fri

### IBC configuration
IBC handles:
- Auto-start IB Gateway on boot (systemd service)
- Auto-login with stored credentials
- Daily restart after IBKR's midnight maintenance
- 2FA: use IBKR mobile app for initial trust, then IBC maintains session

### Cron entry
```
30 16 * * 1-5 cd /home/ubuntu/algo-trader && /usr/bin/python3 main.py >> /home/ubuntu/algo-trader/cron.log 2>&1
```
(Server timezone set to America/New_York)

## File changes

### Modified files
- `main.py` — Replace Alpaca broker calls with ib_insync. Add connect/disconnect wrapper.
- `requirements.txt` — Add ib_insync dependency.

### New files
- `scripts/test_ibkr_connection.py` — Connectivity smoke test (already created).
- `deploy/` — IBC config files and systemd service for Oracle Cloud.

### Unchanged files
- `scripts/bot.py` — Alpaca-specific, keep for reference.
- `scripts/apply_protection.py` — May port later if needed.
- `scripts/test_buy.py`, `scripts/test_cancel.py` — Alpaca test scripts, keep for reference.

## Implementation order

1. Install ib_insync, get IB Gateway + IBC running locally (paper account)
2. Run test_ibkr_connection.py to verify connectivity
3. Rewrite main.py broker calls (account, positions, orders)
4. Implement get_position_age_days using trades.csv
5. Test full run on paper account
6. Set up Oracle Cloud VM
7. Deploy IB Gateway + IBC + algo-trader
8. Run on paper for 1-2 weeks
9. Switch to live (change port 4002 → 4001)
