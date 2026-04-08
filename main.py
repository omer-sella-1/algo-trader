import os
import sys
import requests
import pandas as pd
import csv
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from ib_insync import IB, Stock, MarketOrder

import time
import json

DRY_RUN = "--dry-run" in sys.argv
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() == "true"
PENDING_ORDERS_FILE = "pending_orders.json"

# ==========================================
# 🔐 CONFIGURATION
# ==========================================
load_dotenv()

# Alpaca (data only — free, no trading)
ALPACA_HEADERS = {
    "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
    "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY"),
    "accept": "application/json",
    "Content-Type": "application/json"
}
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"

# IBKR (trading)
IB_HOST = os.getenv("IB_GATEWAY_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_GATEWAY_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))

# FILES
TRADE_LOG_FILE = "trades.csv"
ACTIVITY_LOG_FILE = "activity.log"

# STRATEGY SETTINGS
SMA_PERIOD = 150
BB_LENGTH = 20
BB_STD = 1.5
RSI_PERIOD = 14
RSI_THRESH = 40

# 🚀 RISK SETTINGS
MAX_POSITIONS = 10
MAX_HOLDING_DAYS = 45
# Telegram
TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ==========================================
# 📐 PURE MATH ENGINE (No Libraries!)
# ==========================================

def calculate_sma(series, length):
    return series.rolling(window=length).mean()


def calculate_bb(series, length, std_dev):
    sma = series.rolling(window=length).mean()
    std = series.rolling(window=length).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return lower, upper


def calculate_rsi(series, length=14):
    """Wilder's RSI (Standard Implementation)"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=length - 1, min_periods=length).mean()
    avg_loss = loss.ewm(com=length - 1, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ==========================================
# 📝 LOGGING
# ==========================================
def log_event(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    with open(ACTIVITY_LOG_FILE, "a") as f: f.write(f"[{ts}] {message}\n")


def log_trade(symbol, side, qty, price, reason):
    exists = os.path.isfile(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, "a", newline='') as f:
        w = csv.writer(f)
        if not exists: w.writerow(["Time", "Symbol", "Side", "Qty", "Price", "Reason"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, side, qty, price, reason])


def send_telegram(message):
    """Send a message via Telegram bot. Fails silently if not configured."""
    if not TELEGRAM_BOT_KEY or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


def send_approval_request(order_id, symbol, qty, entry_price, tp_price, sl_price,
                          cash=0, occupied_count=0, rsi=0):
    """Send a Telegram message with Approve/Reject inline buttons."""
    if not TELEGRAM_BOT_KEY or not TELEGRAM_CHAT_ID:
        return
    cost = qty * entry_price
    potential_loss = (entry_price - sl_price) * qty
    potential_gain = (tp_price - entry_price) * qty
    risk_reward = potential_gain / potential_loss if potential_loss > 0 else 0
    text = (
        f"🔔 <b>TRADE APPROVAL REQUIRED</b>\n\n"
        f"<b>{symbol}</b> — {qty} shares @ ${entry_price:.2f}\n"
        f"TP: ${tp_price:.2f} (+${potential_gain:.2f})\n"
        f"SL: ${sl_price:.2f} (-${potential_loss:.2f})\n"
        f"R:R = 1:{risk_reward:.1f}\n\n"
        f"Cost: ${cost:.2f}\n"
        f"Cash after: ${cash - cost:.2f}\n"
        f"RSI: {rsi:.1f}\n"
        f"Slots: {occupied_count}/{MAX_POSITIONS}\n\n"
        f"Approve this trade?"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": json.dumps({"action": "approve", "id": order_id})},
            {"text": "❌ Reject", "callback_data": json.dumps({"action": "reject", "id": order_id})}
        ]]
    }
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }, timeout=10)
    except Exception:
        pass


def save_pending_order(order_id, symbol, qty, entry_price, tp_price, sl_price):
    """Save a pending order to JSON file for the approval handler to execute."""
    pending = {}
    if os.path.isfile(PENDING_ORDERS_FILE):
        with open(PENDING_ORDERS_FILE, 'r') as f:
            pending = json.load(f)

    pending[order_id] = {
        "symbol": symbol,
        "qty": qty,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending"
    }

    with open(PENDING_ORDERS_FILE, 'w') as f:
        json.dump(pending, f, indent=2)


# ==========================================
# 🌐 DATA ENGINE (Alpaca free data + AlphaVantage)
# ==========================================
def get_sp500_tickers():
    if not os.getenv("ALPHAVANTAGE_API_KEY"):
        log_event("❌ Error: ALPHAVANTAGE_API_KEY missing.")
        return []

    url = "https://www.alphavantage.co/query"
    params = {"function": "ETF_PROFILE", "symbol": "SPY", "apikey": os.getenv("ALPHAVANTAGE_API_KEY")}
    try:
        r = requests.get(url, params=params)
        data = r.json()
        if "holdings" in data:
            return [i['symbol'] for i in data["holdings"]]
        else:
            log_event("⚠️ AlphaVantage Limit. Using Fallback.")
            return ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "V"]
    except:
        return []


def get_market_data(symbol):
    end = datetime.now()
    start = end - timedelta(days=300)
    params = {"symbols": symbol, "timeframe": "1Day", "start": start.strftime("%Y-%m-%d"), "limit": 1000, "feed": "iex"}
    try:
        r = requests.get(DATA_URL, headers=ALPACA_HEADERS, params=params)
        if "bars" not in r.json() or symbol not in r.json()["bars"]: return None

        df = pd.DataFrame(r.json()["bars"][symbol])
        df.rename(columns={'t': 'timestamp', 'c': 'close'}, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # Apply Math
        df['sma_150'] = calculate_sma(df['close'], SMA_PERIOD)
        df['lower_bb'], df['upper_bb'] = calculate_bb(df['close'], BB_LENGTH, BB_STD)
        df['rsi'] = calculate_rsi(df['close'], RSI_PERIOD)

        return df
    except:
        return None


# ==========================================
# 🏦 IBKR TRADING ENGINE (ib_insync)
# ==========================================

def submit_bracket_order(ib, symbol, qty, entry_price, tp_price, sl_price):
    contract = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(contract)

    bracket = ib.bracketOrder(
        action='BUY',
        quantity=qty,
        limitPrice=round(entry_price, 2),
        takeProfitPrice=round(tp_price, 2),
        stopLossPrice=round(sl_price, 2)
    )

    # Entry expires end of day, TP/SL persist until hit
    bracket[0].tif = 'DAY'
    bracket[1].tif = 'GTC'
    bracket[2].tif = 'GTC'

    log_event(f"📋 BRACKET ATTEMPT: Buy {qty} {symbol} @ {entry_price:.2f} | TP: {tp_price:.2f} | SL: {sl_price:.2f}")

    try:
        for order in bracket:
            ib.placeOrder(contract, order)
        ib.sleep(1)  # Allow order to propagate
        log_event(f"✅ BRACKET SUBMITTED: {symbol}")
        log_trade(symbol, "BUY_BRACKET", qty, entry_price, "New Entry")
        send_telegram(f"📈 <b>NEW ENTRY</b>: {symbol}\nBuy {qty} @ ${entry_price:.2f}\nTP: ${tp_price:.2f} | SL: ${sl_price:.2f}")
    except Exception as e:
        log_event(f"❌ Order Failed: {e}")
        log_trade(symbol, "BUY_FAILED", qty, entry_price, f"Failed: {e}")
        send_telegram(f"❌ <b>ORDER FAILED</b>: {symbol}\n{e}")


def close_position(ib, symbol, qty, reason):
    """Closes a position immediately (Market Sell)"""
    contract = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(contract)
    order = MarketOrder('SELL', qty)

    try:
        ib.placeOrder(contract, order)
        ib.sleep(1)
        log_event(f"👋 CLOSING {symbol}: {reason}")
        log_trade(symbol, "SELL_CLOSE", qty, "Market", reason)
        send_telegram(f"📉 <b>CLOSED</b>: {symbol}\nSold {qty} shares (Market)\nReason: {reason}")
    except Exception as e:
        log_event(f"❌ Failed to close {symbol}: {e}")
        send_telegram(f"❌ <b>CLOSE FAILED</b>: {symbol}\n{e}")


def get_bot_managed_symbols():
    """Returns set of symbols the bot has opened (BUY_BRACKET) and not yet closed (SELL_CLOSE)."""
    if not os.path.isfile(TRADE_LOG_FILE):
        return set()

    buys = set()
    sells = set()
    with open(TRADE_LOG_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Side'] == 'BUY_BRACKET':
                buys.add(row['Symbol'])
            elif row['Side'] == 'SELL_CLOSE':
                sells.add(row['Symbol'])

    return buys - sells


def get_position_age_days(symbol):
    """Finds how many days we have held a position by checking trades.csv"""
    try:
        if not os.path.isfile(TRADE_LOG_FILE):
            return 0

        with open(TRADE_LOG_FILE, 'r') as f:
            reader = csv.DictReader(f)
            buy_dates = []
            for row in reader:
                if row['Symbol'] == symbol and row['Side'] == 'BUY_BRACKET':
                    buy_dates.append(row['Time'])

        if not buy_dates:
            return 0

        # Most recent buy entry
        last_buy = datetime.strptime(buy_dates[-1], "%Y-%m-%d %H:%M:%S")
        last_buy = last_buy.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - last_buy).days

    except Exception as e:
        log_event(f"⚠️ Could not verify age for {symbol}: {e}")
        return 0


# ==========================================
# 🧠 MAIN LOGIC
# ==========================================
def run_analysis():
    log_event(f"--- 🔎 ANALYSIS STARTED {'(DRY RUN)' if DRY_RUN else ''} ---")

    # Connect to IBKR
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=10)
        log_event(f"🔗 Connected to IBKR Gateway ({IB_HOST}:{IB_PORT})")
    except Exception as e:
        log_event(f"🔥 Cannot connect to IBKR: {e}")
        send_telegram(f"🔥 <b>Cannot connect to IBKR</b>\n{e}")
        return

    try:
        # 1. Account Snapshot
        account_values = {}
        for av in ib.accountValues():
            if av.currency == 'USD':
                try:
                    account_values[av.tag] = float(av.value)
                except ValueError:
                    pass
        equity = account_values.get('NetLiquidation', 0)
        cash = account_values.get('TotalCashValue', 0)

        # Bot only uses actual cash — never margin/leverage
        bot_symbols = get_bot_managed_symbols()
        open_trades = ib.openTrades()
        order_symbols = {t.contract.symbol for t in open_trades if t.contract.symbol in bot_symbols}
        occupied = bot_symbols | order_symbols

        log_event(f"💰 Equity: ${equity:,.2f} | Cash: ${cash:,.2f}")
        log_event(f"📂 Bot-managed Slots: {len(occupied)}/{MAX_POSITIONS} (symbols: {occupied or 'none'})")

        # 2. RECONCILE: free slots where TP/SL already filled
        ib_positions = {pos.contract.symbol: pos for pos in ib.positions()}
        for symbol in list(bot_symbols):
            if symbol not in ib_positions and symbol not in order_symbols:
                log_event(f"🔄 {symbol}: position gone (TP/SL filled). Freeing slot.")
                log_trade(symbol, "SELL_CLOSE", 0, "Auto", "TP/SL filled (reconciled)")
                send_telegram(f"🔄 <b>{symbol}</b> position closed by TP/SL. Slot freed.")
                occupied.discard(symbol)

        # 3. CHECK FOR STALE POSITIONS (Time Stop) 🛑
        # Only check positions the bot opened
        for symbol in list(bot_symbols):
            if symbol not in ib_positions:
                continue  # Bot opened it but position no longer exists (filled TP/SL)

            pos = ib_positions[symbol]
            qty = pos.position
            days_held = get_position_age_days(symbol)

            if days_held > MAX_HOLDING_DAYS:
                log_event(f"⏳ {symbol} held for {days_held} days (Limit: {MAX_HOLDING_DAYS}). Closing as Stale.")
                if DRY_RUN:
                    log_event(f"🔒 DRY RUN: Would close {symbol} ({qty} shares)")
                else:
                    close_position(ib, symbol, qty, f"Stale Trade (> {MAX_HOLDING_DAYS} days)")
                if symbol in occupied: occupied.remove(symbol)

        # 4. SCAN FOR NEW ENTRIES 📡
        if len(occupied) >= MAX_POSITIONS:
            log_event("🚫 Portfolio Full. Skipping Scan.")
            return

        universe = get_sp500_tickers()
        scan_limit = 50
        log_event(f"📡 Scanning Top {scan_limit} stocks...")

        for symbol in universe[:scan_limit]:
            if symbol in occupied: continue

            df = get_market_data(symbol)
            if df is None or len(df) < SMA_PERIOD: continue

            price = df['close'].iloc[-1]
            sma150 = df['sma_150'].iloc[-1]
            lower_bb = df['lower_bb'].iloc[-1]
            upper_bb = df['upper_bb'].iloc[-1]
            rsi = df['rsi'].iloc[-1]

            if (price > sma150) and (price < lower_bb) and (rsi < RSI_THRESH):
                log_event(f"🚀 SIGNAL: {symbol} | Price: {price:.2f} | RSI: {rsi:.2f}")

                # Position Sizing: 10% of cash, no margin
                # For stocks up to $500, buy at least 1 share
                target_amt = cash * 0.10
                shares = max(round(target_amt / price), 1) if price <= 500 else round(target_amt / price)

                if shares > 0 and cash >= (shares * price):
                    # 1. Entry: Limit order 0.5% above close
                    entry = price * 1.005
                    # 2. TP: Upper Band (min 2% gain)
                    tp = max(upper_bb, entry * 1.02)
                    # 3. SL: 10% Risk
                    sl = entry * 0.90

                    if DRY_RUN:
                        log_event(f"🔒 DRY RUN: Would submit bracket for {shares} {symbol} @ {entry:.2f} | TP: {tp:.2f} | SL: {sl:.2f}")
                    elif REQUIRE_APPROVAL:
                        order_id = f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        save_pending_order(order_id, symbol, shares, entry, tp, sl)
                        send_approval_request(order_id, symbol, shares, entry, tp, sl,
                                              cash=cash, occupied_count=len(occupied), rsi=rsi)
                        log_event(f"⏳ APPROVAL REQUESTED: {symbol} ({shares} shares @ {entry:.2f})")
                    else:
                        submit_bracket_order(ib, symbol, shares, entry, tp, sl)

                    cash -= (shares * price)
                    occupied.add(symbol)

                    if len(occupied) >= MAX_POSITIONS:
                        log_event("🛑 Max Positions Reached.")
                        break

        log_event(f"--- ✅ RUN COMPLETE {'(DRY RUN)' if DRY_RUN else ''} ---")
        send_telegram(
            f"✅ <b>Run Complete</b> {'(DRY RUN)' if DRY_RUN else ''}\n"
            f"Equity: ${equity:,.2f} | Cash: ${cash:,.2f}\n"
            f"Slots: {len(occupied)}/{MAX_POSITIONS}"
        )

    finally:
        ib.disconnect()
        log_event("🔌 Disconnected from IBKR")


if __name__ == "__main__":
    try:
        run_analysis()
    except Exception as e:
        log_event(f"🔥 CRITICAL: {e}")
        send_telegram(f"🔥 <b>CRITICAL ERROR</b>\n{e}")
