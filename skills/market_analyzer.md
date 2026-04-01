# Skill: Market Analyzer
# Action: gather_info

## Step 1: Cooldown Check
- Command: `aws dynamodb get-item --table CryptoSentinel_State --key '{"PK": {"S": "USER_1"}}'`
- Logic: If `now - LastGatherTimestamp < 10800` (3 hours):
    - Reply: "⚠️ Cooldown Active. Wait {{hours_remaining}} hours."
    - Stop execution.

## Step 2: Intelligence Gathering
- Fetch: Top 15 Coins via CoinMarketCap API.
- Search: "Latest crypto news impacting [CoinNames] in the last 12 hours" using Google Search.
- Analyze: Fear & Greed Index, Buy/Sell Volumes.

## Step 3: Reasoning (Gemini)
- Compare current prices with `ActiveTrades` in DynamoDB.
- Logic:
    - IF `Price > EntryPrice + 1%` -> Recommend "TAKE PROFIT".
    - IF `Price < EntryPrice - 5%` -> Analyze Support Levels (Recovery Mode).
    - IF `Balance > 0` -> Identify 1-5% breakout opportunities.

## Step 4: UI Update
- Send Telegram Message with current balance and analysis summary.
- Display Buttons: [BUY 10% SOL], [SELL ALL BTC], [GATHER INFO].

## Step 5: Update State
- Reset `LastGatherTimestamp` to `now` in DynamoDB.
