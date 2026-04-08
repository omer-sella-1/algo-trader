import os
import requests
import json
from dotenv import load_dotenv

# 🔐 CONFIGURATION
load_dotenv()
HEADERS = {
    "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
    "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY"),
    "accept": "application/json"
}
BASE_URL = "https://paper-api.alpaca.markets"

# 🎯 YOUR MANUAL TARGETS
TARGETS = {
    "ABBV": {"sl": 203.14, "tp": 235.29},
    "GE": {"sl": 255.89, "tp": 304.73},
    "LLY": {"sl": 888.52, "tp": 1089.42}
}


def get_position_qty(symbol):
    try:
        url = f"{BASE_URL}/v2/positions/{symbol}"
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 404:
            print(f"⚠️ Warning: You don't hold {symbol}. Skipping.")
            return 0
        return float(r.json()['qty'])
    except Exception as e:
        print(f"❌ Error checking position for {symbol}: {e}")
        return 0


def place_oco_protection(symbol, qty, sl_price, tp_price):
    url = f"{BASE_URL}/v2/orders"

    # 📝 CORRECT OCO PAYLOAD
    # We must define the Take Profit TWICE:
    # 1. As the main limit order (root level)
    # 2. Inside the 'take_profit' object (API requirement)

    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "sell",
        "type": "limit",
        "limit_price": str(tp_price),  # Root Level (The actual order)
        "time_in_force": "gtc",
        "order_class": "oco",  # One-Cancels-Other
        "take_profit": {
            "limit_price": str(tp_price)  # Required nested block
        },
        "stop_loss": {
            "stop_price": str(sl_price)
        }
    }

    try:
        r = requests.post(url, json=payload, headers=HEADERS)

        if r.status_code != 200:
            print(f"❌ FAILED {symbol}: {r.json()}")
        else:
            print(f"✅ PROTECTED {symbol}: Sold {qty} (TP: ${tp_price} | SL: ${sl_price})")

    except Exception as e:
        print(f"❌ CONNECTION ERROR {symbol}: {e}")


# ==========================
# 🚀 MAIN EXECUTION
# ==========================
if __name__ == "__main__":
    print("🛡️ Applying OCO Protection to Existing Positions...\n")

    for symbol, targets in TARGETS.items():
        qty = get_position_qty(symbol)

        if qty > 0:
            place_oco_protection(symbol, qty, targets['sl'], targets['tp'])
        else:
            print(f"Skipping {symbol} (Qty is 0)")

    print("\n✅ Done. Check your Alpaca Dashboard to verify 'GTC' orders.")