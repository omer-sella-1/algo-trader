import os
import requests
import json
from dotenv import load_dotenv

# Load Keys
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")

# Config
BASE_URL = "https://paper-api.alpaca.markets"
HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "accept": "application/json"
}


def place_order():
    url = f"{BASE_URL}/v2/orders"

    payload = {
        "symbol": "SPY",
        "qty": "1",
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    }

    print("📨 Sending BUY order via HTTP...")

    try:
        response = requests.post(url, json=payload, headers=HEADERS)
        response.raise_for_status()  # Raise error if failed

        order = response.json()
        print(f"✅ SUCCESS! Order ID: {order['id']}")
        print(f"Status: {order['status']}")

    except requests.exceptions.HTTPError as e:
        response = requests.post(url, json=payload, headers=HEADERS)
        print(f"❌ HTTP Error: {e}")
        print(f"Details: {response.text}")


if __name__ == "__main__":
    place_order()