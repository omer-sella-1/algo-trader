import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 🔐 CONFIGURATION
load_dotenv()
HEADERS = {
    "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
    "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY"),
    "accept": "application/json"
}
BASE_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"


# 📐 PURE PANDAS MATH (No Libraries)
def calculate_bb_upper(series, length=20, std=1.5):
    sma = series.rolling(window=length).mean()
    s = series.rolling(window=length).std()
    upper = sma + (s * std)
    return upper


def get_levels(symbol, entry_price):
    # Fetch Data
    end = datetime.now()
    start = end - timedelta(days=200)
    params = {"symbols": symbol, "timeframe": "1Day", "start": start.strftime("%Y-%m-%d"), "limit": 200, "feed": "iex"}

    try:
        r = requests.get(DATA_URL, headers=HEADERS, params=params)
        data = r.json()
        if "bars" not in data or symbol not in data["bars"]:
            print(f"Skipping {symbol} (No Data)")
            return

        df = pd.DataFrame(data["bars"][symbol])
        df.rename(columns={'c': 'close'}, inplace=True)

        # Math
        df['upper_bb'] = calculate_bb_upper(df['close'])
        upper_band = df['upper_bb'].iloc[-1]

        # Logic
        tp = max(upper_band, entry_price * 1.02)  # Min 2% profit
        sl = entry_price * 0.90  # 10% Stop

        print(f"--- {symbol} ---")
        print(f"Entry Price:   ${entry_price:.2f}")
        print(f"🛑 STOP LOSS:   ${sl:.2f}")
        print(f"💵 TAKE PROFIT: ${tp:.2f}")
        print("-------------------------")
    except Exception as e:
        print(f"Error for {symbol}: {e}")


# Run
print("\nFetching your open positions...")
pos_r = requests.get(f"{BASE_URL}/v2/positions", headers=HEADERS)
positions = pos_r.json()

if not positions:
    print("No open positions found.")
else:
    for p in positions:
        get_levels(p['symbol'], float(p['avg_entry_price']))