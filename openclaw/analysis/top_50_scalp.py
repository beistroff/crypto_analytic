"""
Finds potential scalp trading candidates from the top 50 cryptocurrencies.

This script fetches data for the top 50 cryptocurrencies from CoinMarketCap
and identifies potential scalp trading candidates based on a set of rules.
"""

import argparse
import json
import requests
import boto3

def get_ssm_parameter(name):
    """
    Retrieves a parameter from AWS Systems Manager Parameter Store.

    Args:
        name (str): The name of the parameter to retrieve.

    Returns:
        str: The value of the parameter, or None if an error occurs.
    """
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        parameter = ssm.get_parameter(Name=name, WithDecryption=True)
        return parameter['Parameter']['Value']
    except Exception as e:
        print(f"Error getting SSM parameter: {e}")
        return None

def find_scalp_candidates(limit=50):
    """
    Finds potential scalp trading candidates.

    Args:
        limit (int, optional): The number of top cryptocurrencies to analyze.
                               Defaults to 50.
    """
    api_key = get_ssm_parameter('/sentinel/cmc_api_key')
    if not api_key:
        print(json.dumps({"error": "Missing CMC API key in SSM parameter store (/sentinel/cmc_api_key)"}, indent=2))
        return

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    parameters = {
        'start': '1',
        'limit': str(limit),
        'convert': 'USD'
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key,
    }

    try:
        response = requests.get(url, headers=headers, params=parameters)
        response.raise_for_status()
        data = response.json()

        if 'data' not in data:
            print(json.dumps({"error": "Failed to fetch data from CMC"}, indent=2))
            return

        candidates = []
        for coin in data['data']:
            symbol = coin['symbol']
            # Skip stablecoins
            if symbol in ['USDT', 'USDC', 'DAI', 'FDUSD', 'USDe', 'USD1', 'RLUSD', 'USDD']:
                continue

            quote = coin['quote']['USD']
            price = quote['price']
            change_24h = quote['percent_change_24h']
            volume_24h = quote['volume_24h']
            market_cap = quote['market_cap']

            if market_cap > 0:
                vmc_ratio = volume_24h / market_cap
            else:
                vmc_ratio = 0

            # Scalp Logic:
            # 1. High liquidity (V/MC > 0.05) - means it's actively being traded
            # 2. Price hasn't pumped yet (Change between -4% and +2%) - looking for reversal or lagging pump
            if vmc_ratio > 0.05 and -4.0 <= change_24h <= 2.0:
                candidates.append({
                    "Symbol": symbol,
                    "Price": round(price, 4),
                    "Change_24h": round(change_24h, 2),
                    "V/MC": round(vmc_ratio, 3),
                    "Signal": "SCALP WATCH"
                })

        # Sort by V/MC ratio descending to find the most active coins
        candidates = sorted(candidates, key=lambda x: x['V/MC'], reverse=True)

        print(json.dumps({"scalp_candidates": candidates[:5]}, indent=2))

    except requests.exceptions.RequestException as e:
        print(json.dumps({"error": f"Error fetching data: {e}"}, indent=2))
    except (KeyError, IndexError) as e:
        print(json.dumps({"error": f"Error parsing data: {e}"}, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find scalp trading candidates.")
    parser.add_argument("--limit", type=int, default=50, help="Number of top cryptocurrencies to analyze.")
    args = parser.parse_args()
    find_scalp_candidates(args.limit)
