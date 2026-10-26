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

## #18 Trade journal, part 2 (23 Oct)
- A `trade-journal` skill journals trades and reads the balance through `sentinel`; the agent no longer reads a markdown journal. The daily S3 backup runs as an OpenClaw command automation, and old backups expire by a lifecycle rule.
- Why: portfolio numbers must come from DynamoDB only; backups belong to the deployment, not to the CLI, and cost nothing as a command automation.
- Number: 0 lines of Python changed; `backups/` kept for 30 days.

## #19 Setup block in the snapshot (23 Oct)
- The snapshot computes a 4h setup: trigger (4h close above the 48 h close high), stop 0.25 ATR under the 48 h wick low with its distance in % and ATR, a `stop_in_noise` flag, the pullback zone and room to the 30-day high; 4h and 1h RSI join the daily one.
- Why: the agent improvised triggers and stops per coin, once a stop inside one day's range; trades last 12 h to 7 days, so daily levels were too wide.
- Number: one more candle request per snapshot, about 150 characters more JSON; 144 tests pass.

## #20 News rework, CMC coin names, no-swap flow (23 Oct)
- NewsAPI coin news is the most read of 14 days (2 in the snapshot); `sentinel news world` gives the most read market-moving world news of 3 days, run by the agent only when needed. Headline names come from CMC's top 100 (cached a day). A coin without an OKX swap is no longer listed as missing flow.
- Why: day-old "newest" headlines were noise, the 22 Oct war scare had no source, and coins outside a hand-kept 20-name list were matched by ticker only.
- Number: 20 hand-kept coin names down to 4 aliases; 1 CMC credit a day; 148 tests pass.

## #21 Scan watchlist (24 Oct)
- `sentinel market scan --symbol DOT,ADA` adds coins outside the top N in the same rows; the output names the left-out stablecoins and wrapped coins in `skipped`.
- Why: DOT was asked about but missing from a top-15 scan, and the agent reported row counts instead of naming what was skipped.
- Number: 1 extra CMC credit only when `--symbol` names a coin outside the top N; 149 tests pass.

## #22 Prediction log (24 Oct)
- `sentinel predict log` checks a chat call (lean validator: entry within 1 % of the price, target and stop on the right sides, horizon, confidence) and stores it in `sentinel-sim` with the chat model and a compact snapshot; `predict show` reads it back. The `test-trade-scenario` skill tells the agent how.
- Why: calls made in chat were lost in the Telegram history, so nobody could say how often the agent is right; the scorer (10b) and the model comparison grade these items.
- Number: 0 CMC or NewsAPI credits per call (exchange candles only); 151 tests pass.

## #23 Prediction scorer, export and review (24 Oct)
- `sentinel predict score` (hourly, silent, no model) checks each logged call at every horizon up to its own: BUY hits above the entry, SELL below, HOLD within ±1 %; then target or stop first and the worst move against. `predict export` lists the calls with hit rates per horizon and per model; the `review-predictions` skill turns an export into at most 5 lessons for `memory/prediction_lessons.md`.
- Why: logged calls need a grade before anyone can say how far to trust the agent, and the same scorer will grade the model comparison.
- Number: 0 model tokens per grade; 153 tests pass. Steps 9 and 10 ship as v0.1.8.

## #24 Plan: runner schedule and coins (25 Oct)
- Docs only: the 3.5 runner runs 3 times a day, follow the sun (00:05, 08:05, 16:05 UTC, just after funding settles), one call per coin per run for one fixed horizon, on a fixed list of 20 coins; 9.1 checks each coin's data and recounts the cost.
- Why: 09:00 and 21:00 were placeholders; funding times and the UTC daily close are real market events, and a fixed list keeps model skill apart from coin selection.
- Number: 60 calls a day per arm; Haiku about $0.40 for the 14-day run.

## #26 News rule and backup output (25 Oct)
- Fix PR (gaps G-19, G-16): `AGENTS.md` sends questions about what moves the market, macro or the week ahead to `news world` together with the snapshot's fresh feed headlines, and says only NewsAPI's are a day late. The documented backup time is 04:00 UTC, after OpenClaw's 03:00 job, and a real backup prints errors only.
- Why: asked what moved markets this week, the agent fetched no world news and missed a major market-moving headline it had shown that day; the backup's run summary stored every copy and progress line.
- Number: one rule line changed; the backup summary goes from one line per file to two lines.
