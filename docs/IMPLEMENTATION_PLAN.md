# Crypto Sentinel: Implementation Plan

Version 1, 10 October 2026.

## How to use this file

- Commit it to the repo as `docs/IMPLEMENTATION_PLAN.md`.
- Start every Claude Code session with: *"Read `docs/IMPLEMENTATION_PLAN.md`. Work on task X.Y only. Follow section 3 (Conventions). Stop when its acceptance criteria pass, tick its checkbox, and add a note to `docs/project_notes.md`."*
- Work top to bottom. Phases 1 to 4 are P0 (needed to pass), 5 to 7 are P1, 8 is P2 (optional), 9 is the experiment.
- After each task, append 3 to 5 lines to `docs/project_notes.md`: what changed, why, and any before/after number (lines of code, latency, tokens, bugs fixed). These notes feed the final write-up.

---

## 0. Context and decisions (read first)

**What this is.** An OpenClaw agent on AWS EC2 that acts as a senior crypto analyst for one user over Telegram. It reads market data and news, keeps a trade journal, and suggests trades; the user executes them manually. The project extends it into a measured, low-cost prediction system.

**Research question.** Which cheap model, Gemini Flash or Claude Sonnet (plus Haiku as a cheap control), makes better short-term crypto predictions from the same data, and how much does a fixed "BTC first" signal hierarchy help?

| Topic | Decision |
| --- | --- |
| Gateway | OpenClaw stays. Pin the version, gateway on localhost, no ClawHub skills. Hermes Agent is out of scope (possible later comparison). |
| Agent | By default one agent, one model, with the existing SOUL / IDENTITY persona ("the best crypto analyst"). Default model: Gemini Flash (free tier). |
| Claude models | Sonnet 5.5 (`claude-sonnet-5-5`) and Haiku 5.5 (`claude-haiku-5-5`) through an **Anthropic API key** with a prepaid limit ($5 to $10), **created later, before Phase 3.5**. A Claude Pro subscription does not include API usage, and subscription use inside third-party agents like OpenClaw changed three times in 2026 and is still unclear, so do not depend on it. |
| Data store | DynamoDB is the source of truth: `sentinel-real` (real trades) and `sentinel-sim` (predictions, snapshots, outcomes). The existing daily S3 backups stay as a fallback. |
| Lambda | Only for jobs that need no LLM: market scans and alerts, prediction scoring, Naive Bayes retraining. Cost is effectively $0. All LLM calls run on EC2. |
| Alerts | Lambda puts alerts on SQS; a small poller on EC2 posts them to OpenClaw's local webhook; OpenClaw writes a short warning to Telegram. No inbound ports. |
| Naive Bayes | A sanity gate and an optional skill, never the source of truth. A deterministic validator runs before it and catches absurd answers more cheaply. |
| Telegram | Replies of 5 lines or fewer; full reasoning only on request. A `/` command menu plus inline buttons for the common actions. |
| Real money | No automated trading. Simulated trades only for the experiment. Real trades are journaled but are not experiment results. |
| Cost ceiling | Public IPv4 about $3.60 a month, plus at most about $10 of Anthropic API usage in total. AWS Budgets alarm at $5. |
| Platform | `us-east-1`, ARM (EC2 t4g.small, Lambda arm64). Python 3.10 or newer (Ubuntu 22.04 ships 3.10; Lambda uses python3.12). Code must run on 3.10. |

### 0.1 Infrastructure state and bring-up order (read before Phase 1)

**The infrastructure is currently destroyed** (summer 2026): there is no running EC2 instance, no OpenClaw onboarding, and no live Telegram bot. Only the repo, the S3 backups and the SSM keys exist. Phase 1 is therefore split in two stages, and nothing that needs a running instance is done in Stage A.

| Stage | Tasks | Needs live infra? |
| --- | --- | --- |
| **A. Polish offline** | 1.0 (Google account, Gemini key in SSM, test from the laptop), 1.1, 1.2, 1.3 (Terraform fixes plus security hardening, `terraform validate` and `plan` only), 1.4 (DynamoDB Terraform), 1.5 (data layer, tested with `moto`), the CLI part of 1.7 | No. Only `terraform plan`, local tests and the laptop's AWS CLI. |
| **Gate** | `terraform fmt -check`, `validate` and `plan` clean in every env; `pytest` and `ruff` pass; bootstrap reviewed. | |
| **B. First bring-up (together)** | `terraform apply`, connect via SSM Session Manager, run `bootstrap.sh`, `openclaw onboard` (latest OpenClaw, then pin that exact version in `bootstrap.sh` and `TOOLS.md`), Telegram bot and DM allowlist, Gemini key check from the instance (F.5 and F.6), 1.6 migration from the S3 backup, 1.7 skill switch and Telegram checks | Yes |
| **C. Phases 2 onward** | As written | Yes |

Notes:
- "Use the latest OpenClaw" and "pin the version" do not conflict: install the newest release at first bring-up, record its exact version, and pin to it from then on. Check its current docs and release notes for config keys at that point, because they change often.
- Security hardening for Stage A (task 1.3): no inbound security-group rules (access only via SSM Session Manager), IMDSv2 required, encrypted EBS, least-privilege IAM, gateway on localhost, no ClawHub skills, no secrets in user data, Terraform state in a private encrypted bucket.
- Before the first `terraform apply`, check which resources survived the destroy (the S3 backup bucket, SSM parameters, any old DynamoDB table, remote state) so Terraform neither recreates nor fails on them.

---

## 1. Current state and known bugs

Fix or retire each of these during Phase 1. File paths are relative to the repo root.

| # | Where | Problem |
| --- | --- | --- |
| B1 | `terraform/env/dynamodb/main.tf` | Table has only `hash_key = "PK"`, but `openclaw/utils/sentinel_memory.py` writes `PK` + `SK`. Each new trade for a coin overwrites the previous one. |
| B2 | `openclaw/utils/sentinel_memory.py` | `get_portfolio_summary` uses `table.scan()`; sells are not modelled; no realised P&L. |
| B3 | `openclaw/portfolio/portfolio_manager.py` vs `portfolio_summary.py` | Two JSON paths (`~/.sentinel/portfolio.json` and `~/sentinel/portfolio.json`); `TOOLS.md` names a third store (`portfolio_info`). |
| B4 | `terraform/env/ec2/locals.tf` | Reads `openclaw/market_intelligence.py` and `openclaw/sentinel_memory.py`, which moved to `openclaw/analysis/` and `openclaw/utils/`. `terraform apply` fails. |
| B5 | `terraform/env/ec2/variables.tf` | Default `instance_type = "t2.micro"` (x86) and `architecture = "x86_64"`, while the AMI filter in `main.tf` is arm64. |
| B6 | README vs code | README says SSM `/crypto/api/...`; code reads `/sentinel/cmc_api_key`. Several scripts take the API key as a CLI argument (visible in `ps` and shell history). |
| B7 | All scripts | `get_ssm_parameter` copied into 3 files; no HTTP timeouts or retries; no `requirements.txt` / `pyproject.toml`; no tests; no logging. |
| B8 | `openclaw/analysis/news_aggregator.py` | NewsAPI.org free plan delivers articles 24 h late and is for development use only, so "news from yesterday" is mostly stale. README names a different service (NewsAPI.ai). |
| B9 | `openclaw/analysis/whale_monitor.py` | Hard-wired to SUI; only checks 1 h price change; unused `API_URL`. |
| B10 | Signals | Fixed thresholds (Fear & Greed below 30 and 24 h change below -5% gives DCA BUY); nothing recorded, so accuracy is unknown. No OHLCV, so no RSI or moving averages. |
| B11 | `openclaw/workspace/skills/market_analyzer.md` | Single file with hard-coded `/home/ubuntu/sentinel/...` paths; skill folder format not used. |
| B12 | `openclaw/bootstrap.sh` | Installs the latest OpenClaw unpinned via `curl | bash`; writes scripts as heredocs from Terraform templates. |

---

## 2. Target repository layout

```text
crypto_analytic/
  pyproject.toml                # package "sentinel", extras: [ec2], [lambda], [analysis], [dev]
  Makefile                      # test, lint, build-lambda, fmt
  sentinel/
    __init__.py
    config.py                   # settings: region, table names, watchlist, thresholds, model ids, prices
    secrets.py                  # SSM SecureString reader with in-process cache
    http.py                     # requests session: timeout, retries with backoff, User-Agent
    log.py                      # JSON-lines logging
    cli.py                      # `sentinel ...` entry point (click)
    data/
      cmc.py  coingecko.py  feargreed.py  exchange.py  flow.py  whales.py
      news_rss.py  gdelt.py  newsapi.py
    signals/
      indicators.py             # RSI, SMA, ATR, returns, volume z-score
      btc_regime.py
      snapshot.py               # builds the hierarchy snapshot
      schema.py                 # pydantic models: Snapshot, PredictionOut, ...
    llm/
      base.py  gemini.py  anthropic_.py  openrouter.py  pricing.py
      prompts/  system.md  freeform.md  structured.md  gate_recheck.md
    predict/
      runner.py                 # chat path + scheduled path
      validator.py              # deterministic sanity checks
      gate.py                   # Naive Bayes gate
    models/
      features.py  naive_bayes.py  dataset.py  train.py
    store/
      dynamo.py                 # repositories for both tables
      migrate.py                # S3 / JSON / CSV import
    portfolio/
      service.py                # buy, sell, average price, realised P&L
    eval/
      scoring.py  report.py  export.py  stats.py
    alerts/
      scan.py                   # rules used by the scan Lambda
      poller.py                 # EC2: SQS -> OpenClaw webhook
  lambdas/
    scan_handler.py  score_handler.py  nb_train_handler.py
  openclaw/
    bootstrap.sh
    workspace/
      SOUL.md  IDENTITY.md  AGENTS.md  TOOLS.md  HEARTBEAT.md  USER.md
      skills/
        trade-journal/SKILL.md
        analyse/SKILL.md
        test-trade-scenario/SKILL.md
        prediction-report/SKILL.md
        nb-check/SKILL.md              # optional
        cluster-prediction/SKILL.md    # optional
        system-ops/SKILL.md            # health check, backups
  ops/
    sys_report.sh  s3_backup.sh  s3_share_sync.sh
    systemd/ sentinel-poller.service  sentinel-poller.timer
  experiment.yaml               # frozen arms, coins, models, thresholds
  analysis/                     # experiment statistics and figures
  terraform/env/{iam,dynamodb,ec2,sqs,lambda,budgets}
  tests/  fixtures/  conftest.py
  legacy/                       # old scripts, deleted at the end of Phase 1
  docs/ IMPLEMENTATION_PLAN.md  project_notes.md
```

---

## 3. Conventions

- **Packaging:** `pyproject.toml`, editable install `pip install -e ".[ec2,dev]"` in `/home/ubuntu/sentinel/venv`. Keep Lambda dependencies light (`requests`, `pydantic`; `boto3` is in the runtime). `ccxt`, `feedparser` and LLM SDKs are EC2-only extras. `pandas`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib` only in `[analysis]`.
- **Libraries:** `boto3`, `requests`, `pydantic>=2`, `click` (already used), `python-ulid`, `ccxt`, `feedparser`, `google-genai`, `anthropic`, `openai` (for OpenRouter's OpenAI-compatible API), `pytest`, `moto`, `ruff`.
- **HTTP:** every call goes through `sentinel.http` with `timeout=10`, 3 retries with exponential backoff on 429/5xx, and a per-source minimum interval.
- **Secrets:** only from SSM SecureString under `/sentinel/*` (Appendix B). Never as CLI arguments, never printed, never logged.
- **Time and ids:** UTC everywhere, ISO 8601 with `Z`. Trade and prediction ids are ULIDs (sortable).
- **Numbers:** `Decimal` for anything stored in DynamoDB; floats only in analysis.
- **CLI output:** `--format json` (compact, for the agent) or `--format telegram` (5 lines or fewer, for the user). JSON output must stay small, because it lands in the agent's context.
- **Tests:** `pytest` with `moto` for DynamoDB and recorded JSON fixtures for every external API. No network in unit tests. One opt-in `@pytest.mark.live` smoke test per data source.
- **Skills:** every CLI command an OpenClaw skill uses is documented in that skill's `SKILL.md`, with the exact command line and an example output.
- **Logging:** JSON lines to stdout (CloudWatch for Lambda; journald on EC2).

---

## Phase 1: Foundation, polish and DynamoDB (W1 to W2, 12 to 25 Oct) [P0]

### 1.0 Accounts and API keys (manual, done by you, about 30 minutes)
- [ ] Follow Appendix F.1 to F.2 and F.4 to F.5: dedicated Google account, Gemini key from AI Studio, stored in SSM.
- [ ] **Deferred:** the Anthropic key (F.3) is created later, not now. Do it before the Phase 3.5 pilot day (when the Haiku and Sonnet arms first run live), and ideally run a few Haiku test calls well before the 30 Nov freeze. Until then, develop `sentinel/llm/anthropic_.py` against mocks and recorded fixtures. Spend limit: $5 (see F.3).

**Accept (Stage A, no EC2 needed):** the Gemini test call in Appendix F returns text when run from your laptop (read the key from SSM with the AWS CLI, as in F.5); `aws ssm get-parameters-by-path --path /sentinel --with-decryption --query "Parameters[].Name"` lists the Gemini key. The Anthropic key and its test call are checked later, before Phase 3.5.

### 1.1 Repo hygiene and package skeleton
- [ ] Create `pyproject.toml`, the `sentinel/` skeleton (section 2), `ruff` and `pytest` config, `Makefile`, `.gitignore`.
- [ ] Implement `config.py`, `secrets.py`, `http.py`, `log.py`.
- [ ] Move the current scripts to `legacy/` unchanged so the running agent keeps working until replacements land.

**Accept:** `pip install -e ".[ec2,dev]"` works; `sentinel --help` lists command groups; `pytest` and `ruff check` pass.

### 1.2 Port existing scripts into the package (behaviour-preserving)
Read each legacy script first and keep its behaviour, then improve.

| Legacy script | New command |
| --- | --- |
| `analysis/market_intelligence.py` | `sentinel market overview [--symbol X]`. Keep the old fixed rules as `rules_signal()` in `sentinel/eval/` as a baseline for the experiment. |
| `analysis/top_15_analysis.py`, `top_50_scalp.py` | `sentinel market top --limit 15` and `sentinel market scalp --limit 50` |
| `analysis/news_aggregator.py` | `sentinel news long SYM` (NewsAPI, documented as 24 h delayed, for long-range research) |
| `analysis/whale_monitor.py` | `sentinel market whales SYM` (any symbol; real logic in 2.5) |
| `monitoring/threshold_monitor.py`, `track_coin.py` | `sentinel watch ...` (read them first, then decide the exact subcommands) |
| `utils/quick_ping.py`, `cmc_check.py` | `sentinel health` |
| `system_monitoring/*.sh` | `ops/` (fix paths; keep the daily S3 backup exactly as before) |

- [ ] Unify SSM names (Appendix B); remove every API key CLI argument.
- [ ] Fix the README (SSM paths, NewsAPI.org vs NewsAPI.ai).

**Accept:** every legacy command has a new equivalent with compact JSON output; parser tests with fixtures for CMC listings and quotes, Fear & Greed and NewsAPI.

### 1.3 Terraform fixes
- [ ] `ec2/variables.tf`: `instance_type = "t4g.small"`, `architecture = "arm64"`; keep the Ubuntu 22.04 arm64 AMI filter (optionally pin the AMI id).
- [ ] Replace the heredoc injection in `locals.tf` and `bootstrap.sh`: bootstrap clones the repo at a pinned tag or commit, creates the venv and runs `pip install -e ".[ec2]"`.
- [ ] Pin the OpenClaw version in `bootstrap.sh` (check the installer docs for how to pin; record the version in `TOOLS.md`).
- [ ] IAM: allow both tables and their indexes (`table/NAME` and `table/NAME/index/*`), SSM `/sentinel/*`, the backup bucket, and later SQS receive/delete. Remove anything unused.
- [ ] Optional: `terraform_remote_state` instead of passing the instance profile name as a string.

**Accept (Stage A):** `terraform fmt -check`, `validate` and `plan` are clean in every env. **Accept (Stage B, first bring-up):** a fresh instance boots to a working venv and OpenClaw is onboarded (document the manual `openclaw onboard` steps in `openclaw/README.md`).

### 1.4 DynamoDB tables in Terraform
- [ ] Two tables, on-demand billing, `PK` (S) + `SK` (S), `GSI1` (`GSI1PK`, `GSI1SK`) on both, `GSI2` (`GSI2PK`, `GSI2SK`) on `sentinel-sim`, TTL attribute `ttl` on `sentinel-sim`, `deletion_protection_enabled = true` on `sentinel-real`. Point-in-time recovery is optional (tiny cost at this size).
- [ ] Item layouts exactly as in Appendix A.

**Accept:** tables exist; the EC2 role can put and query; `tests/conftest.py` creates identical tables in `moto` from one shared spec.

### 1.5 Data access layer (`sentinel/store/dynamo.py`, `sentinel/portfolio/service.py`)
- [ ] Repositories: `TradeRepo`, `PositionRepo`, `LessonRepo`, `BidRepo`, `PredictionRepo`, `SnapshotRepo`, `VoteRepo`, `ReportRepo`.
- [ ] Buy and sell write the trade and update the position in one `TransactWriteItems`, with a condition on `version` (optimistic locking).
- [ ] Average cost method: a buy updates `avg_price`; a sell keeps `avg_price` and adds `(sell_price - avg_price) * qty - fee` to `realised_pnl`; position closes when `qty` is below 1e-9.
- [ ] Every read uses `Query` (by `PK` or `GSI1`), never `Scan`.

**Accept:** tests for buy, second buy, partial sell, full sell, realised P&L, fee handling, and a failed transaction on a version conflict.

### 1.6 Migration from S3 and JSON (Stage B: needs the tables applied)
- [ ] `sentinel migrate fetch --bucket openclaw-files --prefix <backup prefix>` downloads the latest backup to a local folder.
- [ ] `sentinel migrate draft` turns `portfolio.json`, `lessons_learned.md` (Active Bids, Active Trades, Success Cases, Mistakes) and `memory/*.md` into `migration/trades.csv`, `bids.csv`, `lessons.csv` for manual review. Use regex for obvious lines and leave anything unclear for the user to fill in.
- [ ] `sentinel migrate import --dry-run` then `import` writes the reviewed CSVs to `sentinel-real`.

**Accept:** the dry run prints counts; resulting positions match `portfolio.json` within 1e-6.

### 1.7 Switch the trade journal to DynamoDB
- [ ] Commands: `sentinel trade add --side buy|sell --symbol SOL --qty 1.35 --price 72.6 [--fee 0.1]`, `sentinel portfolio summary --format telegram|json`, `sentinel lesson add|list`, `sentinel bid add|list|remove`, `sentinel backup export` (DynamoDB to JSON in S3, nightly, next to the existing file backups).
- [ ] New skill folder `openclaw/workspace/skills/trade-journal/SKILL.md`; update `TOOLS.md`; stop all JSON portfolio writes.

**Accept (Stage B, after first bring-up; the CLI and tests are done in Stage A):** in Telegram, "I bought 100 XRP at 1.20" creates a trade and updates the position; "show my balance" returns a short table; the nightly S3 backup still runs.

---

## Phase 2: Market data and signal hierarchy (W3 to W4, 26 Oct to 8 Nov) [P0]

### 2.1 Exchange candles (`sentinel/data/exchange.py`)
- [ ] Use `ccxt` with OKX as default and Kraken as fallback; symbol map from CMC ticker to exchange pair (e.g. `XRP` to `XRP/USDT`).
- [ ] `fetch_ohlcv(symbol, timeframe="1h"|"1d", limit)` with a 5-minute file cache.
- [ ] **First**, run a live check from the EC2 instance in `us-east-1`. Binance blocks many cloud IP ranges with HTTP 451, so do not use Binance as a data source.

**Accept:** hourly and daily candles for BTC and 10 coins in under 10 s; switching the exchange is a config change.

### 2.2 Indicators (`sentinel/signals/indicators.py`)
- [ ] RSI(14), SMA(50) and SMA(200) on daily candles, ATR(14), returns over 1 h, 24 h and 7 d, volume z-score over 30 days.

**Accept:** unit tests against hand-checked values on a fixture series.

### 2.3 BTC regime (`sentinel/signals/btc_regime.py`)
- [ ] Inputs: BTC 24 h and 7 d change, price versus SMA50 and SMA200, BTC dominance (CoinGecko global).
- [ ] Output: `regime` (`risk_on`, `neutral`, `risk_off`) plus the numbers. Document the rule in the docstring.

### 2.4 News (`sentinel/data/news_rss.py`, `gdelt.py`)
- [ ] RSS feed list in config; parse with `feedparser`; dedupe by link; filter by coin aliases (`XRP`, `Ripple`); last 24 h; at most 5 headlines per section.
- [ ] GDELT market-wide tone (P1, can come later).
- [ ] Sentiment is judged by the LLM, not by code.

### 2.5 Flow and whales (`sentinel/data/flow.py`, `whales.py`) [P1, schema now]
- [ ] Funding rate, open interest, taker buy vs sell volume, long/short ratio from OKX public endpoints (verify the endpoints in OKX API docs; check access from `us-east-1`).
- [ ] Whale proxy: share of volume from trades of $100k or more among recent trades.

### 2.6 Snapshot builder (`sentinel/signals/snapshot.py`)
- [ ] `sentinel snapshot SYM [--save] [--format json]` returns the pydantic `Snapshot` in hierarchy order (Appendix C): BTC, market news and mood, coin news, flow, whales, coin technicals, portfolio context.
- [ ] Missing sources become `null` and are listed in `missing`.
- [ ] Keep the JSON under about 1,500 tokens; add a size test.
- [ ] `--save` stores it as a `SNAP` item in `sentinel-sim` with a 180-day TTL.

**Accept:** snapshots for 10 coins in under 20 s; tests for missing sources and the size budget.

---

## Phase 3: Prediction journal and models (W4 to W5, 2 to 15 Nov) [P0]

### 3.1 LLM clients (`sentinel/llm/`)
- [ ] One interface `call(system, user, schema) -> (parsed, usage)` for Gemini (`google-genai`), Anthropic (`anthropic`, models `claude-sonnet-5-5` and `claude-haiku-5-5`) and OpenRouter (OpenAI-compatible).
- [ ] JSON output mode, retries on 429 with backoff, and logged tokens in and out, latency and cost (prices in `config.py`: Sonnet 5.5 $2 / $10 per million tokens in / out, Haiku 5.5 $0.10 / $0.50, Gemini free tier $0).
- [ ] Record the exact model id string returned by each API.

### 3.2 Prompts and output schema
- [ ] `PredictionOut` (Appendix D). `btc_context` comes first and is required.
- [ ] Templates: `system.md` (core of SOUL and IDENTITY plus analyst rules), `freeform.md` (today's style, for arm F0), `structured.md` (hierarchy, for all other arms), `gate_recheck.md`.
- [ ] `prompt_hash` = sha256 of the rendered template without the data.

### 3.3 Deterministic validator (`sentinel/predict/validator.py`)
Runs on every answer before anything else:
- [ ] `btc_context` not empty, and its direction agrees with the snapshot's BTC 24 h sign.
- [ ] `entry` within 1% of the snapshot price.
- [ ] BUY: `target > entry > stop`; SELL: `target < entry < stop`; HOLD: no target or stop needed.
- [ ] `horizon_h` in {1, 6, 24, 48}; `confidence` between 0 and 1; reward-to-risk of 1 or more (warning only).
- [ ] On failure: one retry with the error list; if it fails again, store with `valid = false` (counted in the results).

### 3.4 Chat path: `test-trade-scenario` skill
- [ ] `sentinel predict log --json '<PredictionOut>' --symbol XRP --source chat` validates, stores a `PRED` item and returns the id plus a 5-line message.
- [ ] `sentinel predict show <id>` returns the full reasoning ("details").
- [ ] Skill folder `skills/test-trade-scenario/SKILL.md`: build the snapshot, decide, log, reply in the short format.

### 3.5 Scheduled path: experiment runner
- [ ] `sentinel experiment run --slot 09|21` reads `experiment.yaml`, builds one snapshot per coin, runs every arm, stores one `PRED` per arm.
- [ ] Idempotency key: date + slot + symbol + arm (re-runs skip existing items).
- [ ] System cron on EC2 at 09:00 and 21:00 UTC. This runs outside OpenClaw on purpose, so every arm gets an identical prompt and exact token logging.

### 3.6 Scoring job (Lambda, hourly, no LLM)
- [ ] `score_handler` queries `GSI2` for `OPEN` items with `due_at <= now`, fetches hourly candles since the prediction (plain `requests` to the exchange REST API, no `ccxt` in Lambda), and fills each horizon in `checks`: price, return, hit.
- [ ] Records `target_hit_first` (target touched before stop, or the reverse, or neither) and `max_adverse_pct`.
- [ ] Sets the next `due_at`; after the 48 h check, sets `status = DONE` and removes the `GSI2` attributes.

### 3.7 Reports
- [ ] `sentinel report daily|weekly --format telegram`: hit rate per arm and horizon with n and Wilson interval, best and worst call, cost so far, invalid answers.
- [ ] OpenClaw cron jobs (isolated sessions) send them. Skill folder `skills/prediction-report/SKILL.md`.

**Accept (end of Phase 3):** one pilot day yields 20 snapshots times the number of arms; the scorer fills the 1 h and 6 h checks; the daily report fits in 15 lines.

---

## Phase 4: Telegram UX and short replies (W4, 2 to 8 Nov) [P0]

### 4.1 Reply format
- [ ] Rule in `AGENTS.md` and every skill: 5 lines or fewer, fixed template, full reasoning saved in DynamoDB and sent only on "details <id>". Cap output tokens at about 250 for chat replies.

```text
XRP: BUY, confidence 0.64, 24 h
BTC: +1.2% today, above 50-day average
Why: funding neutral, positive coin news
Sim trade a3f logged, target $1.21, stop $1.12
Reply "details a3f" for the full analysis
```

### 4.2 Command menu
- [ ] Register `/analyse`, `/predict`, `/balance`, `/report`, `/menu`, and optionally `/nb` and `/cluster` in Telegram's `/` menu. Check the "Native and custom commands" part of OpenClaw's Telegram messaging docs (`docs.openclaw.ai/channels/telegram/messaging`) for the exact config key.

### 4.3 Inline buttons
- [ ] Set `channels.telegram.capabilities.inlineButtons: "dm"`.
- [ ] The agent sends buttons with the `message` tool (`presentation.blocks`, type `buttons`, callback buttons). A tap reaches the agent as text `callback_data: <value>` (`docs.openclaw.ai/channels/telegram/rich-messages`).
- [ ] Value grammar: `act:analyse:XRP`, `act:predict:XRP:24`, `act:details:<id>`, `act:nb:XRP`, `act:cluster:XRP`. Document the mapping in each `SKILL.md`.
- [ ] `/menu` replies with one button per watchlist coin; every analysis reply carries [Details] [Sim trade 24 h] [NB check].

### 4.4 Lock the bot down
- [ ] Only your Telegram user id may talk to the bot (DM allowlist in the Telegram channel config).

**Accept:** tapping "XRP" in `/menu` gives a 5-line analysis with buttons; "Details" returns the full text.

---

## Phase 5: Naive Bayes model and gate (W5 to W6, 9 to 22 Nov) [P1]

### 5.1 Historical dataset
- [ ] `sentinel nb build-dataset --days 730`: daily candles for the watchlist and BTC from the exchange, full Fear & Greed history (alternative.me supports `?limit=0`), BTC dominance if CoinGecko's demo history allows (otherwise drop the feature). Save Parquet to S3 `datasets/`.

### 5.2 Features and label (`sentinel/models/features.py`)
- [ ] Label: 1 if the next 24 h return is above +0.5%, else 0.
- [ ] Bucketed features: BTC 24 h direction (down below -1%, flat, up above +1%), BTC above or below SMA50, coin RSI band (below 30, 30 to 70, above 70), coin above or below SMA50, Fear & Greed band (0-24, 25-44, 45-55, 56-75, 76-100), weekend flag, volume z-score band.
- [ ] Only features that exist in history (no news), so training and live use match.

### 5.3 Training (`sentinel/models/naive_bayes.py`, `train.py`)
- [ ] Categorical Naive Bayes in plain Python/numpy with Laplace smoothing (about 80 lines; easy to explain and audit). A test checks parity with scikit-learn's `CategoricalNB`.
- [ ] Walk-forward validation: train on 12 months, test on the next month, roll forward. Report accuracy, Brier score and log-loss against the base rate and a logistic regression.
- [ ] Export `models/nb/<version>.json` (priors, likelihood tables, bucket edges, `trained_until`) to S3 and keep a `latest.json` pointer.

### 5.4 Inference and gate (`sentinel/predict/gate.py`)
- [ ] `sentinel nb check SYM` returns `p_up` and the top 3 features by likelihood ratio, in under 1 s, on EC2 (no Lambda call per prediction).
- [ ] Gate rule (thresholds in config, frozen before the experiment): if the model says BUY with confidence 0.6 or more and `p_up <= 0.35`, or SELL with confidence 0.6 or more and `p_up >= 0.65`, send `gate_recheck.md` with the NB result. The model may keep or revise its answer and must say why.
- [ ] Log `nb_p_up`, `gate_triggered`, `original_action`, `revised`.
- [ ] The gate never overrides the model by itself.
- [ ] Optional skill `skills/nb-check/SKILL.md` for "how confident should I be?".

### 5.5 RQ3 analysis (`analysis/rq3_btc_leads.py`)
- [ ] P(altcoin down over 24 h | BTC down more than 2%) against the base rate, chi-square test of independence, likelihood-ratio table per feature.

### 5.6 Weekly retrain Lambda (optional)
- [ ] `nb_train_handler`, weekly via EventBridge Scheduler. Disabled during the December experiment so the model version stays fixed.

**Accept:** the walk-forward report exists; gate unit tests cover both trigger directions and the no-trigger case.

---

## Phase 6: Lambda alerts through SQS to OpenClaw (W6, 16 to 22 Nov) [P1]

### 6.1 Terraform
- [ ] SQS queue plus dead-letter queue; Lambda functions `scan`, `score`, `nb_train` (arm64, python3.12); EventBridge Scheduler schedules; least-privilege IAM; log retention 14 days; AWS Budgets alarm at $5.

### 6.2 Packaging
- [ ] `make build-lambda`: `pip install --platform manylinux2014_aarch64 --only-binary=:all: --target build/ ".[lambda]"`, then zip. Keep the zip small (no `ccxt`, no pandas).

### 6.3 Scan rules (`sentinel/alerts/scan.py`, every 2 h)
- [ ] BTC move above 2% in 1 h or 5% in 24 h; watchlist coin above 4% in 1 h; funding rate above 0.05% per 8 h; Fear & Greed crossing 25 or 75; price within 1% of an active bid (`BID` items in `sentinel-real`).
- [ ] Cooldown of 6 h per rule and symbol, stored as `ALERT` items with TTL.
- [ ] Send `{type, symbol, rule, value, ts}` to SQS. No LLM.

### 6.4 EC2 poller (`sentinel/alerts/poller.py`, systemd timer every 5 min)
- [ ] Receive up to 10 messages; if none, exit (no LLM call).
- [ ] Batch them into one text and POST to `http://127.0.0.1:<gateway port>/hooks/agent` with `Authorization: Bearer <hook token>` and a message asking for a warning of 3 lines or fewer, delivered to Telegram. Check the payload fields in OpenClaw's hooks reference (`gateway/config-hooks`).
- [ ] Delete the SQS messages only after an HTTP 200.

### 6.5 OpenClaw hooks config
- [ ] Hooks enabled with their own token (not the gateway token), `allowedAgentIds` restricted, isolated session per hook (the default).

**Accept:** a test message on the queue reaches Telegram within 6 minutes; logs show zero LLM calls during quiet periods.

---

## Phase 7: Session hygiene and cost logging (W6) [P1]

- [ ] **7.1 Baseline first:** record input tokens per chat turn over about 30 normal messages (OpenClaw logs or `/status`).
- [ ] **7.2** Move scheduled work from the heartbeat and main session to OpenClaw cron jobs (fresh session per run). Keep `HEARTBEAT.md` minimal.
- [ ] **7.3** Enable `agents.defaults.contextPruning.mode: "cache-ttl"`; keep compaction on (default); make sure every CLI returns compact JSON.
- [ ] **7.4** Measure again and add a before/after table to `docs/project_notes.md`.

---

## Phase 8: Optional extensions (W7, 23 to 29 Nov) [P2]

### 8.1 `cluster-prediction`
- [ ] `sentinel cluster run SYM`: Gemini Flash (technical role), one free OpenRouter model (sentiment role; model id in config), Claude Sonnet or Haiku (risk role), called in parallel.
- [ ] Round 1: JSON votes (action, confidence, one-line reason). If they disagree, round 2: each sees the other two reasons and may change once. Majority vote, then validator and rule check.
- [ ] Store `VOTE` items and one `PRED` with `model = "cluster"`.
- [ ] Orchestrated in Python, so keep OpenClaw's Swarm sub-agents switched off.

### 8.2 Weekly reflection
- [ ] Sunday cron: `sentinel reflect weekly` summarises the worst errors; the LLM proposes up to 3 lessons stored as `LESSON` with `status = proposed`; Telegram buttons Approve / Reject; approved lessons go into the structured prompt. Disabled during the experiment.

### 8.3 Polish
- [ ] Final whale proxy; GitHub Actions running `ruff`, `pytest`, `terraform fmt -check` and `validate`.

---

## Phase 9: Experiment freeze, run and analysis (30 Nov to 28 Dec)

### 9.1 Freeze (30 Nov)
- [ ] `experiment.yaml` committed with arms, coin list, exact model ids, validator and gate thresholds, NB model version, prompt hashes. Git tag `experiment-v1`.
- [ ] Reflection and NB retraining switched off.

| Arm | Model | Prompt | Gate |
| --- | --- | --- | --- |
| F0 | Gemini Flash | freeform | off |
| F1 | Gemini Flash | structured | off |
| F1G | Gemini Flash | structured (reuses F1's answer) | on; an extra call only when triggered |
| H1 | Claude Haiku 5.5 | structured | off |
| S1 | Claude Sonnet 5.5 | structured | off |
| NB | Naive Bayes only | none | n/a |
| RULES | Legacy fixed rules | none | n/a |

Daily volume: 20 snapshots, so about 40 Flash calls plus gate re-checks, 20 Haiku and 20 Sonnet. Expected cost for 28 days: Sonnet about $6 (about $3 through the Batch API), Haiku about $0.30, Flash free.

### 9.2 Run
- [ ] Daily report check; watch for missing data and free-tier 429 errors; never change the frozen config mid-run (log incidents in `project_notes.md` instead).

### 9.3 Analysis (`analysis/`)
- [ ] `sentinel eval export --out data/experiment.parquet`.
- [ ] Scripts producing tables and figures for the write-up:
  - Wilson intervals (`statsmodels proportion_confint(method="wilson")`) and exact binomial test against 50% (`scipy.stats.binomtest`).
  - McNemar (`statsmodels mcnemar`): F1 vs S1, F1 vs H1, F1 vs F1G, F0 vs F1.
  - Cochran's Q (`statsmodels cochrans_q`) across F0, F1, F1G, then McNemar with Holm correction.
  - Brier score with Murphy decomposition and a reliability diagram.
  - Wilcoxon signed-rank (`scipy.stats.wilcoxon`) on paired simulated returns.
  - Block bootstrap by day for return differences.
  - Chi-square (`scipy.stats.chi2_contingency`) for RQ3.
  - Fleiss' kappa (`statsmodels fleiss_kappa`) for cluster agreement, if built.
  - Cost table: tokens, USD, latency per arm.

---

## Appendix A: DynamoDB items

All items carry `type` and `created_at`. Keys are strings.

**`sentinel-real`**

| Type | PK | SK | GSI1PK / GSI1SK | Attributes |
| --- | --- | --- | --- | --- |
| TRADE | `TRADE#{SYM}` | `{ts}#{trade_id}` | `SYM#{SYM}` / `{ts}` | symbol, side (BUY/SELL), qty, price, quote_amount, fee, fee_asset, venue, note, source (telegram/import) |
| POSITION | `POS#{SYM}` | `CURRENT` | `SYM#{SYM}` / `POS` | qty, avg_price, cost_basis, realised_pnl, version, updated_at |
| LESSON | `LESSON` | `{date}#{slug}` | none | text, tags, status (approved/proposed), source (manual/reflection) |
| BID | `BID#{SYM}` | `{bid_id}` | `SYM#{SYM}` / `BID#{bid_id}` | qty, price, status (active/filled/cancelled) |
| META | `META` | `BASELINE` | none | baseline_usdt, since |

**`sentinel-sim`**

| Type | PK | SK | Indexes | Attributes |
| --- | --- | --- | --- | --- |
| SNAP | `SNAP#{SYM}` | `{ts}` | none | schema_version, payload (JSON string), missing, ttl (180 days) |
| PRED | `PRED#{date}` | `{ts}#{SYM}#{arm}` | GSI1: `SYM#{SYM}` / `{ts}`; GSI2 (sparse): `OPEN` / `{due_at}` | pred_id, symbol, arm, model, model_version, variant, source (chat/scheduled), action, direction, confidence, horizon_h, entry, target, stop, btc_context, btc_regime, reasons, rationale_full, prompt_hash, snapshot_ref, tokens_in, tokens_out, cost_usd, latency_ms, valid, validator_errors, nb_p_up, gate_triggered, original_action, revised, status (OPEN/DONE), due_at, checks (map: `h1`, `h6`, `h24`, `h48` each with price, return_pct, hit), target_hit_first, max_adverse_pct |
| VOTE | `PRED#{date}` | `{ts}#{SYM}#cluster#VOTE#{model}#{round}` | none | role, action, confidence, reason, tokens, cost_usd |
| ALERT | `ALERT#{rule}#{SYM}` | `{ts}` | none | value, ttl (6 h cooldown) |
| REPORT | `REPORT#{daily|weekly}` | `{date}` | none | text, metrics (map) |

## Appendix B: SSM parameters (SecureString)

`/sentinel/cmc_api_key`, `/sentinel/newsapi_key`, `/sentinel/coingecko_api_key`, `/sentinel/gemini_api_key`, `/sentinel/anthropic_api_key`, `/sentinel/openrouter_api_key`, `/sentinel/openclaw_hook_token`. The Telegram bot token stays in OpenClaw's own config.

## Appendix C: Snapshot example (compact, hierarchy order)

```json
{
  "schema_version": 1, "ts": "2026-11-03T09:00:00Z", "symbol": "XRP", "price": 1.183,
  "btc": {"price": 81250, "chg_24h": 1.2, "chg_7d": -3.4, "above_sma50": true, "above_sma200": true, "dominance": 58.1, "regime": "neutral"},
  "market": {"fear_greed": 41, "headlines": ["...", "..."]},
  "coin_news": ["...", "..."],
  "flow": {"funding_8h": 0.006, "oi_chg_24h": 3.1, "taker_buy_sell": 1.08, "long_short": 1.32},
  "whales": {"large_trade_share": 0.12},
  "technicals": {"rsi14": 54, "above_sma50": true, "above_sma200": false, "atr14_pct": 4.2, "vol_z": 0.8, "chg_1h": 0.3, "chg_24h": 2.1},
  "portfolio": {"has_position": false, "exposure_pct": 0, "weekday": "Tue"},
  "missing": []
}
```

## Appendix D: `PredictionOut` schema

```json
{
  "btc_context": "BTC +1.2% in 24 h, above both averages: neutral, not blocking alts",
  "action": "BUY", "direction": "UP", "confidence": 0.64, "horizon_h": 24,
  "entry": 1.183, "target": 1.21, "stop": 1.12,
  "reasons": ["funding neutral", "positive coin news", "RSI 54, room to run"],
  "risk_note": "weekend in 2 days, keep size small"
}
```

## Appendix E: OpenClaw skills

| Skill folder | Trigger | Commands it runs |
| --- | --- | --- |
| `trade-journal` | "I bought/sold ...", "balance", "/balance" | `sentinel trade add`, `sentinel portfolio summary`, `sentinel bid ...`, `sentinel lesson ...` |
| `analyse` | "analyse X", `/analyse`, `act:analyse:X` | `sentinel snapshot X --format json` |
| `test-trade-scenario` | "test trade X 24h", `/predict`, `act:predict:X:24` | `sentinel snapshot`, `sentinel predict log`, `sentinel predict show` |
| `prediction-report` | `/report`, daily and weekly cron | `sentinel report daily|weekly --format telegram` |
| `nb-check` (optional) | `/nb`, `act:nb:X` | `sentinel nb check X` |
| `cluster-prediction` (optional) | `/cluster`, `act:cluster:X` | `sentinel cluster run X` |
| `system-ops` | health check, backups (as today) | `sentinel health`, `ops/s3_backup.sh`, `sentinel backup export` |

## Appendix F: Manual setup of model API keys

Do these steps yourself, in a browser and a terminal. Never paste a key into a chat, a Telegram message, a commit or a Claude Code prompt.

### F.1 Dedicated Google account
1. Create a new Google account just for this project (for example `sentinel.agent.<something>@gmail.com`). Turn on 2-step verification.
2. Use it only for AI Studio. Do not link it to your main Gmail, Drive or YouTube.
3. Why: in February 2026 Google suspended accounts that used OpenClaw with the Gemini CLI / Antigravity login, sometimes including linked Gmail. A plain AI Studio API key is the allowed route, and a separate account keeps your main account out of it entirely.

### F.2 Create the Gemini API key (free tier)
1. Signed in with the new account, open [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and accept the terms. New users get a default Google Cloud project automatically; rename it to `sentinel` in the **Projects** view.
2. Click **Create API key** and choose that project. New keys are created as auth keys (since 28 May 2026).
3. If the key shows **Unrestricted**: hover over the label, click **Add restrictions**, select **Restrict to Gemini API only**, click **Restrict key**. The Gemini API rejects unrestricted standard keys.
4. Copy the key once, straight into the SSM step below (F.4). Do not save it in a text file.
5. **Do not link a billing account to this project.** The free tier is for projects without billing; once billing is on, requests are charged.
6. Check your real limits at [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit): requests per minute (RPM), tokens per minute (TPM) and requests per day (RPD) for the current Flash model. Write them in `docs/project_notes.md`.
   - Limits are **per project, not per key**, so a second key in the same project gives no extra quota.
   - The daily quota resets at **midnight Pacific time** (10:00 Kyiv time in winter).
7. Note the exact model id of the current Flash model from AI Studio's model picker (or list them in F.5). It goes into `sentinel/config.py`.
8. Free-tier prompts may be used to improve Google products and may be read by human reviewers. Send market data only; never send portfolio values, names or anything personal.

### F.3 Create the Anthropic API key (paid, capped) [DEFERRED: do before Phase 3.5, not in task 1.0]
A Claude Pro subscription does not include API access; this is a separate prepaid account.
1. Open the Claude Console at [platform.claude.com](https://platform.claude.com/) and sign in (your normal account is fine here).
2. **Settings > Billing:** buy the smallest credit amount offered ($5 to $10). Leave automatic reload off. Optionally create a dedicated workspace `sentinel` and put the key in it, with its own spend limit.
3. Still in **Settings > Billing**, under **Spend limits**, click **Set limit** and enter `5`. A $5 cap fits the experiment only if Sonnet runs through the Batch API (about $3) or with fewer coins or slots; check current prices first. Allowed models are enforced in code (`config.py`), not by the key. At the limit the API returns HTTP 400 "You have reached your specified API usage limits" instead of charging more.
4. **API keys:** create a key named `sentinel-ec2`. Copy it once, straight into F.4.
5. Your tier and rate limits are shown at [platform.claude.com/usage/limits](https://platform.claude.com/usage/limits).

### F.4 Store the keys in SSM (from your laptop with AWS CLI)
Do the Gemini block now; do the Anthropic block when F.3 is done.

`read -s` keeps the key out of your shell history and off the screen.

```bash
read -s GEMINI_KEY      # paste the Gemini key, press Enter
aws ssm put-parameter --region us-east-1 --name /sentinel/gemini_api_key \
  --type SecureString --value "$GEMINI_KEY" --overwrite
unset GEMINI_KEY

read -s ANTHROPIC_KEY   # paste the Anthropic key, press Enter
aws ssm put-parameter --region us-east-1 --name /sentinel/anthropic_api_key \
  --type SecureString --value "$ANTHROPIC_KEY" --overwrite
unset ANTHROPIC_KEY
```

The EC2 role already reads `/sentinel/*`, so nothing else is needed on the instance.

### F.5 Test both keys (on the EC2 instance, via SSM Session Manager)
```bash
GEMINI_KEY=$(aws ssm get-parameter --region us-east-1 --name /sentinel/gemini_api_key \
  --with-decryption --query Parameter.Value --output text)

# list available models (look for the current Flash id)
curl -s -H "x-goog-api-key: $GEMINI_KEY" \
  "https://generativelanguage.googleapis.com/v1beta/models" | grep '"name"' | grep -i flash

# one short test call; replace MODEL_ID with the id found above
curl -s -H "x-goog-api-key: $GEMINI_KEY" -H "Content-Type: application/json" \
  "https://generativelanguage.googleapis.com/v1beta/models/MODEL_ID:generateContent" \
  -d '{"contents":[{"parts":[{"text":"Reply with OK"}]}]}'
unset GEMINI_KEY

ANTHROPIC_KEY=$(aws ssm get-parameter --region us-east-1 --name /sentinel/anthropic_api_key \
  --with-decryption --query Parameter.Value --output text)
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-haiku-5-5","max_tokens":10,"messages":[{"role":"user","content":"Reply with OK"}]}'
unset ANTHROPIC_KEY
```
Both should return a short JSON answer containing "OK". A 403 from Google usually means the key is unrestricted or the wrong project; a 400 from Anthropic about credits means billing is not set up yet.

### F.6 Connect OpenClaw to Gemini with the API key
- In `openclaw onboard` (or the model provider settings), choose **Google Gemini with an API key**. Do **not** choose any Google sign-in option such as Gemini CLI or Antigravity OAuth.
- OpenClaw needs the key in its own config or environment (the Gemini SDKs read `GEMINI_API_KEY`). Load it from SSM at service start rather than writing it into a file in the repo; check the OpenClaw model-provider docs for the exact key name in `openclaw.json`.
- Set Gemini Flash as the default model for the agent. Sonnet and Haiku are called by the `sentinel` package directly for the experiment, so OpenClaw only needs the Anthropic key if you also want to chat with Claude.

### F.7 Optional: OpenRouter (only for `cluster-prediction`)
1. Create an account at openrouter.ai, then a key named `sentinel-cluster`; do not buy credits, so only `:free` models can run.
2. Free models allow 20 requests a minute and 50 a day (1,000 a day after $10 of lifetime credit purchases). Store it as `/sentinel/openrouter_api_key` the same way as F.4.

### F.8 If a key leaks
Create a new key, update the SSM parameter (`--overwrite`), restart the services, check that calls work, then delete the old key. In AI Studio this is the **API Keys** page; in the Claude Console the **API keys** page.

## Appendix G: Verify before relying on it

- [ ] OKX (or Kraken) public endpoints for candles, funding, open interest, taker volume and long/short ratio work from `us-east-1`.
- [ ] Exact OpenClaw config key for custom Telegram commands, and the `/hooks/agent` payload fields for delivering to Telegram.
- [ ] How to pin the OpenClaw version in the installer.
- [ ] Your real Gemini Flash free-tier limits in AI Studio (Google no longer publishes fixed numbers for the current Flash models). Free-tier prompts may be used by Google to improve products, so send market data only.
- [ ] CoinGecko Demo history depth for BTC dominance.
- [ ] The t4g.small free trial end date (31 Dec 2026 per current reports) and what the instance will cost afterwards.
