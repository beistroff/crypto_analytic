---
name: trade-journal
description: Journal the user's real trades and report cash and positions. Use when the user says they bought or sold a coin, asks for their balance, portfolio or positions, or tells you what they hold.
---

# Trade journal

The trade journal is the DynamoDB table `sentinel-real`; only `sentinel` reads and writes it. Run it by its full path, `/home/ubuntu/sentinel/venv/bin/sentinel`. Never keep portfolio numbers in a workspace file (no `portfolio.json`, no markdown journal): a number that is not from these commands is not known.

## "I bought / sold ..."

Journal a trade only when the user says they made it. A suggestion, a watch or a plan is not a trade.

```bash
sentinel trade add --side buy --symbol XRP --qty 100 --price 1.20 --format telegram
```

- `--side buy|sell`, `--symbol` (a ticker such as SOL), `--qty` (coins), `--price` (USDT per coin) are required. Add `--fee USDT` only if the user gives one, `--venue` and `--note` (a few words) only if they say so.
- If the quantity or the price is missing, ask for it. Never guess it, and do not fill in the market price.
- Reply with the command's line as it is. Example output:

```text
BUY 100 XRP at $1.20. Now 100 at avg $1.20.
```

If the buy came from your trade card, also log the card as a test call (the `test-trade-scenario` skill: entry the buy price, the card's target, its add level as the grading stop, 24 h unless the card says otherwise), so the trades your human makes get graded too.

A sell also prints the profit it realised:

```text
SELL 40 XRP at $1.50. Realised +$12.00. Now 60 at avg $1.20.
```

## "Balance", "/balance", "my portfolio"

```bash
sentinel portfolio summary --format telegram
```

Reply with it as it is. Cash and open positions come first, each position with its live price and open result (left out when the price cannot be read). Example output:

```text
Cash: $880.00
Deployed: $120.00 in 1 position, realised +$0, open +$12.00
XRP 100 at avg $1.20, now $1.32 (+10.0%)
```

A position 5 % or more below its average gets the repair plan from `AGENTS.md` (Portfolio).

If it says no starting cash is set, tell the user and offer to set it (below).

## Starting cash and what the user already holds

Cash is the starting cash, minus what is deployed, plus what has been realised, so the journal needs a starting cash before it can name a balance.

```bash
sentinel portfolio baseline --usdt 1000 --format telegram
```

- It refuses to overwrite a starting cash that is already set. Use `--replace` only after the user confirms the new number.
- When the user describes what they hold today, for example "100 USDT cash and 50 SOL bought at 80": set the starting cash to the total they started with (cash plus the cost of the holdings, here 4,100), then journal each holding as a buy at its cost with `--note "opening position"`. Repeat the sums back and wait for a yes before you write anything.
- A deposit or a withdrawal changes the starting cash: ask, then `--replace` with the new total.

## Errors

If a command prints `{"error": ...}`, tell the user in a few words and stop; do not retry in a loop. A trade is written whole or not at all, so after an error the journal is unchanged. "Changed, run the trade again" means another trade landed meanwhile: run the same command once more.

Examples: `{"error":"cannot sell 500 XRP, holding 100"}`, `{"error":"starting cash is already 1000 USDT since 2026-10-20T10:00:00Z; pass --replace to change it"}`.
