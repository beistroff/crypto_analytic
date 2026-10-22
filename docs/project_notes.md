# Project notes

Short notes per merged PR, newest last: what changed, why, and one number. Details are in each PR.

## #8 OpenClaw bring-up (16 Oct)
- Onboarding steps, a slimmed agent workspace and a 2 GB swapfile on the instance.
- Why: the gateway alone takes about 1 GB, and it was OOM-killed on 2 GB of RAM.
- Number: `AGENTS.md` and `TOOLS.md` shrank, 121 lines added and 224 removed in the PR.

## #9 Market signals, snapshot and scan (17 Oct)
- Code now computes RSI, SMAs, ATR, returns, ranges, the BTC regime and futures data; the agent reads them.
- Why: a top-50 scan took about 33 `web_fetch` calls, and levels were read off 10 daily candles by eye.
- Number: `sentinel market scan` covers 50 coins in 5.3 s, about 3,200 characters.

## #10 Fresh news from RSS feeds (19 Oct)
- Four free crypto news feeds, read in parallel with a 5 s timeout, feed the snapshot and the scan.
- Why: NewsAPI's free plan is a day late, and the snapshot had no market headlines.
- Number: headlines from the last 24 h, instead of a day-old feed.

## #11 Plan: agent reasoning tasks and roadmap order (19 Oct)
- Docs only: new tasks 1.9, 2.9, 2.10 and 2.11, and the roadmap as an ordered list of one-PR steps.
- Why: the 19 Oct chat showed long repeated replies, sizing done in the agent's head and portfolio state kept in `.md` files.
- Number: 4 new tasks (1.9, 2.9, 2.10, 2.11).

## #12 Compact replies, one BTC gate (19 Oct)
- Workspace text only: one verdict line per coin, one BTC gate (`btc.regime`), no per-coin budgets, contradictions removed.
- Why: replies ran 15 to 20 lines and restated the gate and unchanged coins every time.
- Number: an example two-coin answer in 7 lines; 132 tests pass.

## #13 Plan: watches instead of bids and caps (19 Oct)
- Docs only: bids and per-coin caps removed, watches planned as logged predictions, line counts relaxed.
- Why: the 2.9 test run contradicted plan text that the trade journal builds on.
- Number: 18 lines added and 18 removed, no code.

## #14 Trade journal in DynamoDB (20 Oct)
- `sentinel trade add`, `portfolio summary` and `portfolio baseline`, with a trade and its position written in one transaction.
- Why: cash and open positions must come from stored data, not from the agent's memory files.
- Number: 137 tests pass, 5 more than in #12; TC-50 to TC-57 passed against `sentinel-sim`.

## #15 Watches checked by an automation (20 Oct)
- `sentinel watch add|list|remove|check`; an OpenClaw command automation runs the check every 15 minutes with no model call.
- Why: a quiet check costs no tokens, and a hit sends one Telegram alert.
- Number: 15-minute checks, 0 model calls.

## #16 Candles for any span, trading approach, scan prompt (22 Oct)
- `sentinel market candles` (weekly by default, 15m for scalps), the trading approach in `AGENTS.md`, the daily scan prompt in the repo, `docs/RELEASING.md`.
- Why: asked about a coin's past year, the agent saw 10 months, because OKX lists it only since Nov 2025.
- Number: the same coin now covers 2 years of weekly candles from Kraken (104 candles).
