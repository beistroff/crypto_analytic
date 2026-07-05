import requests
import sys

def get_cmc_data(api_key, symbol):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    parameters = {
        'symbol': symbol,
        'convert': 'USD'
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key,
    }
    
    try:
        response = requests.get(url, headers=headers, params=parameters)
        return response.json()
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    print("Script structure ready.")
