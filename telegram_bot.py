"""
Telegram Bot for algo-trader.
Runs as a long-lived service. Handles slash commands (/balance, /positions,
/orders, /pnl, /trades, /status, /pending, /log) and inline approval buttons.
"""
import os
import json
import time
import socket
import requests
from datetime import datetime
from dotenv import load_dotenv
from ib_insync import IB, Stock

load_dotenv()

TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_VIEWER_IDS = set(
    i.strip() for i in os.getenv("TELEGRAM_VIEWER_IDS", "").split(",") if i.strip()
)
IB_HOST = os.getenv("IB_GATEWAY_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_GATEWAY_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "2"))  # Different clientId from scanner

PENDING_ORDERS_FILE = "pending_orders.json"
TRADE_LOG_FILE = "trades.csv"
ACTIVITY_LOG_FILE = "activity.log"


def is_admin(chat_id: str) -> bool:
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


def is_allowed(chat_id: str) -> bool:
    return is_admin(chat_id) or str(chat_id) in TELEGRAM_VIEWER_IDS


def log(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    with open(ACTIVITY_LOG_FILE, "a") as f:
        f.write(f"[{ts}] {message}\n")


def send_telegram(message):
    if not TELEGRAM_BOT_KEY or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


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
    try:
        requests.post(f"{base}/setMyCommands", json={
            "commands": VIEWER_COMMANDS,
            "scope": {"type": "default"},
        }, timeout=10)
        requests.post(f"{base}/setMyCommands", json={
            "commands": VIEWER_COMMANDS + ADMIN_EXTRA_COMMANDS,
            "scope": {"type": "chat", "chat_id": int(TELEGRAM_CHAT_ID)},
        }, timeout=10)
    except Exception:
        pass


def answer_callback(callback_query_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=10)
    except Exception:
        pass


def load_pending():
    if os.path.isfile(PENDING_ORDERS_FILE):
        with open(PENDING_ORDERS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_pending(pending):
    with open(PENDING_ORDERS_FILE, 'w') as f:
        json.dump(pending, f, indent=2)


def log_trade(symbol, side, qty, price, reason):
    import csv
    exists = os.path.isfile(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, "a", newline='') as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Time", "Symbol", "Side", "Qty", "Price", "Reason"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, side, qty, price, reason])


def execute_order(order_data):
    """Connect to IBKR and place the bracket order."""
    symbol = order_data["symbol"]
    qty = order_data["qty"]
    entry_price = order_data["entry_price"]
    tp_price = order_data["tp_price"]
    sl_price = order_data["sl_price"]

    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=10)

        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)

        bracket = ib.bracketOrder(
            action='BUY',
            quantity=qty,
            limitPrice=round(entry_price, 2),
            takeProfitPrice=round(tp_price, 2),
            stopLossPrice=round(sl_price, 2)
        )

        bracket[0].tif = 'DAY'
        bracket[1].tif = 'GTC'
        bracket[2].tif = 'GTC'

        for order in bracket:
            ib.placeOrder(contract, order)
        ib.sleep(1)

        log(f"✅ APPROVED & SUBMITTED: {symbol} ({qty} shares @ {entry_price:.2f})")
        log_trade(symbol, "BUY_BRACKET", qty, entry_price, "Approved Entry")
        send_telegram(
            f"📈 <b>ORDER PLACED</b>: {symbol}\n"
            f"Buy {qty} @ ${entry_price:.2f}\n"
            f"TP: ${tp_price:.2f} | SL: ${sl_price:.2f}"
        )
        return True

    except Exception as e:
        log(f"❌ Failed to execute {symbol}: {e}")
        send_telegram(f"❌ <b>EXECUTION FAILED</b>: {symbol}\n{e}")
        return False

    finally:
        ib.disconnect()


IB_QUERY_CLIENT_ID = int(os.getenv("IB_QUERY_CLIENT_ID", "3"))
IB_ACCOUNT = os.getenv("IB_ACCOUNT", "")

# Persistent read-only connection reused by all query functions
ib_query = IB()


def ensure_connected():
    """Reconnect ib_query if the connection dropped (e.g. after gateway restart)."""
    if not ib_query.isConnected():
        ib_query.connect(IB_HOST, IB_PORT, clientId=IB_QUERY_CLIENT_ID, timeout=10)


def query_balance() -> str:
    try:
        ensure_connected()
        vals = {av.tag: av.value for av in ib_query.accountValues() if av.currency == 'USD'}
        equity  = float(vals.get('NetLiquidation', 0))
        cash    = float(vals.get('TotalCashValue', 0))
        buying  = float(vals.get('BuyingPower', 0))
        margin  = float(vals.get('MaintMarginReq', 0))
        return (
            f"💰 <b>Account Balance</b>\n\n"
            f"Net Liquidation: <b>${equity:,.2f}</b>\n"
            f"Cash Available:  <b>${cash:,.2f}</b>\n"
            f"Buying Power:    <b>${buying:,.2f}</b>\n"
            f"Margin Used:     <b>${margin:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Could not fetch balance: {e}"


def query_positions() -> str:
    try:
        ensure_connected()
        portfolio = ib_query.portfolio()
        if not portfolio:
            return "📂 No open positions."
        lines = ["📂 <b>Open Positions</b>\n"]
        for item in portfolio:
            symbol = item.contract.symbol
            qty    = item.position
            avg    = item.averageCost
            mkt    = item.marketValue
            unreal = item.unrealizedPNL
            sign   = "+" if unreal >= 0 else ""
            lines.append(
                f"<b>{symbol}</b>: {qty:.0f} shares @ ${avg:.2f}\n"
                f"  Mkt: ${mkt:,.2f}  |  P&L: {sign}${unreal:,.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not fetch positions: {e}"


def query_orders() -> str:
    try:
        ensure_connected()
        trades = ib_query.reqAllOpenOrders()
        if not trades:
            return "📋 No open orders."
        lines = ["📋 <b>Open Orders</b>\n"]
        for t in trades:
            sym    = t.contract.symbol
            action = t.order.action
            qty    = t.order.totalQuantity
            otype  = t.order.orderType
            lmt    = f"@ ${t.order.lmtPrice:.2f}" if t.order.lmtPrice else (f"@ ${t.order.auxPrice:.2f}" if t.order.auxPrice else "")
            status = t.orderStatus.status
            lines.append(f"<b>{sym}</b>: {action} {qty:.0f} {otype} {lmt} [{status}]")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not fetch orders: {e}"


def query_pnl() -> str:
    if not IB_ACCOUNT:
        return "❌ IB_ACCOUNT env var not set — cannot fetch P&L."
    try:
        ensure_connected()
        pnl_obj = ib_query.reqPnL(IB_ACCOUNT)
        ib_query.sleep(0.5)
        daily  = getattr(pnl_obj, 'dailyPnL', 0) or 0
        unreal = getattr(pnl_obj, 'unrealizedPnL', 0) or 0
        real   = getattr(pnl_obj, 'realizedPnL', 0) or 0
        def sign(v): return "+" if v >= 0 else ""
        return (
            f"📊 <b>P&L Summary</b>\n\n"
            f"Daily P&L:      <b>{sign(daily)}${daily:,.2f}</b>\n"
            f"Unrealized P&L: <b>{sign(unreal)}${unreal:,.2f}</b>\n"
            f"Realized P&L:   <b>{sign(real)}${real:,.2f}</b>"
        )
    except Exception as e:
        return f"❌ Could not fetch P&L: {e}"


def query_trades() -> str:
    try:
        ensure_connected()
        today = datetime.now().strftime("%Y%m%d")
        fills = [f for f in ib_query.executions() if f.time.strftime("%Y%m%d") == today]
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


def query_status() -> str:
    gw_up = False
    try:
        s = socket.create_connection((IB_HOST, IB_PORT), timeout=3)
        s.close()
        gw_up = True
    except OSError:
        pass

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


def query_pending() -> str:
    pending = load_pending()
    waiting = {k: v for k, v in pending.items() if v.get("status") == "pending"}
    if not waiting:
        return "✅ No pending orders."
    lines = [f"⏳ <b>Pending Approvals</b> ({len(waiting)})\n"]
    for o in waiting.values():
        lines.append(
            f"<b>{o['symbol']}</b>: {o['qty']} shares @ ${o['entry_price']:.2f}\n"
            f"  TP: ${o['tp_price']:.2f} | SL: ${o['sl_price']:.2f}\n"
            f"  Created: {o['created']}"
        )
    return "\n".join(lines)


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


def reply_to(chat_id: str, message: str):
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


def handle_command(text: str, from_id: str) -> str:
    if not is_allowed(from_id):
        return "🚫 You are not authorized to use this bot."

    cmd = text.strip().lower().split("@")[0]  # handle /cmd@botname format

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
    return None


def poll_updates():
    """Long-poll Telegram for callback button presses."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/getUpdates"
    offset = 0

    log("🤖 Approval handler started. Listening for button presses...")
    send_telegram("🤖 Approval handler is online and listening.")
    set_bot_commands()

    try:
        ib_query.connect(IB_HOST, IB_PORT, clientId=IB_QUERY_CLIENT_ID, timeout=10)
        log("🔗 Query connection established (clientId=3)")
    except Exception as e:
        log(f"⚠️ Query connection failed at startup (will retry on first command): {e}")

    while True:
        try:
            r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            updates = r.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                # Handle slash commands from message updates
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

                callback = update.get("callback_query")
                if not callback:
                    continue

                # Verify it's from the right user
                if str(callback["from"]["id"]) != str(TELEGRAM_CHAT_ID):
                    continue

                try:
                    data = json.loads(callback["data"])
                except (json.JSONDecodeError, KeyError):
                    continue

                action = data.get("action")
                order_id = data.get("id")

                if not action or not order_id:
                    continue

                pending = load_pending()

                if order_id not in pending:
                    answer_callback(callback["id"], "Order not found or already processed.")
                    continue

                if pending[order_id]["status"] != "pending":
                    answer_callback(callback["id"], f"Order already {pending[order_id]['status']}.")
                    continue

                if action == "approve":
                    answer_callback(callback["id"], "Approved! Placing order...")
                    log(f"👍 Order {order_id} APPROVED")

                    success = execute_order(pending[order_id])
                    pending[order_id]["status"] = "executed" if success else "failed"

                elif action == "reject":
                    answer_callback(callback["id"], "Order rejected.")
                    log(f"👎 Order {order_id} REJECTED")
                    pending[order_id]["status"] = "rejected"
                    send_telegram(f"🚫 <b>REJECTED</b>: {pending[order_id]['symbol']}")

                save_pending(pending)

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            log(f"⚠️ Polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    poll_updates()
