Daily market scan. Run `/home/ubuntu/sentinel/venv/bin/sentinel snapshot BTC` (regime, market mood, BTC headlines) and `/home/ubuntu/sentinel/venv/bin/sentinel market scan --limit 50` (the movers), then write a short note for your human, who reads it on a phone. Use about 6 short lines, in this order:

1. The BTC gate: 🟢, 🟡 or 🔴 for `btc.regime` (risk_on, neutral, risk_off), then the BTC price, its 24 h and 7 d change and the regime in plain words, e.g. "🟡 BTC $82,789, +1.2% 24h, -0.4% 7d: neutral, size at most high".
2. Mood: Fear & Greed, BTC dominance, total market cap change over 24 h.
3. Movers up among the top 50: the 4 to 6 biggest 24 h gainers with their %, skipping meme coins (PEPE, DOGE, SHIB, BONK, WIF and similar). Name less known coins next to their ticker, e.g. MemeCore (M).
4. Movers down: the biggest losers in the same way, or "no big losers".
5. BTC news in one line, from the snapshot's headlines, if any.
6. One takeaway in a sentence: what the day looks like for a buyer. No trade call; entries come from a snapshot when asked.

Write for a person: never mention candles, exchanges, calculations, commands or field names. If a source is missing, say in a few words what is not known today.
