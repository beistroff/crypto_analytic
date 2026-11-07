# Crypto Sentinel: Implementation Plan

Core first, then the experiment, the rest later (see 0.2). One roadmap step is one session, one branch and one PR (`docs/RELEASING.md`). After each task, add 3 to 5 lines to `docs/project_notes.md`: what changed, why, and any before/after number.

## 0. Context and decisions

**What this is.** An OpenClaw agent on AWS EC2 that acts as a senior crypto analyst for one user over Telegram. It reads market data and news, keeps a trade journal and suggests trades; the user trades by hand. Code computes every number; the agent reads them and decides.

**The experiment.** Which cheap model makes better short-term crypto calls from the same data, and how much a fixed "BTC first" signal order and a Naive Bayes check help.

| Topic | Decision |
| --- | --- |
| Gateway | OpenClaw, version pinned, gateway on localhost, no ClawHub skills, exec allowlist (`sentinel` and `ops/*.sh` only). |
| Chat model | Claude Haiku 5.5, with free Gemini Flash and Flash Lite models as fallbacks. GPT models through the ChatGPT subscription run on OpenClaw's own runtime (`models.providers.openai.agentRuntime.id openclaw`), because the Codex runtime refuses the exec allowlist. |
| Claude API | An Anthropic API key with prepaid credit, a $5 monthly spend limit and no auto-reload. No background model jobs (memory dreaming, skill workshop) run on it. |
| Data access | `sentinel` commands return compact JSON. The agent never holds an API key: keys stay in SSM and are read by `sentinel` itself. |
| Data store | DynamoDB: `sentinel-real` (real trades) and `sentinel-sim` (predictions, snapshots, outcomes), both with deletion protection and no paid backup, provisioned inside the free tier. The workspace is backed up to S3 daily (OpenClaw command automation, lifecycle rule on `backups/`); the experiment data is exported to S3 once at the end of the run. |
| Scheduled jobs | OpenClaw command automations with no model call: watch check (15 min), prediction scorer (hourly), backup (daily), experiment runs (00:05, 08:05, 16:05 UTC, from the freeze). One agent automation: the daily market brief (07:00 UTC). |
| Naive Bayes | A sanity check and a gate, never the source of truth. The validator runs first. |
| Replies | Compact by default (rules in `openclaw/workspace/AGENTS.md`); longer when the user asks why or for details. |
| Real money | No automated trading. Experiment calls are simulated; real trades are journaled but are not experiment results. |
| Platform | `us-east-1`, Ubuntu 24.04, t4g.small (its free trial ends 31 Dec 2026: check the cost before then), Python 3.12. No inbound ports: access through SSM Session Manager only. |

### 0.2 Roadmap

Each step is one PR. A PR that touches DynamoDB or the instance merges only after its manual test cases pass (kept locally, outside git). After a step merges: tag a release, update the instance to the tag, smoke test (`sentinel health`, one snapshot, one scan, one Telegram question).

| Step | Track | Task | Status |
| --- | --- | --- | --- |
| 1 | Core | Bring-up: instance, OpenClaw, Telegram, daily backup, daily market scan | Done |
| 2 | Core | Market data: 2.0 to 2.6, 2.8 scan, RSS news | Done |
| 3 | Core | 2.9 agent instructions refresh | Done |
| 4 | Core | Trade journal, part 1: 1.4, 1.5, `trade add`, `portfolio summary` | Done |
| 5 | Core | 1.9 watches and alerts | Done |
| 5a | Core | `market candles`, the gate emoji, the daily scan prompt in the repo, `docs/RELEASING.md` | Done |
| 6 | Core | Trade journal, part 2: `trade-journal` skill, backup automation, S3 lifecycle rule | Done |
| 7 | Core | 2.10 setup block in the snapshot | Done |
| 8 | Core | NewsAPI rework and `news world`, CMC coin names | Done |
| 9 | Core | 2.11 scan watchlist | Done |
| 10 | Core | Prediction journal: 3.3, 3.4, 3.6, 3.7 | Done |
| 11 | Experiment | 3.1 clients, 3.2 prompts, 3.5 runner | Done |
| 12 | Experiment | Phase 5 Naive Bayes, graded by the same scorer | Done |
| 13 | Experiment | Phase 9: new arms (DeepSeek, GPT), freeze, 10-day run, analysis | Next |
| - | Later | Section 5 | |

## 1. Repository layout

```text
sentinel/        # the package: cli.py, views.py (JSON and Telegram forms), config, aws (SSM), net (HTTP), log, health
  data/          # sources: cmc, feargreed, exchange (OKX, Kraken), flow, news_rss, newsapi
  signals/       # indicators, btc_regime, snapshot, scan, schema
  llm/           # model clients and prompts/
  predict/       # runner, validator, gate, scorer, journal
  nb/            # Naive Bayes: features, history, naive_bayes, train, check
  store/         # DynamoDB repositories (real, sim)
  portfolio/     # buy, sell, average price, realised P&L
  alerts/        # watch check, news alert
  eval/          # legacy rule baseline
openclaw/        # bootstrap.sh, workspace/ (SOUL, AGENTS, skills), automations/, README (instance setup)
ops/             # s3_backup.sh and other instance scripts
analysis/        # experiment statistics
terraform/env/   # bootstrap, iam, dynamodb, ec2
experiment.yaml  # arms, coins, horizon, models (frozen at 9.1)
tests/           # pytest, moto, recorded fixtures
```

A folder is created with its first real module, never as an empty placeholder.

## 2. Conventions

- **Packaging:** `pyproject.toml`, editable install pinned by `constraints.txt` (`make install`; `make lock` re-pins). LLM SDKs and `feedparser` are EC2 extras; analysis libraries only in `[analysis]`.
- **HTTP:** every call through `sentinel.net`: timeout 10 s, 3 retries on 429/5xx (1, 2, 4 s), a minimum interval per source.
- **Secrets:** SSM SecureString under `/sentinel/*` (Appendix B), read with `sentinel.aws.get_secret`. In headers only, never in URLs, CLI arguments, environment variables or logs (loaded keys are redacted from log lines).
- **Time and ids:** UTC, ISO 8601 with `Z`; ids are ULIDs. `Decimal` for anything stored in DynamoDB.
- **CLI output:** `--format json` (compact, for the agent) or `--format telegram` (5 lines or fewer). JSON lands in the agent's context, so size tests keep it small.
- **Tests:** `pytest` with `moto` and recorded fixtures, no network (opt-in `@pytest.mark.live` per source). One test per real code path. CI runs `ruff` and `pytest` on every PR.
- **Logging:** JSON lines to stderr; stdout carries only CLI output.

## 3. Done

Task numbers stay as they are, because code and docs refer to them.

| Task | What | Where |
| --- | --- | --- |
| 1.1 to 1.3 | Package, legacy scripts ported, Terraform fixes and hardening (IMDSv2, encrypted EBS, least-privilege IAM, no inbound rules), static bootstrap | `sentinel/`, `terraform/`, `openclaw/bootstrap.sh` |
| 1.4, 1.5 | DynamoDB tables (Appendix A); trades and positions in one transaction with optimistic locking, average-cost P&L, `Query` only | `store/`, `portfolio/` |
| 1.7 | Trade journal in DynamoDB and its skill | `trade add`, `portfolio summary`, `portfolio baseline` |
| 1.8 | Readiness gate, used by bootstrap | `sentinel health` |
| 1.9 | Watches (a watch is a logged prediction), checked every 15 min with no model call | `watch add|list|remove|check` |
| 2.0 to 2.3 | Coin-matched news, OKX candles (Kraken fallback, daily candles on UTC), indicators, range edges, strength against BTC, BTC regime | `data/`, `signals/` |
| 2.4 | RSS headlines in the snapshot; NewsAPI's most read and `news world`; major-news alert (its 30-minute job is off since 3 Nov, too noisy; the command stays) | `news long`, `news world`, `news alert` |
| 2.5 | Funding, open interest, long/short (all accounts and top traders), spot taker buy share | `data/flow.py` |
| 2.6 | Snapshot in hierarchy order: BTC, market, macro, news, flow, technicals, levels, strength; missing sources listed | `sentinel snapshot` |
| 2.8, 2.11 | Market scan, one row per coin, with `--symbol` extras and `skipped` | `market scan` |
| 2.9 | Agent instructions: reply template, one BTC gate, no per-coin budgets | `openclaw/workspace/` |
| 2.10 | 4h setup: trigger, pullback zone, stop and its noise flag, room to the 30-day high | `snapshot.setup` |
| 2.12 | Daily market brief: BTC snapshot, top coins by 24 h change with `v_mc`, headlines with major events first, BTC levels with their distance | `market brief`, `openclaw/automations/daily-scan.md` |
| 3.1, 3.2 | Model clients (Gemini, Anthropic) with tokens, cost and latency; `PredictionOut` with `btc_context` first; prompts `system`, `freeform`, `structured`, `gate_recheck` | `llm/` |
| 3.3 | Validator: `btc_context`, entry within 1 % of the live price, target and stop on the right side, horizon in {1, 4, 12, 24, 72, 168} h, confidence 0 to 1 | `predict/validator.py` |
| 3.4 | Chat calls logged as test trades | `predict log`, `predict show`, `test-trade-scenario` |
| 3.5 | Experiment runner: one snapshot per coin, every arm, idempotent per date, slot, coin and arm; 20 fixed coins | `experiment run` |
| 3.6 | Hourly outcome scorer, code only: checks at each horizon, target or stop first, worst move. HOLD is a hit when buying would not have paid | `predict score` |
| 3.7 | Export for review in a Claude chat, and the review skill | `predict export`, `.claude/skills/review-predictions/` |
| 5.1 to 5.3 | Daily dataset in S3, features (weekday, ATR %, 7-day return against BTC), plain-Python categorical Naive Bayes, walk-forward report against the base rate and a logistic regression | `nb build-dataset`, `nb train` |
| 5.4 | Live check and the gate: a BUY or SELL with confidence 0.6 or more that NB contradicts (`p_up` 0.45 or less, 0.55 or more) is asked once more with `gate_recheck.md`; arm L1G | `nb check`, `predict/gate.py` |
| 5.5 | Does BTC lead the altcoins? Same day 90 %, next day 49 % (p 0.15): it moves with them, it doesn't lead | `analysis/rq3_btc_leads.py` |

## 4. Next: Phase 9, the experiment

### 9.0 New arms (one PR each, before the freeze)
- [x] DeepSeek: a client for `deepseek-flash` (V4.1 Flash) with thinking off, key `/sentinel/deepseek_api_key`, all 20 coins (arm D1).
- [x] GPT: GPT-6 Luna through the ChatGPT subscription (OpenClaw's one-shot `infer model run`, instance only), all 20 coins (arm G1). Its monthly allowance is shared with other Codex use, so the freeze notes carry a fallback rule (e.g. under 40 % left on day 3: a 4-coin sample).
- [x] Measure a few calls per arm (cost, quota) before the freeze.

### 9.1 Freeze
- [x] `experiment.yaml` with arms, coins, horizon, exact model ids, validator and gate thresholds, NB model version, prompt hashes and `end_date` 2026-11-19: a 10-day run from 9 Nov, with an interim report on day 7. The automation's runs on 7 and 8 Nov are a warm-up, left out of the analysis. Git tag `experiment-v1`. Only then add the runner automation (`openclaw/README.md` step 16); before that, runs are by hand.
- [x] Model versions noted where the API gives only an alias (`deepseek-flash` is V4.1-Flash-1017 on DeepSeek's pricing page, 7 Nov), and checked again at the end of the run.
- [x] Each coin checked with `sentinel snapshot`: `missing` empty (7 Nov).
- [ ] No NB retraining and no prompt changes during the run.

| Arm | Model | Prompt | Note |
| --- | --- | --- | --- |
| L0 | Gemini Flash Lite | freeform | |
| L1 | Gemini Flash Lite | structured | |
| L1G | Gemini Flash Lite | structured | reuses L1's answer; NB gate on |
| F1 | Gemini Flash | structured | 4 random coins per run (free quota) |
| H1 | Claude Haiku 5.5 | structured | |
| S1 | Claude Sonnet 5.5 | structured | F1's 4 coins (cost) |
| D1 | DeepSeek V4.1 Flash | structured | thinking off |
| G1 | GPT-6 Luna | structured | ChatGPT subscription |
| NB | Naive Bayes only | none | |
| RULES | Legacy fixed rules | none | |

20 coins × 3 runs = 60 calls a day per full arm. Final arms are chosen at the freeze to fit the $5 Anthropic limit and the free quotas.

### 9.2 Run
- [ ] A daily look at the run results (each run's line in Telegram), missing data and 429 errors; an interim report on day 7 (15 Nov). The frozen config never changes mid-run: incidents go to `project_notes.md`.

### 9.3 Analysis (`analysis/`)
- [ ] Wilson intervals and a binomial test against 50 %; McNemar for paired arms (L1 vs H1, L1 vs L1G, L0 vs L1; F1 vs S1, L1 and H1 on F1's coins); Cochran's Q across L0, L1, L1G with Holm correction; Brier score with a reliability diagram; Wilcoxon and a day-block bootstrap on simulated returns; a cost table per arm (tokens, USD, latency).

## 5. Later

- **Journal:** lessons in DynamoDB with `lesson add|list` (1.6, 1.7); until then they stay in `memory/lessons_learned.md`.
- **Data:** GDELT market tone (2.4); a whale proxy and a volume-spike watch (2.5); spot ETF flows once a free documented source exists, `snapshot --save` (2.6); a CMC pass-through with an endpoint allowlist and a credit budget (2.7).
- **4. Telegram:** a `/` command menu and inline buttons (`channels.telegram.capabilities.inlineButtons`), "details <id>" for the full reasoning.
- **5.6** Weekly NB retrain (never during the experiment); an optional `nb-check` skill.
- **6. Alerts through SQS:** scan rules in a Lambda (BTC and watchlist moves, funding, Fear & Greed crossings), SQS, an EC2 poller posting to OpenClaw's local hook, no model call when quiet; AWS Budgets alarm at $5.
- **7. Session cost:** measure input tokens per chat turn, prune context, measure again.
- **8.1** A three-model vote (`cluster run`), orchestrated in Python.
- **8.2** Weekly reflection: up to 3 proposed lessons, approved by the user in Telegram.
- **8.3** A golden AMI, only if instances are rebuilt often; `openclaw/configure.sh` before the next rebuild.
- **8.4** Shared lessons from other users through a Google Drive folder (one subfolder per user); untrusted text becomes proposals only.
- **8.5** On-chain metrics: MVRV, NVT, exchange net flows and whale transfers, from a free source if one exists, in the snapshot's market block.

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
| PRED | `PRED#{date}` | `{ts}#{SYM}#{arm}` | GSI1: `SYM#{SYM}` / `{ts}`; GSI2 (sparse): `OPEN` / `{due_at}`, or `WATCH` / `{created_at}` while a watch is active | pred_id, symbol, arm, slot (scheduled calls: 00, 08 or 16), model, model_version, variant, source (chat/scheduled), action, direction, confidence, horizon_h, entry, target, stop, btc_context, btc_regime, reasons, rationale_full, prompt_hash, snapshot_ref, tokens_in, tokens_out, cost_usd, latency_ms, valid, validator_errors, warnings, risk_note, snapshot (chat calls: price, rsi14, btc_regime, btc_chg_24h), nb_p_up, gate_triggered, original_action, revised, status (OPEN/DONE), due_at, checks (map: `h1`, `h4`, `h12`, `h24`, `h72`, `h168` each with price, return_pct, hit), target_hit_first, max_adverse_pct, watch (map: trigger, timeframe (close triggers), status active/hit/removed, hit_at, hit_price, removed_at) |
| VOTE | `PRED#{date}` | `{ts}#{SYM}#cluster#VOTE#{model}#{round}` | none | role, action, confidence, reason, tokens, cost_usd (8.1) |
| ALERT | `ALERT#{rule}#{SYM}` | `{ts}` | none | value, ttl (6 h cooldown) (6) |

## Appendix B: SSM parameters (SecureString)

`/sentinel/cmc_api_key`, `/sentinel/newsapi_key`, `/sentinel/gemini_api_key`, `/sentinel/anthropic_api_key`, `/sentinel/deepseek_api_key`. `/sentinel/telegram_token` and `/sentinel/telegram_user_id` (the only account allowed to talk to the bot) are copied into OpenClaw's config at onboarding; `sentinel` never reads them. The instance role reads `/sentinel/*`, so a new key needs no IAM change.

## Appendix C: API keys

Never paste a key into a chat, a Telegram message, a commit or a prompt.

- **Gemini:** an AI Studio API key in a Google account used only for this project, restricted to the Gemini API, with no billing on its project (the free tier is for projects without billing). Limits are per project, not per key. Free-tier prompts may be read by Google: send market data only.
- **Anthropic:** a Claude Console key with prepaid credit, a spend limit and no auto-reload. A Claude subscription does not include API use.
- **DeepSeek:** a platform key with a small prepaid balance.
- **Store a key** without it reaching the shell history, e.g. in PowerShell:
  ```powershell
  $k = Read-Host "API key" -AsSecureString; aws ssm put-parameter --name /sentinel/<name> --type SecureString --overwrite --value ([System.Net.NetworkCredential]::new('', $k).Password); Remove-Variable k
  ```
- **If a key leaks:** create a new key, overwrite the SSM parameter, check that calls work, then delete the old key.
