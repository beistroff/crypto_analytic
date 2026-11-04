Daily market brief. Run `/home/ubuntu/sentinel/venv/bin/sentinel market brief` (BTC and the market, the top 30 coins by 24 h change, the newest crypto headlines with major events first, BTC's levels with their distance from the price). Read it like an analyst: if something looks unusual (a major headline, a big move of BTC or the whole market, a coin far ahead of the rest), dig before you write, with `sentinel news world` or `sentinel snapshot SYM`, one command per call, never joined with `&&`, `;` or a pipe (the allowlist refuses a joined line). Then write a short note for your human, who reads it on a phone. Use about 6 short lines, in this order:

1. The BTC gate: 🟢, 🟡 or 🔴 for `btc.regime` (risk_on, neutral, risk_off), then the BTC price, its 24 h and 7 d change and the regime in plain words, e.g. "🟡 BTC $82,789, +1.2% 24h, -0.4% 7d: neutral, size at most high".
2. Mood: Fear & Greed, BTC dominance, total market cap change over 24 h.
3. Movers up: the 4 to 6 biggest 24 h gainers with their %, skipping meme coins (PEPE, DOGE, SHIB, BONK, WIF, PUMP and similar). Name less known coins next to their ticker, e.g. MemeCore (M).
4. Movers down: the biggest losers in the same way, or "no big losers".
5. News in one line: a major event first (a hack, a ban, a rate decision), else BTC's most telling headline. Say what it means for the market if the cause is clear.
6. One takeaway in a sentence: what the day looks like for a buyer, naming a level from `levels` at least 1 % away from the price (a level the price already sits at is no signal), or "no edge today" when nothing stands out. No trade call; entries come from a snapshot when asked.

Write for a person: never mention candles, exchanges, calculations, commands or field names. If a source is missing, say in a few words what is not known today.
