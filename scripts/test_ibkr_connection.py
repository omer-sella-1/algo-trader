"""
Quick smoke test for IBKR connectivity using ib_insync (pure Python).
Prerequisites:
  1. TWS or IB Gateway running
  2. API enabled in TWS: File > Global Configuration > API > Settings
     - Check "Enable ActiveX and Socket Clients"
     - Port: 7497 (paper) or 7496 (live)
     - Add 127.0.0.1 to trusted IPs
"""

from ib_insync import IB, Stock, util


def main():
    ib = IB()

    # Connect — change port to 7496 for live, 7497 for paper TWS, 4002 for paper Gateway
    print("=" * 50)
    print("IBKR Connection Test (ib_insync)")
    print("=" * 50)

    print("\n1. Connecting to TWS/Gateway...")
    try:
        ib.connect('127.0.0.1', 4001, clientId=1, timeout=10, readonly=True)
    except Exception as e:
        print(f"   FAILED: {e}")
        print("\n   Make sure TWS or IB Gateway is running with API enabled.")
        print("   Check your port in ~/Jts/jts.ini (LocalServerPort)")
        return

    print(f"   Connected: {ib.isConnected()}")

    # Accounts
    print("\n2. Accounts...")
    accounts = ib.managedAccounts()
    print(f"   Accounts: {accounts}")

    # Account summary
    print("\n3. Account summary...")
    values = ib.accountValues()
    for tag in ['NetLiquidation', 'TotalCashValue', 'BuyingPower', 'GrossPositionValue']:
        for av in values:
            if av.tag == tag and av.currency == 'USD':
                print(f"   {tag}: ${float(av.value):,.2f}")

    # Positions
    print("\n4. Positions...")
    positions = ib.positions()
    if not positions:
        print("   No open positions.")
    else:
        for pos in positions:
            print(f"   {pos.contract.symbol}: {pos.position} shares @ avg ${pos.avgCost:.2f}")

    # Search contract
    print("\n5. Contract lookup: AAPL...")
    contract = Stock('AAPL', 'SMART', 'USD')
    details = ib.qualifyContracts(contract)
    if details:
        print(f"   Found: {contract.symbol} (conId: {contract.conId})")
    else:
        print("   Failed to qualify contract.")

    # Historical data
    print("\n6. Historical data (AAPL, 5 days, daily bars)...")
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='5 D',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1
    )
    df = util.df(bars)
    if df is not None and not df.empty:
        print(f"   Got {len(df)} bars:")
        for _, row in df.iterrows():
            print(f"   {row['date']}  O:{row['open']:.2f} H:{row['high']:.2f} "
                  f"L:{row['low']:.2f} C:{row['close']:.2f} V:{int(row['volume'])}")
    else:
        print("   No data returned (may need market data subscription).")

    # Open orders
    print("\n7. Open orders...")
    trades = ib.openTrades()
    if not trades:
        print("   No open orders.")
    else:
        for trade in trades:
            print(f"   {trade.contract.symbol} {trade.order.action} "
                  f"{trade.order.totalQuantity} @ {trade.orderStatus.status}")

    print("\n" + "=" * 50)
    print("All tests complete!")
    ib.disconnect()


if __name__ == "__main__":
    main()
