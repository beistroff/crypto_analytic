"""
Manages a cryptocurrency portfolio stored in a JSON file.

This script can be used to save trades (buy/sell) and update the portfolio.
"""

import argparse
import json
import os

DEFAULT_PORTFOLIO_FILE = os.path.join(os.path.expanduser("~"), ".sentinel", "portfolio.json")

def save_trade(qty, symbol, price, portfolio_file=DEFAULT_PORTFOLIO_FILE):
    """
    Saves a trade to the portfolio.

    Args:
        qty (float): The quantity of the trade (positive for buy, negative for sell).
        symbol (str): The cryptocurrency symbol (e.g., BTC).
        price (float): The price of the trade.
        portfolio_file (str, optional): The path to the portfolio file.
                                        Defaults to DEFAULT_PORTFOLIO_FILE.

    Returns:
        dict: The updated portfolio data for the symbol, or a status message.
    """
    try:
        portfolio_dir = os.path.dirname(portfolio_file)
        if not os.path.exists(portfolio_dir):
            os.makedirs(portfolio_dir)

        if os.path.exists(portfolio_file):
            with open(portfolio_file, 'r') as f:
                try:
                    portfolio = json.load(f)
                except json.JSONDecodeError:
                    portfolio = {}
        else:
            portfolio = {}

    except IOError as e:
        return {"error": f"Failed to read or create portfolio file: {e}"}

    symbol = symbol.upper()
    if symbol not in portfolio:
        portfolio[symbol] = {"qty": 0.0, "total_spend": 0.0, "avg_price": 0.0}

    qty_val = float(qty)
    price_val = float(price)

    # Update quantity
    portfolio[symbol]["qty"] += qty_val

    # Update cost basis
    if qty_val > 0:  # Buy
        portfolio[symbol]["total_spend"] += (qty_val * price_val)
        if portfolio[symbol]["qty"] > 0:
            portfolio[symbol]["avg_price"] = portfolio[symbol]["total_spend"] / portfolio[symbol]["qty"]
        else:
            portfolio[symbol]["avg_price"] = 0
    else:  # Sell
        if portfolio[symbol]["qty"] <= 0.00001:  # Use a small threshold to handle floating point inaccuracies
            # If all assets are sold, reset the portfolio for that symbol
            del portfolio[symbol]
        else:
            # Sells reduce cost basis proportionally
            # This is a simplification and may not be suitable for tax purposes.
            ratio = portfolio[symbol]["qty"] / (portfolio[symbol]["qty"] - qty_val)
            portfolio[symbol]["total_spend"] *= ratio

    try:
        with open(portfolio_file, 'w') as f:
            json.dump(portfolio, f, indent=4)
    except IOError as e:
        return {"error": f"Failed to write to portfolio file: {e}"}

    return portfolio.get(symbol, {"status": "closed"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cryptocurrency Portfolio Manager")
    parser.add_argument("qty", type=float, help="The quantity of the trade (positive for buy, negative for sell)")
    parser.add_argument("symbol", help="The cryptocurrency symbol (e.g., BTC)")
    parser.add_argument("price", type=float, help="The price of the trade")
    parser.add_argument("--portfolio_file", default=DEFAULT_PORTFOLIO_FILE, help=f"The path to the portfolio file (default: {DEFAULT_PORTFOLIO_FILE})")
    args = parser.parse_args()

    result = save_trade(args.qty, args.symbol, args.price, args.portfolio_file)
    print(json.dumps(result, indent=4))
