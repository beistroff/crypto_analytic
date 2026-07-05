"""
Fetches and analyzes cryptocurrency market data.

This script fetches market data from CoinMarketCap and the Fear & Greed Index,
then provides a market snapshot with basic quantitative analysis.
"""

import requests
import boto3
import json
import click

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

def fetch_market_data(symbol=None):
    """
    Fetches market data from CoinMarketCap and Fear & Greed Index.

    Args:
        symbol (str, optional): A specific cryptocurrency symbol to fetch.
                                If None, fetches top 15 cryptocurrencies.
                                Defaults to None.

    Returns:
        dict: A dictionary containing market data.
    """
    # 1. Fetch CMC Data
    cmc_key = get_ssm_parameter('/sentinel/cmc_api_key')
    if not cmc_key:
        return {"error": "Missing CMC API key in SSM parameter store (/sentinel/cmc_api_key)"}

    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': cmc_key}
    
    if symbol:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        parameters = {'symbol': symbol.upper(), 'convert': 'USD'}
    else:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        parameters = {'limit': 15, 'convert': 'USD', 'sort': 'market_cap'}
    
    try:
        cmc_res = requests.get(url, params=parameters, headers=headers).json()
        if 'status' in cmc_res and cmc_res['status'].get('error_code') != 0:
            return {"error": f"CMC API Error: {cmc_res['status'].get('error_message')}"}
    except Exception as e:
        return {"error": f"Failed to fetch data from CMC: {str(e)}"}
    
    # 2. Fetch Fear & Greed Index
    try:
        fng_res = requests.get("https://api.alternative.me/fng/").json()
        fng_value = int(fng_res['data'][0]['value'])
        fng_status = fng_res['data'][0]['value_classification']
    except Exception:
        fng_value = "Unknown"
        fng_status = "Unknown"

    # 3. Process Data
    market_snapshot = []
    
    if symbol:
        data_dict = cmc_res.get('data', {})
        if symbol.upper() in data_dict:
            coin = data_dict[symbol.upper()]
            vol_24h = coin['quote']['USD']['volume_24h']
            m_cap = coin['quote']['USD']['market_cap']
            vol_mc_ratio = vol_24h / m_cap if m_cap and m_cap > 0 else 0
            
            market_snapshot.append({
                "symbol": coin['symbol'],
                "price": round(coin['quote']['USD']['price'], 4),
                "change_24h": round(coin['quote']['USD']['percent_change_24h'], 2),
                "vol_mc_ratio": round(vol_mc_ratio, 4)
            })
        else:
            return {"error": f"Symbol {symbol} not found on CoinMarketCap."}
    else:
        for coin in cmc_res.get('data', []):
            vol_24h = coin['quote']['USD']['volume_24h']
            m_cap = coin['quote']['USD']['market_cap']
            vol_mc_ratio = vol_24h / m_cap if m_cap and m_cap > 0 else 0
            
            # Quantitative Logic
            signal = "HOLD"
            if isinstance(fng_value, int):
                if fng_value < 30 and coin['quote']['USD']['percent_change_24h'] < -5:
                    signal = "DCA BUY"
                elif fng_value > 75:
                    signal = "REDUCE/TP"
                elif vol_mc_ratio > 0.15:
                    signal = "VOLATILITY ALERT"

            market_snapshot.append({
                "symbol": coin['symbol'],
                "price": round(coin['quote']['USD']['price'], 4),
                "change_24h": round(coin['quote']['USD']['percent_change_24h'], 2),
                "vol_mc_ratio": round(vol_mc_ratio, 4),
                "signal": signal
            })

    return {
        "sentiment": f"{fng_status} ({fng_value})",
        "coins": market_snapshot
    }

@click.command()
@click.option('--symbol', help='Specific coin symbol to analyze (e.g., BTC, ETH)')
def cli(symbol):
    """Market Intelligence CLI"""
    print(json.dumps(fetch_market_data(symbol), indent=2))

if __name__ == "__main__":
    cli()
