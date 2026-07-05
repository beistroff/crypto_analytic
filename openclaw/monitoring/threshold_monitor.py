import sys
import json
import requests
import os

def check_thresholds(api_key):
    # Thresholds we are monitoring
    # Format: {Symbol: (Lower_Alert, Upper_Alert)}
    targets = {
        "ADA": (0.225, 0.29),
        "BTC": (65000, 72000),
        "SOL": (75, 85),
        "LINK": (7.90, 10.20)
    }
    
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    parameters = {'symbol': ','.join(targets.keys()), 'convert': 'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, params=parameters)
        data = response.json()['data']
        
        alerts = []
        for symbol, (low, high) in targets.items():
            price = data[symbol]['quote']['USD']['price']
            if price <= low:
                alerts.append(f"🚨 {symbol} ALERT: Price is ${price:.4f}. HIT BUY ZONE (${low})!")
            elif price >= high:
                alerts.append(f"💰 {symbol} ALERT: Price is ${price:.4f}. HIT SELL ZONE (${high})!")
        
        if alerts:
            print("\n".join(alerts))
        else:
            # Silence for heartbeat
            pass
            
    except Exception as e:
        print(f"Error checking thresholds: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_thresholds(sys.argv[1])
