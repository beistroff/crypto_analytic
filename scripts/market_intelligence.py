import requests
import boto3
import json

def get_ssm_parameter(name):
    ssm = boto3.client('ssm', region_name='us-east-1')
    parameter = ssm.get_parameter(Name=name, WithDecryption=True)
    return parameter['Parameter']['Value']

def fetch_market_data():
    # 1. Fetch CMC Top 15
    cmc_key = get_ssm_parameter('/sentinel/cmc_api_key')
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    parameters = {'limit': 15, 'convert': 'USD', 'sort': 'market_cap'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': cmc_key}
    
    cmc_res = requests.get(url, params=parameters, headers=headers).json()
    
    # 2. Fetch Fear & Greed Index
    fng_res = requests.get("https://api.alternative.me/fng/").json()
    fng_value = fng_res['data'][0]['value']
    fng_status = fng_res['data'][0]['value_classification']

    # 3. Process Data for Gemini
    market_snapshot = []
    for coin in cmc_res['data']:
        vol_24h = coin['quote']['USD']['volume_24h']
        m_cap = coin['quote']['USD']['market_cap']
        vol_mc_ratio = vol_24h / m_cap if m_cap > 0 else 0
        
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

if __name__ == "__main__":
    print(json.dumps(fetch_market_data()))
