# sentinel

A command-line tool that gives a trading agent (or you) ready-made crypto market facts: prices, trend, news, levels, a trade journal and a journal of predictions that code grades later.

It never trades and never holds exchange keys. It reads public market data, does the arithmetic, and prints the result.

```bash
sentinel snapshot SOL --format telegram
```

```text
SOL $89.56 (-1.2% 24h, -6.3% 7d), RSI 41.2
BTC $75,765 neutral: +0.4% 24h, below SMA50, above SMA200; F&G 25
7d range: wicks $86.90 (05 Nov) to $97.40 (02 Nov); closes $88.10 to $95.75
4h setup: trigger close above $91.20; stop $87.50 (-2.3%, 1.1 ATR)
funding +0.0041%/8h, OI +3.2% 7d, L/S 2.1; FOMC 09 Dec (in 30 d)
```

(Example numbers.)

## How it thinks

- **Code computes, the model judges.** Fetching, indicators and levels are done in code, so every number is exact and repeatable. A language model only reads the result.
- **BTC first.** Every coin view starts with BTC's regime (`risk_on`, `neutral`, `risk_off`), then the market, then the coin. An altcoin rarely beats a falling BTC.
- **Two outputs for every command.** Compact JSON by default (for an agent to reason on), or `--format telegram`: 5 short lines or fewer, ready to send to a person.
- **A failed source is named, not fatal.** If one data source is down or has no key, the command still answers and lists that source under `missing`.
- **Free data.** Candles from OKX and Kraken (no key), news from RSS feeds (no key), CoinMarketCap and NewsAPI on their free plans.
- **Secrets stay out.** API keys are read from AWS SSM Parameter Store at run time. They are never arguments, never in files, and are removed from every log line.
- **Predictions are graded by code.** A logged call is checked against real candles at its horizon. The model that made a call never grades it.

## Install

Python 3.12 or newer. From the repository root:

```bash
python -m pip install -c constraints.txt -e ".[ec2]"
```

```bash
sentinel --version
```

The `ec2` extra holds everything the CLI needs. Add `dev` (`".[ec2,dev]"`) for the tests.

## What it needs

Nothing is required for a first look: the commands in "Try it" below run with no account and no key.

| You want | You need |
| --- | --- |
| Candles, a coin snapshot, news alerts | Nothing (public APIs) |
| Market-wide commands (`market overview`, `top`, `scalp`, `scan`, `brief`, `whales`) and the market block of a snapshot | A CoinMarketCap key (free Basic plan) in SSM as `/sentinel/cmc_api_key` |
| Most-read news (`news long`, `news world`) | A NewsAPI key (free plan, about a day late) as `/sentinel/newsapi_key` |
| The trade journal (`trade`, `portfolio`) | AWS credentials and the DynamoDB table `sentinel-real` |
| Watches and predictions (`watch`, `predict`) | AWS credentials and the DynamoDB table `sentinel-sim` |
| Naive Bayes (`nb`) | AWS credentials and an S3 bucket |
| The model comparison (`experiment run`) | The above, plus a key for each model provider in [`experiment.yaml`](../experiment.yaml): `/sentinel/gemini_api_key`, `/sentinel/anthropic_api_key`, `/sentinel/deepseek_api_key` (the GPT arm runs through a logged-in `openclaw` binary instead of a key) |

Keys are SSM `SecureString` parameters; the [main README](../README.md) shows how to store them, and [`terraform/`](../terraform) creates the tables, the bucket and the instance role. AWS credentials come from the usual places (an instance role, or `aws-vault exec <profile> -- sentinel ...` on a laptop).

`sentinel health` checks the lot (DynamoDB, S3, CoinMarketCap, Gemini) and exits 1 if something is not ready.

### Optional settings

Set these environment variables to override a default. `sentinel config show` prints what is in effect.

| Variable | Default | What it is |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | Region of the tables, bucket and keys |
| `SENTINEL_REAL_TABLE` | `sentinel-real` | Trades, positions, starting cash |
| `SENTINEL_SIM_TABLE` | `sentinel-sim` | Watches, predictions, experiment snapshots |
| `OPENCLAW_S3_BUCKET` | `openclaw-files` | Naive Bayes datasets and models |
| `SENTINEL_LOG_LEVEL` | `WARNING` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (logs go to stderr) |
| `SENTINEL_CACHE_DIR` | `~/.cache/sentinel` | Candle cache (5 minutes) and small state files |

## Try it

These need no key:

```bash
sentinel market candles BTC --tf 1d --limit 30 --format telegram
```

```bash
sentinel snapshot ETH
```

```bash
sentinel news alert --format telegram
```

Every group and command explains itself:

```bash
sentinel -h
```

```bash
sentinel watch add -h
```

## Commands

Symbols are tickers (`SOL`, not `Solana`). Every command takes `--format json|telegram` (default `json`).

### Market

| Command | What it gives |
| --- | --- |
| `snapshot SYMBOL` | One coin in reading order: BTC regime, market, next FOMC, news, flow (funding, open interest, long/short), technicals, 7-day and 30-day levels, strength against BTC. The main command. |
| `market scan [--limit 50] [--symbol DOT,ADA]` | One row of signals per top coin; `--symbol` adds coins outside the top N |
| `market brief [--limit 30]` | The facts for a daily note: BTC, top movers, headlines, stock indexes, BTC's levels |
| `market overview [--symbol BTC,SOL]` | Fear & Greed, BTC dominance, market cap, quotes |
| `market candles SYMBOL [--tf 1w\|1d\|4h\|1h\|15m] [--limit 104]` | UTC candles with the range's high and low (default: 104 weeks) |
| `market top [--limit 15]`, `market scalp [--limit 50]`, `market whales SYMBOL` | Older rule-based views |

### News

| Command | What it gives |
| --- | --- |
| `news long SYMBOL [--limit 3]` | The coin's most read headlines of 14 days |
| `news world [--limit 5]` | Most read world news of 3 days that moves markets |
| `news alert` | Major headlines from the crypto feeds, each one once; prints `NO_REPLY` when there are none |

### Watches

A watch is a price level you want to hear about. It sets no money aside.

| Command | What it does |
| --- | --- |
| `watch add SYMBOL --trigger touch_below\|close_below\|close_above --level PRICE [--tf 1d\|4h] [--target PRICE] [--stop PRICE] [--note TEXT]` | Adds a watch. `--trigger` and `--level` are required; `--tf` is the candle for close triggers (default `1d`) |
| `watch list`, `watch remove ID` | Shows or stops active watches |
| `watch check` | Checks every watch once and prints one line per hit, or `NO_REPLY`. Meant for a scheduler (every 15 minutes) |

### Trade journal

Your real trades, typed in after you made them. Amounts are exact decimals.

| Command | What it does |
| --- | --- |
| `trade add --side buy\|sell --symbol SOL --qty N --price P [--fee F] [--venue TEXT] [--note TEXT]` | Journals a trade and updates the position. `--side`, `--symbol`, `--qty`, `--price` are required |
| `portfolio summary` | Cash, open positions, what is deployed and realised |
| `portfolio baseline --usdt N [--replace]` | Sets the starting cash the balance is counted from |

### Predictions

A prediction is a test call: nothing is bought. Code grades it later.

| Command | What it does |
| --- | --- |
| `predict log --symbol XRP --model NAME --json '{...}'` | Checks a call and stores it with the market it was made in. All three options are required |
| `predict show ID` | One logged call in full |
| `predict score` | Grades every call that is due. Meant for a scheduler (hourly) |
| `predict export [--days 14]` | The calls of the last days with results and hit rates |

The JSON of a call:

```json
{"btc_context": "BTC neutral, below SMA50", "action": "BUY", "direction": "UP",
 "confidence": 0.6, "horizon_h": 24, "entry": 1.183, "target": 1.21, "stop": 1.15,
 "reasons": ["funding neutral", "RSI 54"], "risk_note": "FOMC in 3 days"}
```

`action` is `BUY`, `SELL` or `HOLD`; `horizon_h` is 1, 4, 12, 24, 72 or 168. A BUY needs `target > entry > stop`, a SELL the reverse, a HOLD neither. A call that breaks these, or whose `entry` is more than 1 % from the live price, is still stored but marked invalid. A HOLD means "do not buy now" and is right when the price is not more than 1 % above the entry at the horizon.

### Model comparison and Naive Bayes

| Command | What it does |
| --- | --- |
| `experiment run [--slot 00\|08\|16]` | One run of [`experiment.yaml`](../experiment.yaml): a snapshot per coin, one call per model arm on that same snapshot. A re-run of a slot only retries the calls that failed |
| `nb build-dataset [--days 1095]` | Daily features and next-day returns of the experiment's coins, stored in S3 |
| `nb train [--dataset KEY]` | Trains the model and prints a walk-forward report |
| `nb check SYMBOL` | The model's chance that the coin closes higher the next day, with the features behind it. A weak second opinion, never a signal by itself |

### Housekeeping

| Command | What it does |
| --- | --- |
| `health [--wait SECONDS]` | Checks keys, DynamoDB, S3 and the APIs; `--wait` keeps retrying short failures |
| `config show` | The settings in effect, no secrets |

## Output and errors

- **stdout** holds the result only: one line of JSON, or the Telegram text.
- **stderr** holds logs, one JSON object per line.
- **A failure** prints `{"error": "..."}` and exits 1. The message holds a status or error code, never a key.
- **A missing source** does not fail the command: look for `missing` in the JSON.
- **`NO_REPLY`** means "nothing to report", so a scheduler can stay silent.

## Layout

| Folder | What is in it |
| --- | --- |
| `cli.py` | The commands: options in, one view out |
| `views.py` | Each command's result in both output forms |
| `data/` | One client per source (CoinMarketCap, exchanges, news, Fear & Greed, stock indexes) |
| `signals/` | Indicators, the snapshot and the market scan |
| `alerts/` | Watches and news alerts |
| `portfolio/`, `store/` | The trade journal and the DynamoDB tables |
| `predict/` | Logging, validating and grading calls; the experiment runner |
| `llm/` | Model clients and prompts for the experiment |
| `nb/` | Naive Bayes: dataset, training, check |

The build order and the reasons behind it are in [`docs/IMPLEMENTATION_PLAN.md`](../docs/IMPLEMENTATION_PLAN.md).
