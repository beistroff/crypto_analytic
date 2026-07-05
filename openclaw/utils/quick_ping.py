"""
A simple script to get a quick price check for BTC and SOL.
"""

import sys
import json
import requests
import argparse

def quick_ping(api_key):
    """
    Fetches the price of BTC and SOL from CoinMarketCap.

    Args:
        api_key (str): The API key for CoinMarketCap.
    """
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    # Monitoring our main interest: BTC and SOL
    parameters = {'symbol': 'BTC,SOL', 'convert': 'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, params=parameters)
        data = response.json()['data']
        
        btc_price = data['BTC']['quote']['USD']['price']
        sol_price = data['SOL']['quote']['USD']['price']
        
        output = [
            "⚡️ QUICK MARKET PING (System Auto-Report)",
            f"• BTC: ${btc_price:,.2f}",
            f"• SOL: ${sol_price:,.2f}",
            "",
            "Status: System check complete. No AI analysis requested."
        ]
        print("\n".join(output))
            
    except Exception as e:
        print(f"Ping Error: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quick market ping for BTC and SOL")
    parser.add_argument("--api_key", required=True, help="CoinMarketCap API key")
    args = parser.parse_args()
    quick_ping(args.api_key)
