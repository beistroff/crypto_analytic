import sys
import json
import requests
from datetime import datetime

def track_coin(api_key, symbol, start_price):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    parameters = {'symbol': symbol, 'convert': 'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, params=parameters)
        data = response.json()['data'][symbol.upper()]
        current_price = data['quote']['USD']['price']
        
        # Calculate percentage change from start price
        change = ((current_price - start_price) / start_price) * 100
        
        # Prepare output
        timestamp = datetime.now().strftime("%H:%M")
        status = "🟢 UP" if change > 0 else "🔴 DOWN"
        
        # Only print (which triggers telegram alert) if change is > 1% or < -1%
        if abs(change) >= 1.0:
            print(f"📡 TRACKING: {symbol.upper()} at {timestamp} UTC")
            print(f"• Current Price: ${current_price:.5f}")
            print(f"• Move from Entry: {status} {abs(change):.2f}%")
            print(f"Summary: Significant price action detected.")
        else:
            # Just for local logging, won't alert user unless script is run manually
            sys.stderr.write(f"DOGE at ${current_price:.5f} ({change:.2f}%). No alert.\n")
            
    except Exception as e:
        print(f"Tracking Error: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 track_coin.py <API_KEY> <SYMBOL> <START_PRICE>")
        sys.exit(1)
    track_coin(sys.argv[1], sys.argv[2], float(sys.argv[3]))
