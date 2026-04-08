import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")

BASE_URL = "https://paper-api.alpaca.markets"
HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "accept": "application/json"
}


def cancel_all():
    # 1. Check for orders first
    orders_url = f"{BASE_URL}/v2/orders"
    response = requests.get(orders_url, headers=HEADERS, params={"status": "open"})
    orders = response.json()

    print(f"🔍 Found {len(orders)} open orders.")

    if len(orders) > 0:
        print("🗑️ sending DELETE request to cancel all...")
        # Alpaca has a handy endpoint to cancel ALL orders at once
        requests.delete(orders_url, headers=HEADERS)
        print("✅ Cancellation command sent.")
    else:
        print("😴 Nothing to cancel.")


if __name__ == "__main__":
    cancel_all()