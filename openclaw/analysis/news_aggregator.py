"""
Fetches and analyzes cryptocurrency news from the News API.

This script can be used to get the latest news for a specific cryptocurrency,
perform a simple sentiment analysis, and generate a trading signal.
"""

import argparse
import json
import requests
import boto3
from datetime import datetime, timedelta

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

def get_crypto_news(api_key, query="crypto", limit=5):
    """
    Fetches cryptocurrency news from the News API.

    Args:
        api_key (str): The API key for the News API.
        query (str, optional): The search query. Defaults to "crypto".
        limit (int, optional): The maximum number of articles to return. Defaults to 5.

    Returns:
        list: A list of news articles, or a list containing an error message.
    """
    # Restrict news to the last 24 hours to avoid stale/cached narratives
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&from={yesterday}&pageSize={limit}&apiKey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        articles = response.json().get('articles', [])
        news = []
        for art in articles:
            news.append({
                "title": art['title'],
                "source": art['source']['name'],
                "url": art['url']
            })
        return news
    except requests.exceptions.RequestException as e:
        return [{"error": f"Error fetching news: {e}"}]
    except json.JSONDecodeError:
        return [{"error": "Failed to decode JSON response from News API."}]


def analyze(symbol):
    """
    Analyzes the news for a specific cryptocurrency.

    Args:
        symbol (str): The cryptocurrency symbol (e.g., BTC).
    """
    news_api_key = get_ssm_parameter('/sentinel/news_api_key')
    if not news_api_key:
        analysis = {
            "symbol": symbol.upper(),
            "market_sentiment": "Unknown",
            "recent_news": [{"error": "Missing News API key in SSM parameter store (/sentinel/news_api_key)"}],
            "signal": "HOLD",
            "rationale": "News API key not configured."
        }
        print(json.dumps(analysis, indent=2))
        return

    news = get_crypto_news(news_api_key, query=symbol)
    
    # Simple sentiment logic based on keywords
    headlines = " ".join([n['title'].lower() for n in news if 'title' in n])
    sentiment = "Neutral"
    if any(word in headlines for word in ["bullish", "approval", "surge", "etf", "win"]):
        sentiment = "Bullish"
    elif any(word in headlines for word in ["bearish", "sec", "lawsuit", "crash", "hack"]):
        sentiment = "Bearish"

    analysis = {
        "symbol": symbol.upper(),
        "market_sentiment": sentiment,
        "recent_news": news[:3],  # Show top 3
        "signal": "ACCUMULATE" if sentiment == "Bullish" else "HOLD",
        "rationale": f"News-driven sentiment is {sentiment}."
    }

    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cryptocurrency News Analyzer")
    parser.add_argument("--symbol", required=True, help="Cryptocurrency symbol (e.g., BTC)")
    args = parser.parse_args()
    analyze(args.symbol)
