import requests
import boto3
import json
import click

def get_ssm_parameter(name):
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        parameter = ssm.get_parameter(Name=name, WithDecryption=True)
        return parameter['Parameter']['Value']
    except Exception as e:
        return None

def fetch_market_data(symbol=None):
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
        fng_value = fng_res['data'][0]['value']
        fng_status = fng_res['data'][0]['value_classification']
    except Exception:
        fng_value = "Unknown"
        fng_status = "Unknown"

    # 3. Process Data for Gemini
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
            
            market_snapshot.append({
                "symbol": coin['symbol'],
                "price": round(coin['quote']['USD']['price'], 4),
                "change_24h": round(coin['quote']['USD']['percent_change_24h'], 2),
                "vol_mc_ratio": round(vol_mc_ratio, 4)
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
