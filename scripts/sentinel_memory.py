import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('CryptoSentinel_State')

def log_trade(symbol, price, total_spend):
    # Calculate quantity: Q = Total / Price
    qty = Decimal(str(total_spend)) / Decimal(str(price))
    
    table.put_item(Item={
        'PK': f'ASSET#{symbol.upper()}',
        'SK': f'TRADE#{Decimal(str(price))}',
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
        avg_rate = data['total_spend'] / data['total_qty']
        summary.append({
            "symbol": sym,
            "total_qty": round(data['total_qty'], 4),
            "avg_rate": round(avg_rate, 4),
            "total_spend": round(data['total_spend'], 2)
        })
    return summary
