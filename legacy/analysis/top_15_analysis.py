"""
Fetches and analyzes the top 15 cryptocurrencies by market cap.

This script fetches data for the top 15 cryptocurrencies from CoinMarketCap,
retrieves the Fear & Greed Index, and provides a basic analysis and
trading signal for each coin.
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

def analyze_top_15():
    """
    Analyzes the top 15 cryptocurrencies.

    Returns:
        dict: A dictionary containing the analysis results.
    """
    api_key = get_ssm_parameter('/sentinel/cmc_api_key')
    if not api_key:
        return {"error": "Missing CMC API key in SSM parameter store (/sentinel/cmc_api_key)"}

    # 1. Fetch CMC Data
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    parameters = {'limit': 15, 'convert': 'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, params=parameters)
        response.raise_for_status()
        data = response.json()['data']
        
        # 2. Fetch Fear & Greed
        fg_res = requests.get("https://api.alternative.me/fng/")
        fg_res.raise_for_status()
        fg_data = fg_res.json()['data'][0]
        fg_value = int(fg_data['value'])
        fg_status = fg_data['value_classification']

        results = []
        for coin in data:
            symbol = coin['symbol']
            price = coin['quote']['USD']['price']
            chg_24h = coin['quote']['USD']['percent_change_24h']
            mcap = coin['quote']['USD']['market_cap']
            vol_24h = coin['quote']['USD']['volume_24h']
            v_mc_ratio = vol_24h / mcap if mcap > 0 else 0
            
            # Quantitative Logic
            signal = "HOLD"
            if fg_value < 30 and chg_24h < -5:
                signal = "DCA BUY"
            elif fg_value > 75:
                signal = "REDUCE/TP"
            elif v_mc_ratio > 0.15:
                signal = "VOLATILITY ALERT"

            results.append({
                "Symbol": symbol,
                "Price": round(price, 2),
                "Change": round(chg_24h, 2),
                "V/MC": round(v_mc_ratio, 3),
                "Signal": signal
            })
        
        return {"fg": fg_value, "fg_status": fg_status, "coins": results}
    except requests.exceptions.RequestException as e:
        return {"error": f"Error fetching data: {e}"}
    except (KeyError, IndexError) as e:
        return {"error": f"Error parsing data: {e}"}


if __name__ == "__main__":
    print(json.dumps(analyze_top_15(), indent=2))
