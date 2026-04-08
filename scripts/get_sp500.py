import os
import requests
from dotenv import load_dotenv

# Load keys
load_dotenv()
AV_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")


def get_sp500_tickers():
    print("🌐 Fetching S&P 500 holdings from Alpha Vantage (via SPY)...")

    if not AV_API_KEY:
        print("❌ Error: ALPHAVANTAGE_API_KEY not found in .env file.")
        return []

    # API Parameters
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "ETF_PROFILE",
        "symbol": "SPY",
        "apikey": AV_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Check for API Limit or Error messages
        if "Information" in data:
            print("⚠️ API Limit Reached. Alpha Vantage allows 25 requests/day on free tier.")
            return []
        if "Error Message" in data:
            print(f"❌ API Error: {data['Error Message']}")
            return []

        # Parse Holdings
        if "holdings" in data:
            holdings_list = data["holdings"]

            # Extract just the ticker symbols
            tickers = [item['symbol'] for item in holdings_list]

            print(f"✅ Successfully loaded {len(tickers)} tickers from SPY.")
            return tickers
        else:
            print("❌ Unexpected Data Format: 'holdings' key missing.")
            # Print keys to debug what we actually got
            print(f"Received keys: {list(data.keys())}")
            return []

    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return []


if __name__ == "__main__":
    sp500 = get_sp500_tickers()
    if sp500:
        print(f"\nSample Tickers: {sp500[:10]}")