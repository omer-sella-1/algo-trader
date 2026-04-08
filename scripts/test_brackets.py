import os
import requests
from dotenv import load_dotenv

load_dotenv()
HEADERS = {
    "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
    "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY"),
    "accept": "application/json"
}
BASE_URL = "https://paper-api.alpaca.markets"

# Test Setup
symbol = "F"
qty = 1
limit_price = 11.50
take_profit = 12.50
stop_loss = 10.00

print(f"🧪 Sending Bracket Test for {symbol}...")

url = f"{BASE_URL}/v2/orders"
payload = {
    "symbol": symbol,
    "qty": str(qty),
    "side": "buy",
    "type": "limit",
    "limit_price": str(limit_price),
    "time_in_force": "day",
    "order_class": "bracket",  # <--- Automation Magic
    "take_profit": {"limit_price": str(take_profit)},
    "stop_loss": {"stop_price": str(stop_loss)}
}

try:
    r = requests.post(url, json=payload, headers=HEADERS)
    r.raise_for_status()
    order = r.json()
    print("✅ SUCCESS! Order Accepted.")
    print(f"ID: {order['id']}")
    print(f"Status: {order['status']} (Expected: 'accepted' or 'held')")

    if order['legs']:
        print("🦵 Legs Attached (TP/SL): YES")
    else:
        print("⚠️ Legs not visible yet (Normal if parent is not filled)")

except Exception as e:
    print(f"❌ FAILED: {e}")
    if 'r' in locals(): print(r.text)