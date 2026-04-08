import os
import requests
import json
from dotenv import load_dotenv

# 1. Load your keys
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")

# 2. Configuration
# Use 'paper-api.alpaca.markets' for paper trading
# Use 'api.alpaca.markets' for live trading
BASE_URL = "https://paper-api.alpaca.markets"
ACCOUNT_URL = f"{BASE_URL}/v2/account"

# 3. Create the Headers (This is the authentication)
headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "accept": "application/json"
}


def get_account():
    try:
        # Send GET request
        response = requests.get(ACCOUNT_URL, headers=headers)

        # Check if successful
        response.raise_for_status()

        # Parse JSON
        account_data = response.json()

        print("\n--- 🏦 Account Information ---")
        print(f"ID: {account_data.get('id')}")
        print(f"Status: {account_data.get('status')}")
        print(f"Cash: ${account_data.get('cash')}")
        print(f"Buying Power: ${account_data.get('buying_power')}")
        print(f"Portfolio Value: ${account_data.get('equity')}")

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    get_account()