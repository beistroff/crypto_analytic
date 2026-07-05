"""
Manages a cryptocurrency portfolio stored in AWS DynamoDB.

This script provides a CLI to log trades and get a portfolio summary.
"""

import boto3
import json
import click
import time
from decimal import Decimal

def get_dynamodb_table(table_name='CryptoSentinel_State', region_name='us-east-1'):
    """
    Returns a DynamoDB table object.

    Args:
        table_name (str, optional): The name of the DynamoDB table.
                                    Defaults to 'CryptoSentinel_State'.
        region_name (str, optional): The AWS region. Defaults to 'us-east-1'.

    Returns:
        boto3.resource.Table: A DynamoDB table object.
    """
    dynamodb = boto3.resource('dynamodb', region_name=region_name)
    return dynamodb.Table(table_name)

def log_trade(symbol, price, total_spend, table):
    """
    Logs a trade to the DynamoDB table.

    Args:
        symbol (str): The cryptocurrency symbol (e.g., BTC).
        price (float): The price of the trade.
        total_spend (float): The total amount spent in the trade.
        table (boto3.resource.Table): The DynamoDB table object.
    """
    qty = Decimal(str(total_spend)) / Decimal(str(price))
    # Use higher precision timestamp for unique SK
    timestamp = int(time.time() * 1000000)
    
    table.put_item(Item={
        'PK': f'ASSET#{symbol.upper()}',
        'SK': f'TRADE#{timestamp}',
        'price': Decimal(str(price)),
        'total_spend': Decimal(str(total_spend)),
        'quantity': qty
    })
    return f"Logged {float(qty):.4f} {symbol} at ${price}"

def get_portfolio_summary(table):
    """
    Retrieves and summarizes the portfolio from the DynamoDB table.

    Args:
        table (boto3.resource.Table): The DynamoDB table object.

    Returns:
        list: A list of dictionaries, where each dictionary represents an asset.
    """
    items = []
    response = table.scan()
    items.extend(response.get('Items', []))
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))
        
    assets = {}
    for item in items:
        if not item['PK'].startswith('ASSET#'): continue
        symbol = item['PK'].replace('ASSET#', '')
        
        if symbol not in assets:
            assets[symbol] = {'total_qty': 0.0, 'total_spend': 0.0}
        
        assets[symbol]['total_qty'] += float(item.get('quantity', 0))
        assets[symbol]['total_spend'] += float(item.get('total_spend', 0))

    summary = []
    for sym in sorted(assets.keys()):
        data = assets[sym]
        if abs(data['total_qty']) < 1e-10 and abs(data['total_spend']) < 1e-10:
            continue
            
        avg_rate = data['total_spend'] / data['total_qty'] if data['total_qty'] != 0 else 0
        summary.append({
            "symbol": sym,
            "total_qty": round(data['total_qty'], 4),
            "avg_rate": round(avg_rate, 4),
            "total_spend": round(data['total_spend'], 2)
        })
    return summary

@click.group()
def cli():
    """Sentinel Memory CLI"""
    pass

@cli.command()
@click.option('--table_name', default='CryptoSentinel_State', help='DynamoDB table name')
@click.option('--region', default='us-east-1', help='AWS region')
def show(table_name, region):
    """Show portfolio summary"""
    table = get_dynamodb_table(table_name, region)
    print(json.dumps(get_portfolio_summary(table), indent=2))

@cli.command()
@click.option('--symbol', required=True, help='Coin symbol (e.g. SOL)')
@click.option('--price', required=True, type=float, help='Price per coin')
@click.option('--total', required=True, type=float, help='Total amount spent in USD')
@click.option('--table_name', default='CryptoSentinel_State', help='DynamoDB table name')
@click.option('--region', default='us-east-1', help='AWS region')
def buy(symbol, price, total, table_name, region):
    """Log a new trade"""
    table = get_dynamodb_table(table_name, region)
    result = log_trade(symbol, price, total, table)
    print(json.dumps({"status": "success", "message": result}))

if __name__ == "__main__":
    cli()
