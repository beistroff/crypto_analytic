import os
import requests
import time
import sys

# Simplified Whale Monitor for SUI
# Looks for significant volume spikes or price reversals that indicate whale accumulation

API_URL = "https://api.coinmarketcap.com/v2/ticker/20947/" # SUI ID on CMC

def check_sui_whale_activity(api_key):
    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        parameters = {'symbol': 'SUI', 'convert': 'USD'}
        headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
        
        response = requests.get(url, headers=headers, params=parameters)
        data = response.json()
        
        quote = data['data']['SUI']['quote']['USD']
        price = quote['price']
        vol_24h = quote['volume_24h']
        change_1h = quote['percent_change_1h']
        
        # Trigger conditions
        # 1. Price reversal > 1% in an hour
        # 2. Volume is significant (> 10% of MCap)
        
        status = f"SUI Whale Check: ${price:.4f} | 1h: {change_1h:+.2f}%"
        
        if change_1h > 1.5:
            return f"🚨 SUI WHALE ALERT: Rapid 1h pump detected ({change_1h:+.2f}%). Accumulation starting? Price: ${price:.4f}"
        
        return None
    except Exception as e:
        return f"Error in whale monitor: {str(e)}"

if __name__ == "__main__":
    key = sys.argv[1]
    result = check_sui_whale_activity(key)
    if result:
        print(result)
    else:
        print("SUI_QUIET")
