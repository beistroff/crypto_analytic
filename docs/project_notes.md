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

## #25 Experiment runner (25 Oct)
- `sentinel experiment run` (an OpenClaw command automation at 00:05, 08:05 and 16:05 UTC) builds one snapshot per coin of `experiment.yaml`, stores it, and has every arm call its model directly on it: Gemini Flash Lite with and without the BTC-first reading order (L0, L1), Gemini Flash on 4 random coins (F1, its free quota is 20 a day), Haiku 5.5 (H1), and Sonnet 5.5 on F1's same 4 coins (S1, for the price). The answers go through the validator into the prediction journal; the hourly scorer grades them.
- Why: the research question needs every model on identical inputs, with exact tokens and cost; a chat turn through the agent would cost 10 to 20 times more and differ per model.
- Number: 132 calls a day (L0 60, L1 60, F1 12) on the free tier, 60 Haiku calls at about $0.001 each and 12 Sonnet calls at about $0.0075 each (measured 26 Oct: $0.05 a run, about $2.10 for 14 days); 0 NewsAPI requests; 155 tests pass. Ships as v0.1.9.

## #26 News rule and backup output (25 Oct)
- Fix PR (gaps G-19, G-16): `AGENTS.md` sends questions about what moves the market, macro or the week ahead to `news world` together with the snapshot's fresh feed headlines, and says only NewsAPI's are a day late. The documented backup time is 04:00 UTC, after OpenClaw's 03:00 job, and a real backup prints errors only.
- Why: asked what moved markets this week, the agent fetched no world news and missed a major market-moving headline it had shown that day; the backup's run summary stored every copy and progress line.
- Number: one rule line changed; the backup summary goes from one line per file to two lines.

## #27 One command per call (26 Oct)
- Fix PR: `AGENTS.md` and the daily scan prompt say to run one `sentinel` command per call, never joined with `&&`, `;` or a pipe.
- Why: on 26 Oct the daily scan sent both of its commands in one exec call; the allowlist matches one command, so it refused the line and no scan went out.
- Number: two sentences; 1 failed scan in 8 runs.

## #28 HOLD means wait (26 Oct)
- A HOLD is graded as "wait, do not buy now": right when buying would not have paid (the price is not more than 1 % above the entry at the horizon); `predict export` adds BUY, SELL and HOLD hit rates apart. The runner prompt and both skills say so.
- Why: the first experiment runs showed models use HOLD to stay out with low confidence, and the ±1 % band would have graded every careful call in a moving market as a miss.
- Number: one scoring rule and one export line; the stored return lets the analysis apply either rule.
- Same PR, agent rules (`AGENTS.md`) after reviewing a day of chat: state a watch's full entry rule up front and follow it when it hits (an AVAX hit was answered "wait" against its own rule), rank several coins, suggest keeping about 20 % with a break-even stop at the target, and offer to log buy or sell verdicts as test calls so they get measured.

## #29 Money flow (26 Oct)
- The snapshot adds where money moves: the total crypto volume's change against yesterday and its share outside BTC (`market`), and the coin's spot taker buy share over 24 h and OKX's top traders' long/short next to all accounts' (`flow`). The market scan adds `v_mc` and `vol_z30` per coin; `AGENTS.md` says how to read them and to name the numbers behind any flow claim.
- Why: the agent judged price and positioning but could not see money moving into stablecoins, out of BTC or into one coin; the old agent's whale talk was a story without such data.
- Number: two extra OKX calls per snapshot (free, keyless), 0 extra CMC credits; snapshot JSON grows by about 100 characters, the scan by two columns. On 26 Oct SOL's top traders were at 0.88 (net short) against 2.1 for all accounts.

## #31 Trade card (27 Oct)
- `AGENTS.md`: every buy or buy-if comes as a short trade card (when to buy at which candle close, buy price, where and when to sell, what to do if it drops, the chance to reach the target first, why, how long it is valid, and the watch set for it), and a list of coins always ends with one pick. A neutral BTC gate caps the size instead of meaning "wait"; after a run of 5 % or more the agent prefers the dip to the pullback zone; a dropping trade gets a repair plan (hold, one add from cash at support, one break that ends the idea) instead of a bare stop.
- Why: the agent gave conditional signals that read as information: no target, no time frame, no chance, and a stop that meant taking an 11 % loss with no plan.
- Number: one reply format replaces the old trigger line and its example; about 6 lines more in `AGENTS.md`.

## #33 Live result in the portfolio (28 Oct)
- `sentinel portfolio summary` adds each position's live exchange price and open result (USDT and %), plus the total; a price that cannot be read leaves only that position without it. The `trade-journal` skill logs a buy that came from a trade card as a test call too, and points a position 5 % or more below its average to the repair plan.
- Why: the summary showed the average cost but not how a trade was doing, so the repair-plan rule had no number to start from, and the trades actually made were never graded.
- Number: one cached exchange call per open position; 155 tests pass.

## #34 Agent rules without stops (30 Oct)
- `AGENTS.md`: the trading rules lose the stop machinery (setup stop, "stop in noise", stop watches, "the break ends the idea"). A trade card now gives the add level and how likely the good path is against the bad one; a held coin that is down gets a recovery plan (hold, add from cash at support, sell part on a bounce), and taking a loss is the human's call, raised only for an outside reason. News is checked before a buy call and whenever BTC or a held coin falls 3 % or more, a cause is given only when it is in the data, and a major event is reported at once. The skills keep a `stop` only to grade test calls.
- Why: competing rules (a tight 4h setup stop, a daily "break", a repair plan) led the agent to advise selling three small positions at a loss, against the patient spot approach; it also explained a market drop with a cause that was not in its data and missed an exchange hack until told.
- Number: 4 contradicting stop rules removed; `AGENTS.md` from 156 to 152 lines with the same tools.

## #35 Major-news alert (30 Oct)
- `sentinel news alert` (an OpenClaw command automation every 30 minutes, no model call) reads the free crypto news feeds and sends a short Telegram alert for a market-moving headline of the last 2 h: an exchange hack or exploit, frozen or halted withdrawals, an insolvency, a delisting or ban, a rate decision, a depeg. Each link once (kept two days in the cache folder), at most 3 per run; quiet runs and feed outages send nothing.
- Why: a major exchange hack moved the market overnight and the agent only learned of it when told; it acts only when written to and had no news watch.
- Number: 0 model tokens; 4 feed reads per run; 156 tests pass.
