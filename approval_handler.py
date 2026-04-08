"""
Telegram Approval Handler for algo-trader.
Runs as a long-lived service. Listens for inline button callbacks
and executes approved orders via IBKR.
"""
import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from ib_insync import IB, Stock

load_dotenv()

TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
IB_HOST = os.getenv("IB_GATEWAY_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_GATEWAY_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "2"))  # Different clientId from scanner

PENDING_ORDERS_FILE = "pending_orders.json"
TRADE_LOG_FILE = "trades.csv"
ACTIVITY_LOG_FILE = "activity.log"


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


def poll_updates():
    """Long-poll Telegram for callback button presses."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/getUpdates"
    offset = 0

    log("🤖 Approval handler started. Listening for button presses...")
    send_telegram("🤖 Approval handler is online and listening.")

    while True:
        try:
            r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            updates = r.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

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
