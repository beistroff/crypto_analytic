"""
Generates a summary of the cryptocurrency portfolio.

This script reads the portfolio from a JSON file, fetches current prices from
CoinMarketCap, and calculates the current value and ROI for each asset and
the total portfolio.
"""

import requests
import json
import os
import sys
import argparse

DEFAULT_PORTFOLIO_FILE = os.path.join(os.path.expanduser("~"), "sentinel", "portfolio.json")

def get_cmc_prices(symbols, api_key):
    """
    Fetches cryptocurrency prices from CoinMarketCap.

    Args:
        symbols (list): A list of cryptocurrency symbols.
        api_key (str): The API key for CoinMarketCap.

    Returns:
        dict: A dictionary of prices, or None if the API call fails.
    """
    base_url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    parameters = {
        'symbol': ','.join(symbols),
        'convert': 'USD'
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key,
    }

    try:
        response = requests.get(base_url, headers=headers, params=parameters)
        data = response.json()
        prices = {}
        for symbol in symbols:
            if symbol == "USDT":
                prices[symbol] = 1.0
                continue
            
            price = data['data'][symbol]['quote']['USD']['price']
            prices[symbol] = price
        return prices
    except Exception:
        return None

def get_balance(api_key, portfolio_file=DEFAULT_PORTFOLIO_FILE):
    """
    Calculates the portfolio balance.

    Args:
        api_key (str): The API key for CoinMarketCap.
        portfolio_file (str, optional): The path to the portfolio file.
                                        Defaults to DEFAULT_PORTFOLIO_FILE.

    Returns:
        dict: A dictionary containing the portfolio summary.
    """
    if not os.path.exists(portfolio_file):
        return {"assets": [], "total_value": 0, "total_cost": 0.0, "total_roi": 0}
    
    with open(portfolio_file, 'r') as f:
        portfolio = json.load(f)
    
    symbols = list(portfolio.keys())
    current_prices = get_cmc_prices(symbols, api_key)
    
    if not current_prices:
        # Fallback to 1.0 for USDT if API fails
        current_prices = {s: 1.0 if s == "USDT" else 0.0 for s in symbols}

    summary = []
    total_value = 0.0
    total_cost = 0.0
    
    for symbol, data in portfolio.items():
        curr_price = current_prices.get(symbol, data["avg_price"])
        curr_value = data["qty"] * curr_price
        roi = ((curr_price - data["avg_price"]) / data["avg_price"] * 100) if data["avg_price"] > 0 else 0
        
        summary.append({
            "Asset": symbol,
            "Qty": round(data["qty"], 3),
            "Avg Price": round(data["avg_price"], 3),
            "Current Price": round(curr_price, 3),
            "ROI %": round(roi, 2),
            "Value": round(curr_value, 2)
        })
        total_value += curr_value
        total_cost += data["total_spend"]

    total_roi = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0
    
    return {
        "assets": summary,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_roi": round(total_roi, 2)
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cryptocurrency Portfolio Summary")
    parser.add_argument("--api_key", required=True, help="CoinMarketCap API key")
    parser.add_argument("--portfolio_file", default=DEFAULT_PORTFOLIO_FILE, help="The path to the portfolio file")
    args = parser.parse_args()

    print(json.dumps(get_balance(args.api_key, args.portfolio_file)))
