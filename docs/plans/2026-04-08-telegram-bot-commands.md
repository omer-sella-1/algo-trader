# Telegram Bot Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add slash commands (/balance, /positions, /orders, /pnl, /trades, /status, /pending, /log) to the existing Telegram approval bot, with admin vs viewer access tiers.

**Architecture:** Extend `approval_handler.py` — the always-on long-polling service — to also handle `message` updates (slash commands) alongside the existing `callback_query` branch. Each command connects to IB Gateway read-only, fetches data, and replies. A `set_bot_commands()` call on startup registers the command menu in Telegram via `setMyCommands` with two scopes: admin (all commands) and default (viewer-safe commands only).

**Tech Stack:** Python 3, `requests` (HTTP to Telegram), `ib_insync` (IBKR data), raw Telegram Bot API (no extra libraries needed)

---

### Task 1: Add env var + access control helpers

**Files:**
- Modify: `approval_handler.py` (top of file, after existing env vars)

This task adds two helpers used by every command handler:
- `is_admin(chat_id)` — True if chat_id matches TELEGRAM_CHAT_ID
- `is_allowed(chat_id)` — True if admin OR in TELEGRAM_VIEWER_IDS

**Step 1: Add TELEGRAM_VIEWER_IDS to .env on the VM**

```bash
# SSH into VM, then:
echo 'TELEGRAM_VIEWER_IDS=' >> ~/algo-trader/.env
# Fill in comma-separated IDs, e.g.: TELEGRAM_VIEWER_IDS=123456789,987654321
# Leave blank for now if no viewers yet — the var just needs to exist
```

**Step 2: Add the env var load and helpers to approval_handler.py**

After the existing env var block (line ~20), add:

```python
TELEGRAM_VIEWER_IDS = set(
    i.strip() for i in os.getenv("TELEGRAM_VIEWER_IDS", "").split(",") if i.strip()
)


def is_admin(chat_id: str) -> bool:
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


def is_allowed(chat_id: str) -> bool:
    return is_admin(chat_id) or str(chat_id) in TELEGRAM_VIEWER_IDS
```

**Step 3: Manual verification**

Add a temporary `print` after the block and run locally:
```bash
TELEGRAM_CHAT_ID=123 TELEGRAM_VIEWER_IDS="456,789" python -c "
import os; os.environ['TELEGRAM_CHAT_ID']='123'; os.environ['TELEGRAM_VIEWER_IDS']='456,789'
# paste the two functions and test:
# is_admin('123') -> True
# is_admin('456') -> False
# is_allowed('456') -> True
# is_allowed('999') -> False
"
```

**Step 4: Commit**
```bash
git add approval_handler.py
git commit -m "feat: add viewer access control helpers"
```

---

### Task 2: Register bot command menu on startup

**Files:**
- Modify: `approval_handler.py` — add `set_bot_commands()`, call it at start of `poll_updates()`

**Step 1: Add the function after the existing `answer_callback` function**

```python
VIEWER_COMMANDS = [
    {"command": "balance",   "description": "Account equity, cash, and buying power"},
    {"command": "positions", "description": "All open positions with unrealized P&L"},
    {"command": "orders",    "description": "Open and pending orders"},
    {"command": "pnl",       "description": "Today's P&L summary"},
    {"command": "trades",    "description": "Today's filled trades"},
    {"command": "status",    "description": "Gateway connectivity and bot health"},
    {"command": "pending",   "description": "Trades awaiting your approval"},
]

ADMIN_EXTRA_COMMANDS = [
    {"command": "log", "description": "Last 15 lines of activity log (admin only)"},
]


def set_bot_commands():
    """Register slash command menus in Telegram for admin and viewers."""
    if not TELEGRAM_BOT_KEY or not TELEGRAM_CHAT_ID:
        return
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}"

    # Default scope: viewer-safe commands (shown to everyone including viewers)
    requests.post(f"{base}/setMyCommands", json={
        "commands": VIEWER_COMMANDS,
        "scope": {"type": "default"},
    }, timeout=10)

    # Admin scope: all commands including /log
    requests.post(f"{base}/setMyCommands", json={
        "commands": VIEWER_COMMANDS + ADMIN_EXTRA_COMMANDS,
        "scope": {"type": "chat", "chat_id": int(TELEGRAM_CHAT_ID)},
    }, timeout=10)
```

**Step 2: Call it at the top of `poll_updates()`, after the startup log lines**

```python
def poll_updates():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/getUpdates"
    offset = 0

    log("🤖 Approval handler started. Listening for button presses...")
    send_telegram("🤖 Approval handler is online and listening.")
    set_bot_commands()   # <-- add this line
    ...
```

**Step 3: Test manually**

Deploy and restart the approval handler. Open the bot in Telegram, type `/` — you should see the command menu appear.

**Step 4: Commit**
```bash
git add approval_handler.py
git commit -m "feat: register telegram command menu on startup"
```

---

### Task 3: Add IBKR query functions

**Files:**
- Modify: `approval_handler.py` — add 5 query functions before `poll_updates()`

Each function connects with a fresh `IB()`, queries read-only data, formats a string, disconnects, and returns the string. Use `clientId=3` (different from scanner=1 and approval handler=2).

**Step 1: Add `query_balance()`**

```python
def query_balance() -> str:
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=3, timeout=10)
        vals = {av.tag: av.value for av in ib.accountValues() if av.currency == 'USD'}
        equity   = float(vals.get('NetLiquidation', 0))
        cash     = float(vals.get('TotalCashValue', 0))
        buying   = float(vals.get('BuyingPower', 0))
        margin   = float(vals.get('MaintMarginReq', 0))
        return (
            f"💰 <b>Account Balance</b>\n\n"
            f"Net Liquidation: <b>${equity:,.2f}</b>\n"
            f"Cash Available:  <b>${cash:,.2f}</b>\n"
            f"Buying Power:    <b>${buying:,.2f}</b>\n"
            f"Margin Used:     <b>${margin:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Could not fetch balance: {e}"
    finally:
        ib.disconnect()
```

**Step 2: Add `query_positions()`**

```python
def query_positions() -> str:
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=3, timeout=10)
        positions = ib.positions()
        if not positions:
            return "📂 No open positions."
        lines = ["📂 <b>Open Positions</b>\n"]
        for p in positions:
            symbol  = p.contract.symbol
            qty     = p.position
            avg     = p.avgCost
            mkt     = p.marketValue if hasattr(p, 'marketValue') else 0
            unreal  = p.unrealizedPNL if hasattr(p, 'unrealizedPNL') else 0
            sign    = "+" if unreal >= 0 else ""
            lines.append(
                f"<b>{symbol}</b>: {qty:.0f} shares @ ${avg:.2f}\n"
                f"  Mkt: ${mkt:,.2f}  |  P&L: {sign}${unreal:,.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not fetch positions: {e}"
    finally:
        ib.disconnect()
```

**Step 3: Add `query_orders()`**

```python
def query_orders() -> str:
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=3, timeout=10)
        trades = ib.openTrades()
        if not trades:
            return "📋 No open orders."
        lines = ["📋 <b>Open Orders</b>\n"]
        for t in trades:
            sym    = t.contract.symbol
            action = t.order.action
            qty    = t.order.totalQuantity
            otype  = t.order.orderType
            lmt    = f"@ ${t.order.lmtPrice:.2f}" if t.order.lmtPrice else ""
            status = t.orderStatus.status
            lines.append(f"<b>{sym}</b>: {action} {qty:.0f} {otype} {lmt} [{status}]")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not fetch orders: {e}"
    finally:
        ib.disconnect()
```

**Step 4: Add `query_pnl()`**

```python
def query_pnl() -> str:
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=3, timeout=10)
        account = os.getenv("IB_ACCOUNT", "")
        pnl_obj = ib.reqPnL(account) if account else None
        ib.sleep(1)  # allow pnl subscription to populate
        if pnl_obj is None:
            return "❌ IB_ACCOUNT env var not set — cannot fetch P&L."
        daily   = pnl_obj.dailyPnL   or 0
        unreal  = pnl_obj.unrealizedPnL or 0
        real    = pnl_obj.realizedPnL   or 0
        sign_d  = "+" if daily  >= 0 else ""
        sign_u  = "+" if unreal >= 0 else ""
        sign_r  = "+" if real   >= 0 else ""
        return (
            f"📊 <b>P&L Summary</b>\n\n"
            f"Daily P&L:      <b>{sign_d}${daily:,.2f}</b>\n"
            f"Unrealized P&L: <b>{sign_u}${unreal:,.2f}</b>\n"
            f"Realized P&L:   <b>{sign_r}${real:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Could not fetch P&L: {e}"
    finally:
        ib.disconnect()
```

**Step 5: Add `query_trades()`**

```python
def query_trades() -> str:
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=3, timeout=10)
        today = datetime.now().strftime("%Y%m%d")
        fills = [f for f in ib.executions() if f.time.strftime("%Y%m%d") == today]
        if not fills:
            return "📈 No fills today."
        lines = ["📈 <b>Today's Fills</b>\n"]
        for f in fills:
            sym  = f.contract.symbol
            side = f.execution.side
            qty  = f.execution.shares
            px   = f.execution.price
            t    = f.time.strftime("%H:%M:%S")
            lines.append(f"<b>{sym}</b>: {side} {qty:.0f} @ ${px:.2f}  ({t})")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not fetch trades: {e}"
    finally:
        ib.disconnect()
```

**Step 6: Commit**
```bash
git add approval_handler.py
git commit -m "feat: add IBKR read-only query functions for bot commands"
```

---

### Task 4: Add local query functions (/status, /pending, /log)

**Files:**
- Modify: `approval_handler.py` — add 3 local query functions (no IBKR needed)

**Step 1: Add `query_status()`**

```python
def query_status() -> str:
    # Gateway ping
    import socket
    gw_up = False
    try:
        s = socket.create_connection((IB_HOST, IB_PORT), timeout=3)
        s.close()
        gw_up = True
    except OSError:
        pass

    # Last scan time from activity.log
    last_scan = "unknown"
    try:
        with open(ACTIVITY_LOG_FILE, "r") as f:
            for line in reversed(f.readlines()):
                if "ANALYSIS STARTED" in line or "RUN COMPLETE" in line:
                    last_scan = line.split("]")[0].strip("[")
                    break
    except Exception:
        pass

    gw_icon = "✅" if gw_up else "❌"
    return (
        f"🤖 <b>Bot Status</b>\n\n"
        f"IB Gateway ({IB_HOST}:{IB_PORT}): {gw_icon}\n"
        f"Approval handler: ✅ online\n"
        f"Last scan: {last_scan}"
    )
```

**Step 2: Add `query_pending()`**

```python
def query_pending() -> str:
    pending = load_pending()
    waiting = {k: v for k, v in pending.items() if v.get("status") == "pending"}
    if not waiting:
        return "✅ No pending orders."
    lines = [f"⏳ <b>Pending Approvals</b> ({len(waiting)})\n"]
    for oid, o in waiting.items():
        lines.append(
            f"<b>{o['symbol']}</b>: {o['qty']} shares @ ${o['entry_price']:.2f}\n"
            f"  TP: ${o['tp_price']:.2f} | SL: ${o['sl_price']:.2f}\n"
            f"  Created: {o['created']}"
        )
    return "\n".join(lines)
```

**Step 3: Add `query_log()` (admin only)**

```python
def query_log(n: int = 15) -> str:
    try:
        with open(ACTIVITY_LOG_FILE, "r") as f:
            lines = f.readlines()
        tail = lines[-n:] if len(lines) >= n else lines
        return "📜 <b>Activity Log (last {})</b>\n\n<pre>{}</pre>".format(
            n, "".join(tail).strip()
        )
    except Exception as e:
        return f"❌ Could not read log: {e}"
```

**Step 4: Commit**
```bash
git add approval_handler.py
git commit -m "feat: add local query functions (status, pending, log)"
```

---

### Task 5: Add command dispatcher + wire into poll loop

**Files:**
- Modify: `approval_handler.py` — add `handle_command()`, update `poll_updates()`

**Step 1: Add `handle_command()`**

```python
def handle_command(text: str, from_id: str):
    """Parse and dispatch a slash command. Returns reply string."""
    cmd = text.strip().lower().split("@")[0]  # strip /cmd@botname format

    if not is_allowed(from_id):
        return "🚫 You are not authorized to use this bot."

    if cmd == "/balance":
        return query_balance()
    elif cmd == "/positions":
        return query_positions()
    elif cmd == "/orders":
        return query_orders()
    elif cmd == "/pnl":
        return query_pnl()
    elif cmd == "/trades":
        return query_trades()
    elif cmd == "/status":
        return query_status()
    elif cmd == "/pending":
        return query_pending()
    elif cmd == "/log":
        if not is_admin(from_id):
            return "🚫 /log is restricted to the admin."
        return query_log()
    else:
        return None  # unknown command — ignore silently
```

**Step 2: Add `reply_to()` helper**

```python
def reply_to(chat_id: str, message: str):
    """Send a reply message to a specific chat."""
    if not TELEGRAM_BOT_KEY:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception:
        pass
```

**Step 3: Update `poll_updates()` to handle message updates**

In the `for update in updates:` loop, after the existing `callback = update.get("callback_query")` block, add:

```python
                # --- NEW: handle slash commands ---
                msg = update.get("message") or update.get("edited_message")
                if msg:
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text.startswith("/"):
                        log(f"📨 Command '{text}' from {chat_id}")
                        reply = handle_command(text, chat_id)
                        if reply:
                            reply_to(chat_id, reply)
                    continue
```

Make sure this is inside the `for update in updates:` loop and comes **after** the `callback_query` block (so button presses still work unchanged).

**Step 4: Commit**
```bash
git add approval_handler.py
git commit -m "feat: wire slash command dispatcher into telegram poll loop"
```

---

### Task 6: Add IB_ACCOUNT env var + deploy

**Files:**
- `.env` on Oracle VM — add `IB_ACCOUNT`
- Restart `approval_handler` systemd service (or screen session)

**Step 1: Find your account ID**

It's visible on the IBKR Gateway login screen, or run:
```bash
python -c "
from ib_insync import IB
ib = IB(); ib.connect('127.0.0.1', 4001, clientId=99)
print([av.account for av in ib.accountValues()][:1])
ib.disconnect()
"
```
It should be `U11801478` (already in CLAUDE.md).

**Step 2: Add to .env**
```bash
echo 'IB_ACCOUNT=U11801478' >> ~/algo-trader/.env
```

**Step 3: Deploy updated approval_handler.py to VM**
```bash
# From local machine:
scp -i ~/Downloads/"ssh-key-2026-04-04 (1).key" \
    approval_handler.py \
    ubuntu@129.159.139.113:~/algo-trader/approval_handler.py
```

**Step 4: Restart the approval handler on VM**
```bash
# SSH into VM first, then:
pkill -f approval_handler.py
cd ~/algo-trader && source venv/bin/activate
screen -dmS approval python approval_handler.py
```

**Step 5: Smoke test each command**

Send each command to the bot in Telegram and verify the response:
- `/status` — should show gateway up/down + last scan time
- `/balance` — equity, cash, buying power
- `/positions` — list of all positions
- `/orders` — open orders
- `/pnl` — daily P&L (requires IB_ACCOUNT)
- `/trades` — today's fills
- `/pending` — pending approvals (may be empty, that's fine)
- `/log` — last 15 lines of activity.log

**Step 6: Test viewer access**

Add a friend's chat ID to `TELEGRAM_VIEWER_IDS`, restart, have them try `/balance` (should work) and `/log` (should be rejected).

**Step 7: Final commit**
```bash
git add .env.example  # if you maintain one
git commit -m "feat: add IB_ACCOUNT env var for P&L queries"
```

---

## Summary

| Task | What it does |
|------|-------------|
| 1 | Access control: admin vs viewer helpers |
| 2 | Register command menu in Telegram on startup |
| 3 | IBKR read-only queries (balance, positions, orders, pnl, trades) |
| 4 | Local queries (status, pending, log) |
| 5 | Command dispatcher wired into poll loop |
| 6 | Deploy + smoke test |

All changes are in `approval_handler.py`. No new files. No new dependencies.
