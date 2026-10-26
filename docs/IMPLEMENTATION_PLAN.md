# Crypto Sentinel: Implementation Plan

Version 2, 16 October 2026: core first, then the research track, the rest later (see 0.2).

## How to use this file

- Commit it to the repo as `docs/IMPLEMENTATION_PLAN.md`.
- Start every Claude Code session with: *"Read `docs/IMPLEMENTATION_PLAN.md`. Work on task X.Y only. Follow section 3 (Conventions). Stop when its acceptance criteria pass, tick its checkbox, and add a note to `docs/project_notes.md`."*
- Follow the order in 0.2 (Roadmap): the core first, then the research track, then Later. One task per session and per PR. Each phase heading says which track it belongs to.
- After each task, append 3 to 5 lines to `docs/project_notes.md`: what changed, why, and any before/after number (lines of code, latency, tokens, bugs fixed). These notes feed the final write-up.

---

## 0. Context and decisions (read first)

**What this is.** An OpenClaw agent on AWS EC2 that acts as a senior crypto analyst for one user over Telegram. It reads market data and news, keeps a trade journal, and suggests trades; the user executes them manually. The project extends it into a measured, low-cost prediction system.

**Research question.** Which cheap model, Gemini Flash, DeepSeek or Claude Sonnet (plus Haiku as a cheap control), makes better short-term crypto predictions from the same data, and how much does a fixed "BTC first" signal hierarchy help?

| Topic | Decision |
| --- | --- |
| Gateway | OpenClaw stays. Pin the version, gateway on localhost, no ClawHub skills. Hermes Agent is out of scope (possible later comparison). |
| Agent | By default one agent with the existing SOUL / IDENTITY persona ("the best crypto analyst"). Chat model: Claude Haiku 5.5, with the free Gemini models (3.8, 3.7, 3.6 Flash, then 3.5 and 3.1 Flash Lite) as fallbacks. Decided at bring-up (2026-10-16): free Gemini Flash allows 5 requests a minute and 20 a day, which one agent turn plus OpenClaw's retries can use up. |
| Priorities (2026-10-16) | Core first: the agent useful day to day (market data, trade journal, lessons, a light prediction journal). Then the research track (the measured experiment, with Naive Bayes). Everything else later. The order is in 0.2; there are no dates. Deep analysis stays on Haiku with more thinking; Sonnet is not used for chat (cost). |
| Data access | `sentinel` commands for structured, compact data; `web_fetch` for public, keyless sources (OKX candles, funding, open interest); later, when a question needs it, the CMC pass-through (2.7) for any other CMC endpoint. The agent never holds an API key: whatever is in its context can end up in replies, memory files and the S3 backup. |
| Claude models | Sonnet 5.5 (`claude-sonnet-5-5`) and Haiku 5.5 (`claude-haiku-5-5`) through an **Anthropic API key** with $5 of prepaid credit, a $5 monthly spend limit and no auto-reload (created 2026-10-16). A Claude Pro subscription does not include API usage, and Anthropic cut subscriptions off from third-party agents like OpenClaw in April 2026, so do not depend on it. |
| Data store | DynamoDB is the source of truth: `sentinel-real` (real trades) and `sentinel-sim` (predictions, snapshots, outcomes). Provisioned capacity (2 RCU/WCU per table and index) stays inside the always-free tier; point-in-time recovery is off. The tables have no backup (decided 23 Oct: no cost, and the trade journal is re-entered by hand if lost); the daily S3 backup of the workspace stays, run by an OpenClaw command automation. Keep S3 under 5 GB with a lifecycle rule on `backups/`. |
| Lambda | Only for jobs that need no LLM: market scans and alerts, prediction scoring, Naive Bayes retraining. Cost is effectively $0. All LLM calls run on EC2. |
| Alerts | Lambda puts alerts on SQS; a small poller on EC2 posts them to OpenClaw's local webhook; OpenClaw writes a short warning to Telegram. No inbound ports. |
| Naive Bayes | A sanity gate and an optional skill, never the source of truth. A deterministic validator runs before it and catches absurd answers more cheaply. |
| Telegram | Compact per coin (a verdict, one reason line, one line with trigger, stop and size), with no total line limit; longer when the user asks for detail, when the agent needs to ask questions, or when the market situation needs explaining. A `/` command menu plus inline buttons for the common actions. |
| Real money | No automated trading. Simulated trades only for the experiment. Real trades are journaled but are not experiment results. |
| Cost ceiling | Public IPv4 about $3.60 a month, DynamoDB $0 (free tier), plus at most $5 a month of Anthropic API usage (the key's spend limit). AWS Budgets alarm at $5. |
| Platform | `us-east-1`, Ubuntu 24.04 LTS (22.04 standard support ends mid-2027). Instance type is a variable (t4g.small today); the architecture and AMI follow from it, so another free-tier type needs no code change. Lambda arm64 python3.12; EC2 runs Python 3.12 as well. |

### 0.1 Infrastructure state and bring-up order (read before Phase 1)

**The infrastructure is currently destroyed** (summer 2026): there is no running EC2 instance, no OpenClaw onboarding, and no live Telegram bot. Only the repo, the S3 backups and the SSM keys exist. Phase 1 is therefore split in two stages, and nothing that needs a running instance is done in Stage A.

| Stage | Tasks | Needs live infra? |
| --- | --- | --- |
| **A. Polish offline** | 1.0 (Google account, Gemini key in SSM, test from the laptop), 1.1, 1.2, 1.3 (Terraform fixes plus security hardening, `terraform validate` and `plan` only), 1.4 (DynamoDB Terraform), 1.5 (data layer, tested with `moto`), the CLI part of 1.7, 1.8 (readiness gate code and tests) | No. Only `terraform plan`, local tests and the laptop's AWS CLI. |
| **Gate** | `terraform fmt -check`, `validate` and `plan` clean in every env; `pytest` and `ruff` pass; bootstrap reviewed. | |
| **B. First bring-up (together)** | `terraform apply` (bootstrap runs and must pass the 1.8 readiness gate: `~/sentinel/.ready` exists), connect via SSM Session Manager, `openclaw onboard` (latest OpenClaw, then pin that exact version as `openclaw_version` in `terraform.tfvars` and record it in `TOOLS.md`; steps in `openclaw/README.md`), Telegram bot and DM allowlist, Gemini key check from the instance (F.5 and F.6), history import from the old backup (full lessons, the April to May memory notes, the May portfolio as a history note; not the old `HEARTBEAT.md`), daily S3 backup (system crontab) and daily market scan (OpenClaw automation), 1.7 skill switch and Telegram checks | Yes |
| **C. Phases 2 onward** | As written | Yes |

Notes:
- "Use the latest OpenClaw" and "pin the version" do not conflict: install the newest release at first bring-up, record its exact version, and pin to it from then on. Check its current docs and release notes for config keys at that point, because they change often.
- Security hardening for Stage A (task 1.3): no inbound security-group rules (access only via SSM Session Manager), IMDSv2 required, encrypted EBS, least-privilege IAM, gateway on localhost, no ClawHub skills, no secrets in user data, Terraform state in a private encrypted bucket.
- Before the first `terraform apply`, check which resources survived the destroy (the S3 backup bucket, SSM parameters, any old DynamoDB table, remote state) so Terraform neither recreates nor fails on them.

### 0.2 Roadmap (2026-10-19): core first, then the research track
The plan is split in three. **Core** makes the agent useful day to day: good market data, a real portfolio in DynamoDB, and short, consistent replies. The **research track** is the measured experiment. **Later** is optional. There are no dates: steps follow this order, at the pace the work allows. Each step is one session and one small PR. A PR that touches DynamoDB or the instance merges only after its manual test cases pass (kept locally, outside git). After each merge: tag a release, update the instance to that tag, then a smoke test (`sentinel health`, one snapshot, one scan, one Telegram question).

| Step | Track | Task (one PR) | Status |
| --- | --- | --- | --- |
| 1 | Core | Bring-up: instance, OpenClaw, Telegram, daily S3 backup, daily market scan | Done |
| 2 | Core | Market data: 2.0 to 2.6, 2.8 scan, 2.4 RSS | Done |
| 3 | Core | 2.9 agent instructions refresh (workspace text only) | Done |
| 4 | Core | Trade journal, part 1: 1.4 item layouts, 1.5 data layer, `trade add`, `portfolio summary` | Done |
| 5 | Core | 1.9 watches and alerts | Done |
| 5a | Core | Polish after step 5: `market candles` (weekly history), the gate emoji, the daily scan prompt in the repo, `docs/RELEASING.md` | Done |
| 6 | Core | Trade journal, part 2: `trade-journal` skill, daily backup as an OpenClaw command automation; 1.3 S3 lifecycle rule (decided 22 and 23 Oct: lessons stay in `memory/lessons_learned.md`, no import of the markdown journal, no DynamoDB export) | Done |
| 7 | Core | 2.10 setup block in the snapshot (4h) | Done |
| 8 | Core | 2.4 NewsAPI rework and `news world`, CMC coin names, no-swap flow out of `missing` | Done |
| 9 | Core | 2.11 scan watchlist | Done |
| 10 | Core | Minimal prediction journal, in two PRs (decided 24 Oct): 10a 3.3 validator and 3.4 log; 10b 3.6 outcome scorer, 3.7 export and review skill | Done |
| 11 | Research | 3.1 clients, 3.2 prompts, 3.5 runner (3 follow-the-sun runs a day, 20 fixed coins) | Done |
| 12 | Research | Phase 5 Naive Bayes (5.1 to 5.5), graded by the same outcome scorer | Next |
| 13 | Research | Phase 9 freeze, run and analysis | |
| - | Later | revisit the chat model order once the agent is stable (free Gemini first, Haiku as the fallback; DeepSeek as a fallback if the experiment shows it is good), 1.6, 1.7 `lesson share`, 2.4 GDELT, 2.4 scheduled world-news watcher (Lambda or instance timer that flags major events), 2.5 whale proxy, 2.6 `--save`, 2.7 CMC pass-through, 5.6, Phases 4, 6, 7 and 8, `openclaw/configure.sh` (before the next rebuild) | |

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
| B11 | `openclaw/workspace/skills/market_analyzer.md` | Single file with hard-coded `/home/ubuntu/sentinel/...` paths; skill folder format not used. Removed in 2.9. |
| B12 | `openclaw/bootstrap.sh` | Installs the latest OpenClaw unpinned via `curl | bash`; writes scripts as heredocs from Terraform templates. |

---

## 2. Target repository layout

This is the target, not a scaffold: a folder is created together with its first real module, never as an empty placeholder.

```text
crypto_analytic/
  pyproject.toml                # package "sentinel", extras: [ec2], [lambda], [analysis], [dev]
  Makefile                      # test, lint, build-lambda, fmt
  sentinel/
    __init__.py
    config.py                   # settings: region, table names, watchlist, thresholds, model ids, prices
    aws.py                      # boto3 clients (timeouts, retries) and SSM SecureString keys, cached
    net.py                      # requests session: timeout, retries with backoff, rate limit, User-Agent
    log.py                      # JSON-lines logging
    health.py                   # readiness checks (keys, tables, bucket, CMC, Gemini)
    views.py                    # command results: compact JSON for the agent, 5-line Telegram text
    cli.py                      # `sentinel ...` entry point (click)
    data/
      cmc.py  feargreed.py  exchange.py  flow.py  whales.py
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
      base.py                   # shared DynamoDB helpers
      real.py  sim.py           # repositories for sentinel-real and sentinel-sim
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

- **Packaging:** `pyproject.toml`, editable install with pinned versions: `pip install -c constraints.txt -e ".[ec2,dev]"` locally (`make install`), `.[ec2]` in `/home/ubuntu/sentinel/venv` (bootstrap). `constraints.txt` holds the exact versions tested together; CI and bootstrap install from it, and `make lock` re-pins after an upgrade. Keep Lambda dependencies light (`requests`, `pydantic`; `boto3` is in the runtime). `ccxt`, `feedparser` and LLM SDKs are EC2-only extras. `pandas`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib` only in `[analysis]`.
- **Libraries:** `boto3`, `requests`, `pydantic>=2`, `click` (already used), `python-ulid`, `ccxt`, `feedparser`, `google-genai`, `anthropic`, `openai` (for OpenRouter's OpenAI-compatible API), `pytest`, `moto`, `ruff`.
- **HTTP:** every call goes through `sentinel.net` with `timeout=10`, 3 retries on 429/5xx waiting 1, 2 and 4 s (at least the source's minimum interval), and a per-source minimum interval. A Retry-After over 30 s returns the response at once instead of waiting.
- **Secrets:** only from SSM SecureString under `/sentinel/*` (Appendix B), read with `sentinel.aws.get_secret`. Sent in request headers only, never in URLs. Never as CLI arguments or environment variables, never printed, never logged (every loaded key is also redacted from log lines as a safety net).
- **Time and ids:** UTC everywhere, ISO 8601 with `Z`. Trade and prediction ids are ULIDs (sortable).
- **Numbers:** `Decimal` for anything stored in DynamoDB; floats only in analysis.
- **CLI output:** `--format json` (compact, for the agent) or `--format telegram` (5 lines or fewer, for the user). JSON output must stay small, because it lands in the agent's context.
- **Tests:** `pytest` with `moto` for DynamoDB and recorded JSON fixtures for every external API. No network in unit tests. One opt-in `@pytest.mark.live` smoke test per data source.
- **Skills:** every CLI command an OpenClaw skill uses is documented in that skill's `SKILL.md`, with the exact command line and an example output.
- **Logging:** JSON lines to stderr, so stdout carries only CLI output (journald collects both on EC2). The CLI logs at `WARNING`; services set `SENTINEL_LOG_LEVEL=INFO`. Lambda uses the runtime's JSON log format instead of `log.setup()`.

---

## Phase 1: Foundation, polish and DynamoDB [Core; 1.6 Later]

### 1.0 Accounts and API keys (manual, done by you, about 30 minutes)
- [x] Follow Appendix F.1 to F.2 and F.4 to F.5: dedicated Google account, Gemini key from AI Studio, stored in SSM.
- [x] The Anthropic key (F.3), created 2026-10-16 with $5 of prepaid credit and a $5 monthly spend limit; OpenClaw uses it for chat (Haiku 5.5).

**Accept (Stage A, no EC2 needed):** the Gemini test call in Appendix F returns text when run from your laptop (read the key from SSM with the AWS CLI, as in F.5); `aws ssm get-parameters-by-path --path /sentinel --with-decryption --query "Parameters[].Name"` lists the Gemini key. The Anthropic key and its test call are checked later, before Phase 3.5.

### 1.1 Repo hygiene and package skeleton
- [x] Create `pyproject.toml`, the `sentinel/` skeleton (section 2), `ruff` and `pytest` config, `Makefile`, `.gitignore`.
- [x] Implement `config.py`, `aws.py` (SSM keys), `net.py` (HTTP), `log.py`.
- [x] Move the current scripts to `legacy/` unchanged so the running agent keeps working until replacements land.

**Accept:** `pip install -e ".[ec2,dev]"` works; `sentinel --help` lists command groups; `pytest` and `ruff check` pass.

### 1.2 Port existing scripts into the package (behaviour-preserving)
Read each legacy script first and keep its behaviour, then improve.

| Legacy script | New command |
| --- | --- |
| `analysis/market_intelligence.py` | `sentinel market overview [--symbol X[,Y]]` (default BTC): market block (Fear & Greed as background, BTC dominance, total market cap 24 h change, stablecoin share from CMC global metrics) plus quotes. The old fixed rules are `rules_signal()` in `sentinel/eval/rules.py`, the RULES baseline. |
| `analysis/top_15_analysis.py`, `top_50_scalp.py` | `sentinel market top --limit 15` (legacy rule signal per coin) and `sentinel market scalp --limit 50` |
| `analysis/news_aggregator.py` | `sentinel news long SYM` (NewsAPI, documented as 24 h delayed, for long-range research); headlines only, the old keyword sentiment is dropped (the LLM judges sentiment, 2.4) |
| `analysis/whale_monitor.py` | `sentinel market whales SYM` (any symbol; real logic in 2.5) |
| `monitoring/threshold_monitor.py`, `track_coin.py` | replaced by stored watches (1.9): `sentinel watch add|list|remove|check` |
| `utils/quick_ping.py`, `cmc_check.py` | `sentinel health` already exists (1.8); quick_ping's BTC and SOL prices come from `sentinel market overview --symbol BTC,SOL` |
| `system_monitoring/*.sh` | `ops/` (paths from settings; S3 scripts take `--dry-run`; same backup layout, without the venv and repo clone that bootstrap rebuilds) |

- [x] Unify SSM names (Appendix B); remove every API key CLI argument.
- [x] Fix the README (SSM paths, NewsAPI.org vs NewsAPI.ai).

**Accept:** every legacy command has a new equivalent with compact JSON output; parser tests with fixtures for CMC listings and quotes, Fear & Greed and NewsAPI.

### 1.3 Terraform fixes
- [x] `ec2`: architecture derived from the instance type, Ubuntu 24.04 AMI chosen by architecture, encrypted gp3 root volume, IMDSv2 with hop limit 1, no inbound rules and no DNS/NTP egress rules (link-local, not filtered).
- [x] Replace the heredoc injection in `locals.tf` and `bootstrap.sh` with a static bootstrap (OS packages, venv, OpenClaw). Since 1.8 it also deploys the `sentinel` package (git clone at `sentinel_ref`; an S3 tarball instead if the repo goes private).
- [x] OpenClaw installed through the installer with `--version` and `--no-onboard`; `openclaw_version` variable and a check block warn until it is pinned. Record the version in `TOOLS.md` after the first bring-up.
- [x] IAM least privilege: both tables and their indexes, no `Scan`, SSM `/sentinel/*` read only, S3 read/write on the backup bucket and delete only under `strategy-share/`. Session Manager through AWS's minimal instance policy, not `AmazonSSMManagedInstanceCore` (which allows reading every SSM parameter in the account). Terraform owns the role's complete policy set (`aws_iam_role_policy_attachments_exclusive`, `aws_iam_role_policies_exclusive`), so a policy attached by hand shows in the plan and is removed. Later: SQS receive/delete.
- [x] State in S3 with native lock files (`env/bootstrap`, neutral committed bucket name); provider lock files committed; CI runs fmt, validate, tflint, shellcheck and gitleaks.
- [x] S3 lifecycle rule on the backup bucket (expire old `backups/` objects) so it stays under 5 GB; the bucket is not Terraform-managed, so import it or set the rule once.
- [ ] Optional: `terraform_remote_state` instead of passing the instance profile name as a string.

**Accept (Stage A):** `terraform fmt -check`, `validate` and `plan` are clean in every env. **Accept (Stage B, first bring-up):** a fresh instance boots to a working venv and OpenClaw is onboarded (document the manual `openclaw onboard` steps in `openclaw/README.md`).

### 1.4 DynamoDB tables in Terraform
- [x] Two tables, provisioned capacity (2 RCU/WCU, free tier), `PK` (S) + `SK` (S), `GSI1` (`GSI1PK`, `GSI1SK`) on both, `GSI2` (`GSI2PK`, `GSI2SK`) on `sentinel-sim`, TTL attribute `ttl` on `sentinel-sim`, `deletion_protection_enabled = true` on `sentinel-real`. Point-in-time recovery is off to keep the cost at $0; the tables have no backup.
- [x] Item layouts exactly as in Appendix A.

**Accept:** tables exist; the EC2 role can put and query; `tests/conftest.py` creates identical tables in `moto` from one shared spec.

### 1.5 Data access layer (`sentinel/store/real.py`, `sentinel/portfolio/service.py`)
- [x] Repositories: `TradeRepo`, `PositionRepo` and the starting balance (`BaselineRepo`). The others (`LessonRepo`, `PredictionRepo`, `SnapshotRepo`, `VoteRepo`, `ReportRepo`) come with the tasks that use them.
- [x] Buy and sell write the trade and update the position in one `TransactWriteItems`, with a condition on `version` (optimistic locking).
- [x] Average cost method: a buy updates `avg_price`; a sell keeps `avg_price` and adds `(sell_price - avg_price) * qty - fee` to `realised_pnl`; position closes when `qty` is below 1e-9.
- [x] Every read uses `Query` (by `PK` or `GSI1`), never `Scan`.

**Accept:** tests for buy, second buy, partial sell, full sell, realised P&L, fee handling, and a failed transaction on a version conflict. **Merge gate:** the same steps as manual test cases against the real AWS table `sentinel-sim` (the `SENTINEL_REAL_TABLE` override, under aws-vault), from starting cash through a full sell and the summary, ending with a cleanup step that deletes the test items.

### 1.6 Migration of lessons from the S3 backup (Stage B: needs the tables applied)
**Deferred (2026-10-16):** the lessons stay a workspace file (`memory/lessons_learned.md`, copied at bring-up and backed up daily); this migration waits until shared lessons (8.4) need `LESSON` items.

Only the lessons move over. Positions and the baseline are entered fresh at bring-up with the 1.7 commands; the May 2026 portfolio in the backup is not migrated.
- [ ] `sentinel migrate fetch --bucket openclaw-files --prefix <backup prefix>` downloads `lessons_learned.md` from the latest backup to a local folder.
- [ ] `sentinel migrate draft` turns its Principles, Success Cases and Mistakes sections into `migration/lessons.csv` for manual review. Use regex for obvious lines and leave anything unclear for the user to fill in.
- [ ] `sentinel migrate import --dry-run` then `import` writes the reviewed rows as `LESSON` items to `sentinel-real`.

**Accept:** the dry run prints the count; `sentinel lesson list` shows every reviewed lesson.

### 1.7 Switch the trade journal to DynamoDB
- [x] Commands: `sentinel trade add --side buy|sell --symbol SOL --qty 1.35 --price 72.6 [--fee 0.1]`, `sentinel portfolio summary --format telegram|json`. The daily `ops/s3_backup.sh` runs as an OpenClaw command automation (no model call); there is no `backup export` (decided 23 Oct: backups are the deployment's business, not the CLI's).
- [x] New skill folder `openclaw/workspace/skills/trade-journal/SKILL.md`; update `TOOLS.md`; stop all JSON portfolio writes.
- [ ] [Later] `sentinel lesson add|list` with `LESSON` items, together with 1.6 (decided 22 Oct: until then lessons stay in `memory/lessons_learned.md`, which the agent reads and the daily S3 backup covers).
- [ ] [Later] `sentinel lesson share` (daily, after the backup): renders the approved `LESSON` items as `beistroff_lessons_learned.md`, redacts dollar amounts, quantities and the baseline (rules and % results stay), and replaces yesterday's copy in your own subfolder of the shared Google Drive folder (F.9). `sentinel lesson auth` runs the one-time Google consent from the laptop. Defaults chosen 2026-10-15, change if you prefer: redacted, folder owned by the dedicated Google account.

**Accept (Stage B, after first bring-up; the CLI and tests are done in Stage A):** in Telegram, "I bought 100 XRP at 1.20" creates a trade and updates the position; "show my balance" returns a short table; the daily S3 backup still runs. **Merge gate:** none (no code change); the Telegram checks run after the release. The markdown journal is not imported (decided 22 Oct): the portfolio is entered fresh with `portfolio baseline` and `trade add`.

### 1.8 Readiness gate
Only the checks the agent cannot work without. Others join with their own task (the exchange in 2.1); OpenClaw and Telegram are checked after the manual onboarding.
- [x] `sentinel health [--wait SECONDS] [--format json|telegram]`, exit 1 when not ready. Checks: `dynamodb` (both tables ACTIVE), `s3` (backup bucket reachable), `cmc` (key from SSM, `/v1/key/info`, no credit cost), `gemini` (key from SSM, list models).
- [x] Retries at three levels: each request (`sentinel.net`, boto3 standard mode); the gate re-runs only transient failures (network, credentials not there yet, 429/5xx) every 5 s doubling to 60 s until the deadline, and stops at once on a fatal one (missing or bad key, missing table); bootstrap retries flaky network steps and waits for the dpkg lock and snap seeding.
- [x] Bootstrap clones the repo at `sentinel_ref` (Terraform variable, check block warns until it is a release tag), installs the package, then runs `sentinel health --wait 600` before installing OpenClaw, so a bad key fails within minutes; `~/sentinel/.ready` only when every step passed, otherwise bootstrap exits 1 and the instance stays up for debugging over SSM.
- [x] No key leaves the process: keys in headers only, key headers dropped on cross-host redirects, details from status and error codes only, loaded keys redacted from every log line; tests cover each failure path.

**Accept (Stage A):** `pytest` covers pass, fatal and transient cases for every check, the wait loop, and that no key shows up in any output. **Accept (Stage B):** the first boot ends with `~/sentinel/.ready`; `cloud-init status --long` shows done.

### 1.9 Watches and alerts (after 1.5)
Why (chat of 19 Oct): the agent kept a plan file of per-coin budgets, took its caps for deployed money, and re-checked every planned entry by hand in each message. Budgets set aside per coin are noise (decided 19 Oct): the flow is analyse, then watch a level, then get pinged when it is reached. Until this lands the agent notes watches in `memory/watchlist.md` (2.9) and checks them on request.
- [x] A watch is a logged prediction (the 3.4 `PRED` item with a `watch` map: trigger `touch_below`, `close_below` or `close_above`, stop, target, status, hit_at), so the 3.6 scorer grades it: `sentinel watch add|list|remove`.
- [x] `sentinel watch check`: code only, no LLM, from an OpenClaw command automation every 15 minutes (`openclaw automations add --command`, no model call; closed UTC candles for the close triggers). On a hit it marks the watch and prints a short alert, which OpenClaw delivers to Telegram; a quiet run prints `NO_REPLY` and costs nothing.
- [x] Amounts (agent side, in `AGENTS.md`): no formula and no per-coin caps. The agent suggests its conviction as a % of cash (never above 20 % per coin; BTC `neutral` caps it at high, `risk_off` means no new buys) and the user decides; code at most converts the % to USDT and enforces the 20 % ceiling. The tier is logged with each prediction so the scorer can check calibration.
- [x] `sentinel portfolio summary` states the cash and open positions first, so "nothing is deployed" is never in doubt.

**Accept:** tests for each trigger type on a fixture series, a watch with no candles, one alert per hit.

---

## Phase 2: Market data and signal hierarchy [Core; parts Later]

Why (agent runs of 16 and 17 Oct): the agent fetched raw data and eyeballed it. A top-50 scan took about 33 `web_fetch` calls and read levels off 10 daily candles; the daily BTC scan named $80.4k as support although BTC wicked to 79,775 on 15 Oct UTC, mixed wick and close levels, had no moving averages, and its news was unrelated to the coin. From here on code computes the signals and the agent reads them.

### 2.0 News query fix (`sentinel/data/newsapi.py`)
- [x] `sentinel news long SOL` returned unrelated headlines (housing, programming, fantasy sports). Query with coin aliases (ticker plus full name, e.g. `SOL` / `Solana`), English only, and keep only headlines that name the coin; when nothing relevant is found the output says so plainly.

**Accept:** a test with an unrelated headline in the fixture shows it dropped, and an empty result says "no relevant headlines".

### 2.1 Exchange candles (`sentinel/data/exchange.py`)
- [x] OKX as default and Kraken as fallback (for coins not on OKX, e.g. XMR); symbol map from CMC ticker to exchange pair (`XRP` to `XRP-USDT` on OKX, `XRPUSD` on Kraken).
- [x] Daily, 4-hour and hourly candles. Daily candles **always** use `bar=1Dutc`: OKX's default `1D` runs on Hong Kong time (16:00 to 16:00 UTC), which put the agent's dates a day off. Fix the example URL in `openclaw/workspace/AGENTS.md` too.
- [x] 5-minute file cache; every result carries its candle timestamps (UTC open time per candle, and whether it is closed).
- [x] Plain `requests` through `sentinel.net`, not `ccxt`: two endpoints only, the same timeouts, retries, rate limits and logging as every other source, no large dependency to import on each CLI call, and the scoring job (3.6) can reuse it as it is.
- [x] **First**, run a live check from the EC2 instance in `us-east-1` (candles and the 2.5 flow endpoints: `pytest -m live tests/test_exchange.py`; 17 Oct: OKX, Kraken, CMC and NewsAPI all answer from the instance). Binance blocks many cloud IP ranges with HTTP 451, so do not use Binance as a data source.

**Accept:** hourly and daily candles for BTC and 10 coins in under 10 s (7 s from a laptop on 17 Oct); switching the exchange is a config change (`exchanges` in `config.py`).

### 2.2 Indicators (`sentinel/signals/indicators.py`)
- [x] RSI(14), SMA20, SMA50 and SMA200 on daily candles, ATR(14), returns over 1 h, 24 h and 7 d, volume z-score over 30 days.
- [x] Range edges computed in code: 7-day and 30-day wick high and low with their UTC dates, plus the close range, clearly labelled.
- [x] Relative strength against BTC (return difference over 7, 14 and 30 days) and beta to BTC (90 days).

**Accept:** unit tests against hand-checked values on a fixture series.

### 2.3 BTC regime (`sentinel/signals/btc_regime.py`)
- [x] Inputs: BTC 24 h and 7 d change, price versus SMA50 and SMA200, BTC dominance (CMC global metrics, `sentinel.data.cmc.global_metrics`; reported, but it does not change the label without a dominance history).
- [x] Output: `regime` (`risk_on`, `neutral`, `risk_off`) plus the numbers. Document the rule in the docstring.

### 2.4 News (`sentinel/data/news_rss.py`, `gdelt.py`)
- [x] RSS feed list in config (CoinDesk, Cointelegraph, The Block, Decrypt; checked 17 Oct); parse with `feedparser`; dedupe by link; filter by coin aliases (`XRP`, `Ripple`); last 24 h; at most 5 headlines per section. The snapshot shows BTC's 2 freshest headlines in `market.headlines` (the newest of all feeds were mostly unrelated stories) and up to 3 of the coin's in `coin_news_fresh`, each article once; a failing feed is listed in `missing` as `rss:<name>`.
- [x] NewsAPI rework: the coin's news over 14 days, most read first (`sortBy=popularity`), at most 2 in the snapshot; a separate `sentinel news world` (the last 3 days) for what moves markets beyond crypto (rates, recession, US policy, bans, war, AI), which the agent runs only when a question needs it (macro questions, before a buy), never on every snapshot. The agent writes a one-line dated note of a major market event to memory and reads it there instead of fetching it again.
- [x] Coin names from CMC: headlines were matched by ticker and by the names in `config.COIN_NAMES` (20 coins), so other coins by ticker alone (19 Oct: two "Zcash" headlines were missed for ZEC). Names now come from CMC's top 100 listing, cached for a day (1 credit a day), with `COIN_NAMES` only for extra aliases.
- [ ] GDELT market-wide tone (P1, can come later).
- [x] Sentiment is judged by the LLM, not by code.

### 2.5 Flow and whales (`sentinel/data/flow.py`, `whales.py`) [Core: funding and open interest; whale proxy Later]
- [x] Funding rate, open interest and its 7-day change, long/short account ratio from OKX public endpoints (verified in the OKX API docs; access from `us-east-1` is checked with 2.1's live check).
- [x] Taker buy vs sell volume (moved up 26 Oct, money flow): `flow.taker_buy_pct`, the spot share of the last 24 h bought at the ask (OKX `rubik/stat/taker-volume`). The snapshot's `market` also has the total volume's change against yesterday and its share outside BTC (CMC global metrics, no extra credit).
- [ ] [Later] Whale proxy: share of volume from trades of $100k or more among recent trades.
- [ ] [Later] Volume-spike watch: an alert when a top-20 coin's volume jumps while its price is flat.

### 2.6 Snapshot builder (`sentinel/signals/snapshot.py`)
- [x] `sentinel snapshot SYM [--format json|telegram]` returns the pydantic `Snapshot` in hierarchy order (Appendix C) with an `as_of` timestamp: BTC, market mood, macro, coin news, flow, coin technicals, range levels, strength against BTC. Whales (2.5) and portfolio context (1.7) join when their tasks land.
- [x] Macro line: the next FOMC meeting from a static list in config (Federal Reserve calendar, update it once a year).
- [ ] [Later] Spot ETF net flows: no free, documented, machine-readable source confirmed (17 Oct: Farside and TFTC are web pages; NewHedge's API needs a token; no free terms found for SoSoValue's or CoinGlass's APIs; scrapers on Apify are paid). Add them when one turns up.
- [x] Missing sources become `null` and are listed in `missing`.
- [x] A coin without an OKX perpetual (XMR, VET, TON) has no flow by design: keep `flow` `null` but leave it out of `missing`, as the scan already does for funding.
- [x] Keep the JSON under about 1,500 tokens; add a size test.
- [ ] [Later] `--save` stores it as a `SNAP` item in `sentinel-sim` with a 180-day TTL.

**Accept:** snapshots for 10 coins in under 20 s (17 Oct, laptop: 19 s as 10 separate CLI calls, most of it Python start-up; about 0.8 s per snapshot); tests for missing sources and the size budget.

### 2.8 Market scan (`sentinel/signals/scan.py`)
Replaces the agent's own top-50 scan (about 33 `web_fetch` calls, levels read off raw candles).
- [x] `sentinel market scan [--limit 50] [--format json|telegram]`: one CMC listings call, then per coin its daily candles and OKX funding rate in parallel, in one process; BTC's regime first.
- [x] One row per coin under `columns`: price, 24 h and 7 d change (CMC, rolling), RSI14, above SMA50 and SMA200, strength against BTC over 7 days, distance to the 7-day wick low and high, funding. Stablecoins and wrapped BTC or ETH are skipped; coins without candles are listed in `missing`.
- [x] The Telegram form names the stand-outs: strongest and weakest against BTC, nearest the 7-day wick low, RSI extremes.
- [x] News count per coin (2.4): `news_24h`, the coin's headlines in the RSS feeds over the last 24 h (the feeds are read once per scan). No NewsAPI requests: one per coin would take about 50 s and half of the free plan's 100 a day. Titles come from `sentinel snapshot` for the coins worth a closer look.
- [x] Money flow per coin (added 26 Oct): `v_mc` (CMC 24 h volume over market cap) and `vol_z30` (yesterday's volume against its 30 days), from data the scan already fetches.

**Accept:** top 50 in about 5 s without NewsAPI (17 Oct, laptop: 5.3 s, 3.1 s with cached candles; about 3,200 characters of JSON); a test for the rows, skipped and missing coins and the size budget.

### 2.9 Agent instructions refresh (`openclaw/workspace/`)
Why (chat of 19 Oct): replies ran 15 to 20 lines, repeated the BTC gate and unchanged coins in every message, quoted tool internals ("41 rows, not 50"), and the workspace files contradict each other. An early, light version of 4.1.
- [x] Reply template in `AGENTS.md`: one verdict line per coin (`COIN price: buy / wait / avoid`), then at most 3 lines (one reason with two numbers at most, the trigger, the stop and size). One stop; alternatives only when asked. The BTC gate once, in one line, only when it changed since the last reply. Unchanged coins in one line ("No change: XMR, BNB"). No tool internals unless missing data changes the answer. A follow-up offer at most once per topic.
- [x] One BTC gate: green, yellow and red are `btc.regime` (`risk_on`, `neutral`, `risk_off`) from `sentinel`, not a second rule kept in `HEARTBEAT.md`.
- [x] Portfolio questions: read the trade journal before answering, and say "cash N USDT, no open positions" when that is the case. No per-coin budgets; watches are noted in `memory/watchlist.md` until 1.9.
- [x] Remove the contradictions: `SOUL.md` and `IDENTITY.md` still lead with volume to market cap and Fear & Greed (BTC first now); `memory/lessons_learned.md` names Binance as the price benchmark (blocked from AWS; OKX now) and a 10 % "take initial out" rule while the old skill says 3 %; delete `skills/market_analyzer.md` (B11: old scripts, tables and buttons).

**Accept:** in Telegram, a multi-coin question gets a compact block per coin (a verdict, one reason line, one line with trigger, stop and size) with no total line limit, and a follow-up only repeats what changed.

### 2.10 Setup block in the snapshot (`sentinel/signals/snapshot.py`)
Why (chat of 19 Oct): the agent improvised triggers and stops per coin and argued in prose that a stop 3.7 % away sat inside one day's range. Code computes these the same way every time.
- [x] `setup` after `levels`, on 4h candles (decided 23 Oct: trades last 12 h to 7 days): breakout trigger (a 4h close above the 48 h close high), pullback zone (4h SMA50 to the 48 h close low, when the price is above the 4h SMA50), stop (0.25 ATR below the 48 h wick low), stop distance in % and in 4h ATR, and room to the 30-day wick high in %. A stop under 1 ATR (4h) or half the daily ATR away is flagged `stop_in_noise`. 4h and 1h RSI in `technicals`.
- [x] `AGENTS.md`: quote `setup`; change it only with a stated reason.

**Accept:** hand-checked values on the `trending` fixture; the size test still passes.

### 2.11 Scan watchlist (`sentinel/signals/scan.py`)
Why (chat of 19 Oct): DOT was asked about but missing from "top 15" (it ranks lower), and the agent reported row counts instead of naming what was skipped.
- [x] `sentinel market scan --symbol DOT,ADA` adds coins outside the top N, in the same rows.
- [x] The output names the skipped stablecoins and wrapped coins (`skipped`), so a short row count needs no explanation.

**Accept:** a test with an extra symbol outside the listing and the `skipped` list.

### 2.7 CMC pass-through (`sentinel cmc get`) [Later: build it when a question needs more than `web_fetch` and the fixed commands give]
So the agent can ask CMC for more than the fixed commands without ever holding the key.
- [ ] `sentinel cmc get <endpoint> [--param key=value ...]`: read-only endpoints from an allowlist in config; `sentinel` adds the key header, trims the response to the requested fields and a size budget, and reports the credits used.
- [ ] A per-day credit budget in settings; the command refuses once it is spent (the free plan has a monthly credit limit).

**Accept:** tests for an allowed and a refused endpoint, the trimming, the budget, and that the key never appears in any output.

---

## Phase 3: Prediction journal and models [Core: 3.3, 3.4, 3.6, 3.7; Research: 3.1, 3.2, 3.5]

### 3.1 LLM clients (`sentinel/llm/`)
- [x] One interface `call(system, user, schema) -> (parsed, usage)` for Gemini (`google-genai`) and Anthropic (`anthropic`, models `claude-sonnet-5-5` and `claude-haiku-5-5`). OpenRouter (OpenAI-compatible, for the DeepSeek arm, model id in config) is built only if D1 is chosen at the 9.1 freeze (it needs `/sentinel/openrouter_api_key`). Check DeepSeek's price and data terms when that client is built; the arms only ever see market snapshots, never portfolio or personal data.
- [x] JSON output mode, retries on 429 with backoff, and logged tokens in and out, latency and cost (prices in `config.py`: Sonnet 5.5 $2 / $10 per million tokens in / out, Haiku 5.5 $0.10 / $0.50, Gemini free tier $0).
- [x] Record the exact model id string returned by each API.

### 3.2 Prompts and output schema
- [x] `PredictionOut` (Appendix D). `btc_context` comes first and is required.
- [x] Templates: `system.md` (core of SOUL and IDENTITY plus analyst rules, without the BTC-first order), `freeform.md` (today's style, for arm L0), `structured.md` (hierarchy, for all other arms). `gate_recheck.md` comes with the gate (step 12).
- [x] `prompt_hash` = sha256 of the rendered template without the data.

### 3.3 Deterministic validator (`sentinel/predict/validator.py`)
Runs on every answer before anything else (lean version, decided 24 Oct: no parsing of free text, and the schema states no range levels to compare):
- [x] `btc_context` not empty.
- [x] `entry` within 1% of the live price.
- [x] BUY: `target > entry > stop`; SELL: `target < entry < stop`; HOLD: no target or stop needed.
- [x] `horizon_h` in {1, 4, 12, 24, 72, 168} (decided 24 Oct: scalps 1 to 12 h, trades 1 to 7 days; calls of a month or more are investments and are not logged; another horizon is refused like bad JSON, since the scorer could never grade it); `confidence` between 0 and 1; reward-to-risk of 1 or more (warning only).
- [x] On failure: the call is stored with `valid = false` and its errors (counted in the results); no retry in code.

### 3.4 Chat path: `test-trade-scenario` skill
Minimal by design (2026-10-19): the agent logs its calls; it never scores or reviews them, which would spend its token budget.
- [x] `sentinel predict log --json '<PredictionOut>' --symbol XRP --model M --source chat` validates, stores a `PRED` item in `sentinel-sim` (coin, verdict, entry, trigger, stop, horizon, the chat model, and a compact snapshot from exchange candles: price, RSI, BTC regime and 24 h change) and returns the id plus a short message.
- [x] `sentinel predict show <id>` returns the full reasoning ("details").
- [x] Skill folder `skills/test-trade-scenario/SKILL.md`: read `memory/prediction_lessons.md`, build the snapshot, decide, log, reply in the short format. `memory/lessons_learned.md` stays for real trades only.

### 3.5 Scheduled path: experiment runner
- [x] `sentinel experiment run --slot 00|08|16` reads `experiment.yaml`, builds one snapshot per coin (stored as a `SNAP` item; without NewsAPI's day-old news, which keeps the free plan's quota for chat), runs every arm, stores one `PRED` per arm: one call per coin per run, for the one horizon fixed in `experiment.yaml` (24 h suggested, set at the 9.1 freeze).
- [x] Coins: a fixed list of 20 in `experiment.yaml`, the same for every arm (decided 25 Oct; a list that changed daily would mix model skill with coin selection): BTC, ETH, SOL, BNB, ADA, XRP, LINK, XMR, ZEC, LTC, AAVE, UNI, NEAR, AVAX, SUI, TON, DOT, XLM, TRX, DOGE. An arm on a model with a small free quota or a high price calls a random sample of them per run (F1 and S1: the same 4 coins, decided 25 Oct), the same sample on a re-run.
- [x] Idempotency key: date + slot + symbol + arm (re-runs skip existing items).
- [x] An OpenClaw command automation at 00:05, 08:05 and 16:05 UTC (decided 25 Oct, follow the sun: just after funding settles at 00, 08 and 16 UTC and, at 00:05, after the UTC daily close; the Asia, Europe and US sessions can be compared). It makes no model call in OpenClaw, so every arm gets an identical prompt and exact token logging.

### 3.6 Outcome scorer (hourly, code only, no LLM)
Records what the market did after each call, with zero model tokens. It is the answer key: the agent's calls (3.4, 3.5) and Naive Bayes' calls (Phase 5) are graded by the same scorer, and Naive Bayes learns from its outcomes. Core version: `sentinel predict score`, an hourly OpenClaw command automation on the instance that sends nothing (decided 24 Oct, like the watch check). The Lambda version waits for Phase 6.
- [x] Queries `GSI2` for `OPEN` items with `due_at <= now`, fetches candles since the prediction (15-minute up to 12 h, hourly above), and fills `checks` at each standard horizon up to the call's own (decided 24 Oct): price, return, hit. BUY is a hit above the entry, SELL below.
- [x] Records `target_hit_first` (target touched before stop, or the reverse, or neither) and `max_adverse_pct`.
- [x] A FLAT call (HOLD) is a hit when the price stays within ±1 % at the horizon.
- [x] Sets the next `due_at`; after the call's own horizon, sets `status = DONE` and removes the `GSI2` attributes.

### 3.7 Export and review (outside the agent)
Changed 2026-10-19: no report crons and no reviews by the agent. The user reviews the logs in a Claude chat, where the token budget is larger.
- [x] `sentinel predict export [--days 14]`: the calls and their outcomes, compact, to paste into a chat, with hit rates per horizon and per model computed by code.
- [x] A review skill in the repo, `.claude/skills/review-predictions/SKILL.md`, usable in Claude Code or pasted into any Claude chat with an export: hit rate per horizon, where the reasoning went wrong, recurring patterns, and at most 5 drafted lessons.
- [x] Lessons the user approves go to `memory/prediction_lessons.md` (separate from the real-trade lessons), which the 3.4 skill reads before a call. The user sends them to the agent, which writes the file.
- [ ] [Research] Per-arm hit rates with n and Wilson intervals move to the 9.3 analysis.

**Accept (end of Phase 3, core part):** a chat call is logged with its snapshot; the scorer fills its checks up to its horizon; the export of a week fits in one chat message; the review skill turns it into lessons.

---

## Phase 4: Telegram UX and short replies [Later]

### 4.1 Reply format
- [ ] Rule in `AGENTS.md` and every skill: compact per coin with no total line limit, fixed template, full reasoning saved in DynamoDB and sent only on "details <id>". Cap output tokens at about 250 for chat replies. (Changed 2026-10-16: replies are short by default and longer when the user asks or the market needs explaining; see the Telegram row in section 0.)

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
- [x] Only your Telegram user id may talk to the bot (DM allowlist in the Telegram channel config; done at bring-up).

**Accept:** tapping "XRP" in `/menu` gives a 5-line analysis with buttons; "Details" returns the full text.

---

## Phase 5: Naive Bayes model and gate [Research; 5.6 Later]

### 5.1 Historical dataset
- [ ] `sentinel nb build-dataset --days 730`: daily candles for the watchlist and BTC from the exchange, full Fear & Greed history (alternative.me supports `?limit=0`). BTC dominance history is dropped (CMC history needs a paid plan) unless a free source turns up. Save Parquet to S3 `datasets/`.

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

## Phase 6: Lambda alerts through SQS to OpenClaw [Later; the daily market scan covers alerts for now]

### 6.1 Terraform
- [ ] SQS queue plus dead-letter queue; Lambda functions `scan`, `score`, `nb_train` (arm64, python3.12); EventBridge Scheduler schedules; least-privilege IAM; log retention 14 days; AWS Budgets alarm at $5.

### 6.2 Packaging
- [ ] `make build-lambda`: `pip install --platform manylinux2014_aarch64 --only-binary=:all: --target build/ ".[lambda]"`, then zip. Keep the zip small (no `ccxt`, no pandas).

### 6.3 Scan rules (`sentinel/alerts/scan.py`, every 2 h)
- [ ] BTC move above 2% in 1 h or 5% in 24 h; watchlist coin above 4% in 1 h; funding rate above 0.05% per 8 h; Fear & Greed crossing 25 or 75; price within 1% of an active watch (1.9).
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

## Phase 7: Session hygiene and cost logging [Later]

- [ ] **7.1 Baseline first:** record input tokens per chat turn over about 30 normal messages (OpenClaw logs or `/status`).
- [ ] **7.2** Move scheduled work from the heartbeat and main session to OpenClaw cron jobs (fresh session per run). Keep `HEARTBEAT.md` minimal.
- [ ] **7.3** Enable `agents.defaults.contextPruning.mode: "cache-ttl"`; keep compaction on (default); make sure every CLI returns compact JSON.
- [ ] **7.4** Measure again and add a before/after table to `docs/project_notes.md`.

---

## Phase 8: Optional extensions [Later]

### 8.1 `cluster-prediction`
- [ ] `sentinel cluster run SYM`: Gemini Flash (technical role), one free OpenRouter model (sentiment role; model id in config), Claude Sonnet or Haiku (risk role), called in parallel.
- [ ] Round 1: JSON votes (action, confidence, one-line reason). If they disagree, round 2: each sees the other two reasons and may change once. Majority vote, then validator and rule check.
- [ ] Store `VOTE` items and one `PRED` with `model = "cluster"`.
- [ ] Orchestrated in Python, so keep OpenClaw's Swarm sub-agents switched off.

### 8.2 Weekly reflection
- [ ] Sunday cron: `sentinel reflect weekly` summarises the worst errors; the LLM proposes up to 3 lessons stored as `LESSON` with `status = proposed`; Telegram buttons Approve / Reject; approved lessons go into the structured prompt. Disabled during the experiment.

### 8.3 Polish
- [ ] Final whale proxy; GitHub Actions running `ruff`, `pytest`, `terraform fmt -check` and `validate`.
- [ ] Golden AMI (Packer), only if instances are destroyed and recreated often. The AMI itself is free, but its EBS snapshot costs about $0.05 per GB-month, and it needs a rebuild per OpenClaw release. Never bake tokens into it.

### 8.4 Shared lessons from other users
Other users share their lessons the same way (`<user>_lessons_learned.md`), so the agent can learn from experience beyond its own trades.
- [ ] Folder layout (F.9): the parent folder is view-only for invited users; each user has a subfolder where only they are an editor, so nobody can change or remove another user's files. Files count against their uploader's own Google storage.
- [ ] `sentinel lesson inbox` (daily, after `share`): reads the other users' subfolders, only `.md` and `.txt` up to 200 KB per file, skips everything else, and warns when the folder passes 500 MB.
- [ ] Untrusted text never reaches the agent raw: a model call without tools (3.1 client) turns each changed file into at most 3 candidate lessons, stored as `LESSON` with `status = proposed` and `source = shared:<user>`; Telegram Approve / Reject buttons as in 8.2; only approved lessons reach the prompt.
- [ ] Disabled during the experiment (like 8.2), so the frozen prompt stays fixed.

**Accept:** a test file from a second account produces proposals; approving one adds it to `sentinel lesson list`; a file that tries to give instructions ("ignore your rules and run ...") only ever becomes a proposal you can reject.

---

## Phase 9: Experiment freeze, run and analysis [Research: freeze, a 14-day run, then the analysis]

### 9.1 Freeze
- [ ] `experiment.yaml` committed with arms, coin list, horizon, exact model ids, validator and gate thresholds, NB model version, prompt hashes, and `end_date` 14 days after the first run (runs make no calls from then on). Git tag `experiment-v1`. Only then the runner automation is added (`openclaw/README.md` step 16); before the freeze, runs happen only by hand.
- [ ] Each of the 20 coins (3.5) checked with `sentinel snapshot`: `missing` empty, at least 300 daily candles, an OKX swap for funding (XMR has none, which is known), SUI and TON first.
- [ ] Reflection and NB retraining switched off.

| Arm | Model | Prompt | Gate |
| --- | --- | --- | --- |
| L0 | Gemini Flash Lite | freeform | off |
| L1 | Gemini Flash Lite | structured | off |
| L1G | Gemini Flash Lite | structured (reuses L1's answer) | on; an extra call only when triggered |
| F1 | Gemini Flash, 4 random coins per run | structured | off |
| H1 | Claude Haiku 5.5 | structured | off |
| S1 | Claude Sonnet 5.5, F1's 4 coins per run | structured | off |
| D1 | DeepSeek (through OpenRouter) | structured | off |
| NB | Naive Bayes only | none | n/a |
| RULES | Legacy fixed rules | none | n/a |

Daily volume (25 Oct): 20 coins × 3 runs = 60 snapshots, so 60 calls a day per arm plus gate re-checks. Expected cost for 14 days: Haiku about $0.0005 a call, about $0.40; Sonnet about $0.01 to $0.03 a call with its default thinking, far over the $5 limit on all coins, so S1 calls F1's 4 coins per run, 12 a day, about $2 to $5 for 14 days (decided 25 Oct; check the first day's cost); free Gemini Flash allows 20 calls a day and 5 a minute, so the full Gemini arms run on Flash Lite (500 a day, 15 a minute) and F1 calls 4 random coins per run, 12 a day (decided 25 Oct).

Shortened (2026-10-16): the run is 14 days. The final arms are chosen at the freeze to fit the $5 monthly Anthropic limit (S1 only if the budget allows), DeepSeek's price on OpenRouter (D1 only if a free variant exists or the credit it needs is small) and the free Gemini quota (5 requests a minute and 20 a day for 3.x Flash, so the Gemini arms may need a Flash Lite model).

### 9.2 Run
- [ ] Daily report check; watch for missing data and free-tier 429 errors; never change the frozen config mid-run (log incidents in `project_notes.md` instead).

### 9.3 Analysis (`analysis/`)
- [ ] `sentinel eval export --out data/experiment.parquet`.
- [ ] Scripts producing tables and figures for the write-up:
  - Wilson intervals (`statsmodels proportion_confint(method="wilson")`) and exact binomial test against 50% (`scipy.stats.binomtest`).
  - McNemar (`statsmodels mcnemar`): L1 vs H1, L1 vs L1G, L0 vs L1, and F1 vs S1, L1 and H1 on F1's coins only.
  - Cochran's Q (`statsmodels cochrans_q`) across L0, L1, L1G, then McNemar with Holm correction.
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
| POSITION | `POS` | `{SYM}` | `SYM#{SYM}` / `POS` | qty, avg_price, cost_basis, realised_pnl, version, updated_at |
| LESSON | `LESSON` | `{date}#{slug}` | none | text, tags, status (approved/proposed), source (manual/reflection) |
| META | `META` | `BASELINE` | none | baseline_usdt, since |

**`sentinel-sim`**

| Type | PK | SK | Indexes | Attributes |
| --- | --- | --- | --- | --- |
| SNAP | `SNAP#{SYM}` | `{ts}` | none | schema_version, payload (JSON string), missing, ttl (180 days) |
| PRED | `PRED#{date}` | `{ts}#{SYM}#{arm}` | GSI1: `SYM#{SYM}` / `{ts}`; GSI2 (sparse): `OPEN` / `{due_at}`, or `WATCH` / `{created_at}` while a watch is active | pred_id, symbol, arm, slot (scheduled calls: 00, 08 or 16), model, model_version, variant, source (chat/scheduled), action, direction, confidence, horizon_h, entry, target, stop, btc_context, btc_regime, reasons, rationale_full, prompt_hash, snapshot_ref, tokens_in, tokens_out, cost_usd, latency_ms, valid, validator_errors, warnings, risk_note, snapshot (chat calls: price, rsi14, btc_regime, btc_chg_24h), nb_p_up, gate_triggered, original_action, revised, status (OPEN/DONE), due_at, checks (map: `h1`, `h4`, `h12`, `h24`, `h72`, `h168` each with price, return_pct, hit), target_hit_first, max_adverse_pct, watch (map, 1.9: trigger, timeframe (close triggers), status active/hit/removed, hit_at, hit_price, removed_at) |
| VOTE | `PRED#{date}` | `{ts}#{SYM}#cluster#VOTE#{model}#{round}` | none | role, action, confidence, reason, tokens, cost_usd |
| ALERT | `ALERT#{rule}#{SYM}` | `{ts}` | none | value, ttl (6 h cooldown) |
| REPORT | `REPORT#{daily|weekly}` | `{date}` | none | text, metrics (map) |

## Appendix B: SSM parameters (SecureString)

`/sentinel/cmc_api_key`, `/sentinel/newsapi_key`, `/sentinel/gemini_api_key`, `/sentinel/anthropic_api_key`, `/sentinel/openrouter_api_key`, `/sentinel/openclaw_hook_token`. `/sentinel/telegram_token` and `/sentinel/telegram_user_id` (the only Telegram account allowed to talk to the bot) are stored here too, but only copied into OpenClaw's config at onboarding; `sentinel` never reads them. OpenClaw also gets `/sentinel/anthropic_api_key` at onboarding, for the chat model.

## Appendix C: Snapshot example (compact, hierarchy order)

`sentinel snapshot SOL` as built in 2.6 (a live run on 17 Oct 2026, about 1,500 characters; the CMC market fields and the headlines are filled in for the example). Market headlines (BTC's) and `coin_news_fresh` come from the 2.4 RSS feeds (up to 2 and 3 headlines; a live SOL snapshot with 5 market headlines was about 1,900 characters). `whales` (2.5) and `portfolio` (1.7) join when their tasks land.

```json
{
  "schema_version": 1, "as_of": "2026-10-17T08:31:53Z", "symbol": "SOL", "price": 104.92,
  "prices_at": "2026-10-17T08:31:53Z", "exchange": "okx",
  "btc": {"price": 81698.0, "chg_24h": -0.66, "chg_7d": -1.39, "sma50": 81361.6, "sma200": 72466.0, "above_sma50": true, "above_sma200": true, "dominance": 58.1, "regime": "neutral", "regime_points": 2},
  "market": {"fear_greed": 55, "total_mcap_chg_24h": -0.8, "stablecoin_share": 7.9, "headlines": [{"title": "...", "source": "CoinDesk"}]},
  "macro": {"next_fomc": "2026-10-28", "days_to_fomc": 11},
  "coin_news_fresh": [{"title": "...", "source": "Cointelegraph"}],
  "coin_news": [{"title": "...", "source": "..."}], "news_delayed_24h": true,
  "flow": {"funding_pct": -0.0012, "funding_interval_h": 8.0, "oi_usd": 313875577.0, "oi_chg_7d": -3.21, "long_short": 2.21},
  "technicals": {"rsi14": 39.7, "sma20": 113.206, "sma50": 109.425, "sma200": 87.5164, "above_sma50": false, "above_sma200": true, "atr14_pct": 4.65, "vol_z30": -0.43, "chg_1h": -0.16, "chg_24h": -1.78, "chg_7d": -4.62},
  "levels": {
    "d7": {"wick_low": 100.56, "wick_low_date": "2026-10-15", "wick_high": 113.4, "wick_high_date": "2026-10-12", "close_low": 104.29, "close_high": 111.34},
    "d30": {"wick_low": 100.56, "wick_low_date": "2026-10-15", "wick_high": 124.96, "wick_high_date": "2026-09-27", "close_low": 104.29, "close_high": 122.16}
  },
  "vs_btc": {"rs_7d": -3.15, "rs_14d": -8.69, "rs_30d": -3.67, "beta_90d": 1.24},
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
| `trade-journal` | "I bought/sold ...", "balance", "/balance" | `sentinel trade add`, `sentinel portfolio summary`, `sentinel portfolio baseline` |
| `analyse` | "analyse X", `/analyse`, `act:analyse:X` | `sentinel snapshot X --format json` |
| `test-trade-scenario` | "test trade X 24h", `/predict`, `act:predict:X:24` | `sentinel snapshot`, `sentinel predict log`, `sentinel predict show` |
| `review-predictions` (in the repo's `.claude/skills/`, used in Claude Code or a Claude chat, not by the agent) | the user, with a `sentinel predict export` | none; drafts lessons for `memory/prediction_lessons.md` |
| `nb-check` (optional) | `/nb`, `act:nb:X` | `sentinel nb check X` |
| `cluster-prediction` (optional) | `/cluster`, `act:cluster:X` | `sentinel cluster run X` |
| `system-ops` | health check, backups (as today) | `sentinel health`, `ops/s3_backup.sh` |

## Appendix F: Manual setup of model API keys

Do these steps yourself, in a browser and a terminal. Never paste a key into a chat, a Telegram message, a commit or a Claude Code prompt.

### F.1 Dedicated Google account
1. Create a new Google account just for this project (for example `sentinel.agent.<something>@gmail.com`). Turn on 2-step verification.
2. Use it only for this project: AI Studio, and later the shared lessons folder (F.9). Do not link it to your main Gmail, Drive or YouTube.
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

### F.7 Optional: OpenRouter (for `cluster-prediction` and the DeepSeek arm D1)
1. Create an account at openrouter.ai, then a key named `sentinel-cluster`; do not buy credits, so only `:free` models can run.
2. Free models allow 20 requests a minute and 50 a day (1,000 a day after $10 of lifetime credit purchases). Store it as `/sentinel/openrouter_api_key` the same way as F.4.

### F.8 If a key leaks
Create a new key, update the SSM parameter (`--overwrite`), restart the services, check that calls work, then delete the old key. In AI Studio this is the **API Keys** page; in the Claude Console the **API keys** page.

### F.9 Google Drive folder for shared lessons (for 1.7 and 8.4)
1. Signed in with the dedicated Google account (F.1), create a folder `sentinel-lessons` with one subfolder per user (`beistroff/`, `user1/`, ...).
2. Share the parent folder as **Viewer** with each invited user, and each user's subfolder as **Editor** with that user only.
3. In the Google Cloud project of the Gemini key (no billing needed), enable the Google Drive API and create an OAuth client of type **Desktop app**. Set the consent screen to **External** and **In production**: in Testing, Google expires refresh tokens after 7 days. The "unverified app" warning is expected for personal use.
4. Scopes: `drive.file` (write your own file) and `drive.readonly` (read the others').
5. Run `sentinel lesson auth` once from the laptop; it stores the client id, secret and refresh token as one SecureString, `/sentinel/gdrive_oauth`. Never paste them into a chat.

## Appendix G: Verify before relying on it

- [ ] OKX (or Kraken) public endpoints for candles, funding, open interest, taker volume and long/short ratio work from `us-east-1`.
- [ ] Exact OpenClaw config key for custom Telegram commands, and the `/hooks/agent` payload fields for delivering to Telegram.
- [ ] How to pin the OpenClaw version in the installer.
- [ ] Your real Gemini Flash free-tier limits in AI Studio (Google no longer publishes fixed numbers for the current Flash models). Free-tier prompts may be used by Google to improve products, so send market data only.
- [ ] CMC global-metrics field names (`btc_dominance`, `stablecoin_market_cap`, `total_market_cap_yesterday_percentage_change`): `pytest -m live` checks them.
- [ ] The t4g.small free trial end date (31 Dec 2026 per current reports) and what the instance will cost afterwards.
- [ ] Google OAuth for F.9: refresh-token lifetime for an unverified app "In production", and that Drive viewers of the parent folder cannot remove files from another user's subfolder.
