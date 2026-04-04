import boto3
import json
import click
import time
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('CryptoSentinel_State')

def log_trade(symbol, price, total_spend):
    # Calculate quantity: Q = Total / Price
    qty = Decimal(str(total_spend)) / Decimal(str(price))
    timestamp = int(time.time())
    
    table.put_item(Item={
        'PK': f'ASSET#{symbol.upper()}',
        'SK': f'TRADE#{timestamp}#{Decimal(str(price))}',
        'price': Decimal(str(price)),
        'total_spend': Decimal(str(total_spend)),
        'quantity': qty
    })
    return f"Logged {qty:.4f} {symbol} at ${price}"

def get_portfolio_summary():
    # Fetch all items from DynamoDB
    response = table.scan()
    assets = {}
    
    for item in response['Items']:
        if not item['PK'].startswith('ASSET#'): continue
        symbol = item['PK'].replace('ASSET#', '')
        
        if symbol not in assets:
            assets[symbol] = {'total_qty': 0, 'total_spend': 0}
        
        assets[symbol]['total_qty'] += float(item['quantity'])
        assets[symbol]['total_spend'] += float(item['total_spend'])

    summary = []
    for sym, data in assets.items():
        avg_rate = data['total_spend'] / data['total_qty'] if data['total_qty'] > 0 else 0
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
def show():
    """Show portfolio summary"""
    print(json.dumps(get_portfolio_summary(), indent=2))

@cli.command()
@click.option('--symbol', required=True, help='Coin symbol (e.g. SOL)')
@click.option('--price', required=True, type=float, help='Price per coin')
@click.option('--total', required=True, type=float, help='Total amount spent in USD')
def buy(symbol, price, total):
    """Log a new trade"""
    result = log_trade(symbol, price, total)
    print(json.dumps({"status": "success", "message": result}))

if __name__ == "__main__":
    cli()