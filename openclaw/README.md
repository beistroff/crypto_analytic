# OpenClaw Agent

This directory holds the agent's OpenClaw side: its workspace (persona, rules, memory templates) and the instance bootstrap. The data tools the agent calls are the `sentinel` package at the repo root (`sentinel --help`); operational shell scripts are in `ops/`; the old standalone scripts are kept unchanged in `legacy/` until their replacements are proven.

**Note:** This directory does not contain the agent's full memory or context. Those dynamic files are generated during operation within the `/workspace` and are backed up separately to S3 (`ops/s3_backup.sh`).

## Directory Structure

- **`/workspace`**: This is the agent's "mind." It contains foundational files like `AGENTS.md` and `SOUL.md` that define the agent's behavior. The files included in the repository serve as a powerful starting template, but users are encouraged to tune and customize them to fit their own needs and strategies.

- **`bootstrap.sh`**: run by Terraform's `user_data` on a new EC2 instance: OS packages, the `sentinel` package at `sentinel_ref`, the readiness gate (`sentinel health`), a 2 GB swapfile, then OpenClaw.

---

## First Bring-up: OpenClaw Onboarding

Done by hand over SSM once bootstrap has finished (`~/sentinel/.ready` exists). Tested with OpenClaw 2026.10.3. Keys never appear on screen or on a command line: they go from SSM to OpenClaw through a pipe or the environment. These SSM parameters must exist first: `/sentinel/gemini_api_key`, `/sentinel/anthropic_api_key` (key with a $5 monthly spend limit), `/sentinel/telegram_token` and `/sentinel/telegram_user_id`.

1. Connect with `aws ssm start-session --target <instance-id>`, then run `sudo -iu ubuntu` and `export XDG_RUNTIME_DIR=/run/user/$(id -u)` (`systemctl --user` needs it under `sudo`).
2. Onboard with the Gemini key from the environment:
   ```bash
   GEMINI_API_KEY="$(aws ssm get-parameter --region us-east-1 --name /sentinel/gemini_api_key --with-decryption --query Parameter.Value --output text)" openclaw onboard --auth-choice gemini-api-key --skip-channels --skip-skills --install-daemon
   ```
   Decline Google sign-in, Gemini CLI, Antigravity and ClawHub. Keep the gateway on loopback with token auth (port 18789). The wizard's default model is a Pro model with no free quota; pick a Flash model.
3. Stop the gateway for the configuration steps: `systemctl --user stop openclaw-gateway.service`.
4. Load only the plugins in use (all 41 are enabled by default, and the gateway then needs about 1 GB):
   ```bash
   openclaw config set plugins.allow '["google","memory-core","device-pair","document-extract","anthropic"]' --strict-json
   ```
5. Add the Anthropic key and set the models: Haiku first, free Gemini models as fallbacks.
   ```bash
   aws ssm get-parameter --region us-east-1 --name /sentinel/anthropic_api_key --with-decryption --query Parameter.Value --output text | openclaw models auth paste-api-key --provider anthropic
   openclaw models set anthropic/claude-haiku-5-5
   openclaw config set agents.defaults.model.fallbacks '["google/gemini-3.8-flash","google/gemini-3.7-flash","google/gemini-3.6-flash","google/gemini-3.5-flash-lite","google/gemini-3.1-flash-lite"]' --strict-json
   ```
6. Telegram: the bot token goes into a file through a pipe (redirecting the snap `aws` straight into a file left it empty), and only your numeric user id may write to the bot.
   ```bash
   install -d -m 700 ~/.openclaw/credentials
   aws ssm get-parameter --region us-east-1 --name /sentinel/telegram_token --with-decryption --query Parameter.Value --output text | install -m 600 /dev/stdin ~/.openclaw/credentials/telegram.token
   openclaw config set channels.telegram.enabled true
   openclaw config set channels.telegram.tokenFile /home/ubuntu/.openclaw/credentials/telegram.token
   openclaw config set channels.telegram.dmPolicy allowlist
   openclaw config set channels.telegram.allowFrom "[\"tg:$(aws ssm get-parameter --region us-east-1 --name /sentinel/telegram_user_id --with-decryption --query Parameter.Value --output text)\"]" --strict-json
   openclaw config set channels.telegram.configWrites false
   ```
7. Heartbeats off until `HEARTBEAT.md` is rewritten: `openclaw config set agents.defaults.heartbeat.every "0m"`.
8. Exec only for `sentinel` and the `ops/` scripts:
   ```bash
   openclaw exec-policy set --host gateway --security allowlist --ask off --ask-fallback deny
   openclaw approvals allowlist add --agent main "/home/ubuntu/sentinel/venv/bin/sentinel"
   openclaw approvals allowlist add --agent main "/home/ubuntu/sentinel/src/ops/*.sh"
   ```
9. Workspace: copy `SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `TOOLS.md`, `skills/` and `memory/lessons_learned.md` from `~/sentinel/src/openclaw/workspace/` into `~/.openclaw/workspace/`, write `USER.md` from `USER.md.example` by hand (it stays on the instance), and delete `BOOTSTRAP.md`.
10. Run `openclaw config validate && systemctl --user start openclaw-gateway.service`. In Telegram send `/new`, then "run a health check".
11. Watch alerts (plan 1.9): an OpenClaw command automation runs `sentinel watch check` every 15 minutes with no model call. A hit prints a short alert, which goes to your Telegram chat; a quiet run prints `NO_REPLY` and sends nothing. `SENTINEL_LOG_LEVEL=ERROR` keeps routine warnings (stderr) out of the chat.
    ```bash
    openclaw automations add --name "Watch check" --every 15m --command-argv '["/home/ubuntu/sentinel/venv/bin/sentinel","watch","check","--format","telegram"]' --command-env SENTINEL_LOG_LEVEL=ERROR --timeout-seconds 120 --announce --channel telegram --to "$(aws ssm get-parameter --region us-east-1 --name /sentinel/telegram_user_id --with-decryption --query Parameter.Value --output text)"
    openclaw automations list
    ```
    `openclaw automations runs <id>` shows the run history.
12. Daily market scan: an agent automation at 07:00 UTC whose prompt is `openclaw/automations/daily-scan.md`. After a release that changes the file, set it again on the existing job (`openclaw automations list` shows the id):
    ```bash
    openclaw automations edit <id> --message "$(cat ~/sentinel/src/openclaw/automations/daily-scan.md)"
    openclaw automations run <id>
    ```

13. Backup bucket lifecycle (once, from your laptop; the instance role cannot change it, and cannot delete backups either, so S3 expires them itself): `ops/s3_lifecycle.json` expires everything under `backups/` after 30 days (older versions after 7, if the bucket is versioned), which keeps the bucket far under 5 GB. `strategy-share/` is not touched. The call replaces the bucket's whole lifecycle configuration, so look at the current one first:
    ```bash
    aws-vault exec sentinel-deploy -- aws s3api get-bucket-lifecycle-configuration --bucket openclaw-files
    aws-vault exec sentinel-deploy -- aws s3api put-bucket-lifecycle-configuration --bucket openclaw-files --lifecycle-configuration file://ops/s3_lifecycle.json
    ```
    `get-bucket-lifecycle-configuration` should now print both rules; a `NoSuchLifecycleConfiguration` error before the first `put` is normal.
14. Daily backup: an OpenClaw command automation runs `ops/s3_backup.sh` at 04:00 UTC (OpenClaw's own "Memory Dreaming" job runs at 03:00, and two jobs at once crowd the 2 GB instance) with no model call and sends nothing to Telegram. It copies the workspace and the sentinel folder to `backups/<UTC stamp>/`; the DynamoDB tables are not in it (the trade journal is re-entered by hand if it is ever lost). Remove an older system crontab entry for the script first (`crontab -l`), so it does not run twice. The snap `aws` is in `/snap/bin`, which the gateway's PATH may lack:
    ```bash
    openclaw automations add --name "Daily backup" --cron "0 4 * * *" --tz UTC --command-argv '["/home/ubuntu/sentinel/src/ops/s3_backup.sh"]' --command-env PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin --timeout-seconds 600 --no-deliver
    openclaw automations run <id>
    ```
15. Prediction scorer (plan 3.6): an OpenClaw command automation runs `sentinel predict score` every hour with no model call and sends nothing to Telegram. It checks every logged test call that is due against the exchange candles; `sentinel predict export` shows the results. The run history (`openclaw automations runs <id>`) has one line per run, such as `Due 2: 1 graded, 1 done`.
    ```bash
    openclaw automations add --name "Prediction scorer" --every 1h --command-argv '["/home/ubuntu/sentinel/venv/bin/sentinel","predict","score","--format","telegram"]' --command-env SENTINEL_LOG_LEVEL=ERROR --timeout-seconds 300 --no-deliver
    openclaw automations run <id>
    ```
16. Experiment runs (plan 3.5): an OpenClaw command automation runs `sentinel experiment run` at 00:05, 08:05 and 16:05 UTC with no model call in OpenClaw and sends nothing to Telegram. Each run takes the 20 coins of `experiment.yaml`, and every arm (Gemini Flash Lite on all of them; Haiku on all; Gemini Flash and Sonnet on the same 4 random ones) calls its model directly on the same snapshot; the calls go into the prediction journal and the hourly scorer grades them. A run takes about 10 minutes, up to an hour when free Gemini queues its answers (it waits between free Gemini calls and gives each up to 10 minutes); its run history line looks like `Run 2026-10-26 08: L0 20, L1 20, F1 4, H1 20, S1 4; $0.0900`. Add it only at the experiment freeze (plan 9.1), not with a release, after setting `end_date` in `experiment.yaml` to 14 days after the first run: from that date the runs make no model calls (`experiment ended`), so a forgotten automation costs nothing; remove it then.
    ```bash
    openclaw automations add --name "Experiment run" --cron "5 0,8,16 * * *" --tz UTC --command-argv '["/home/ubuntu/sentinel/venv/bin/sentinel","experiment","run","--format","telegram"]' --command-env SENTINEL_LOG_LEVEL=ERROR --timeout-seconds 3600 --no-deliver
    openclaw automations run <id>
    ```
17. Major-news alert (plan 2.4): an OpenClaw command automation runs `sentinel news alert` every 30 minutes with no model call. It reads the free crypto news feeds and sends a short Telegram alert only for a market-moving headline (an exchange hack or exploit, frozen or halted withdrawals, an insolvency, a delisting or ban, a rate decision, a stablecoin depeg): up to 3 of the newest headlines, each with its source (e.g. `⚠️ Binance hack sends bitcoin, ether lower (CoinDesk)`), and "+N more on this" when there are more. After an alert it stays quiet for 3 hours, skipping the follow-ups; a quiet run prints `NO_REPLY` and sends nothing.
    ```bash
    openclaw automations add --name "News alert" --every 30m --command-argv '["/home/ubuntu/sentinel/venv/bin/sentinel","news","alert","--format","telegram"]' --command-env SENTINEL_LOG_LEVEL=ERROR --timeout-seconds 120 --announce --channel telegram --to "$(aws ssm get-parameter --region us-east-1 --name /sentinel/telegram_user_id --with-decryption --query Parameter.Value --output text)"
    openclaw automations run <id>
    ```

Things learned on the way:
- Gemini free tier: the 3.x Flash models allow 5 requests a minute and 20 a day, the Lite models 15 and 500, Pro models none. OpenClaw retries a rate-limited call up to 10 times and Google counts each try, so the free Flash models cannot carry an agent on their own. Google Search grounding has no free quota for Gemini 3 and newer.
- `TOOLS.md` is not loaded into the session, so the tool list lives in the Tools section of `AGENTS.md`.
- Every `openclaw` command starts a Node process of a few hundred MB. On a 2 GB instance, avoid running them while the agent is answering.
- `openclaw models` prints a masked fragment of each key; use `openclaw models | head -8` to see the models only.

---

## OpenClaw Runtime Structure (`~/.openclaw`)

When the OpenClaw agent is installed, it creates a standard runtime directory in the user's home folder (`~/.openclaw`). This is where the agent's state, memory, and learned skills are stored. For more details, please refer to the official OpenClaw documentation.

A brief overview of the key directories:

- **`/workspace`**: The agent's active "mind." It contains the core personality files (`SOUL.md`, `IDENTITY.md`), operational guides (`AGENTS.md`), and memory files that the agent uses in every session. The contents of this project's `/workspace` are copied here to serve as a starting point.

- **`/workspace/memory`**: This is where the agent stores its long-term and short-term memories. It includes daily log files (`YYYY-MM-DD.md`) and curated, important recollections (`lessons_learned.md`).

- **`/skills`**: This directory holds reusable capabilities that the agent can learn and execute. Each skill is a self-contained module that extends the agent's abilities, allowing it to interact with new tools or APIs.

This separation ensures that the core logic (in this repository) is distinct from the agent's dynamic, operational state (in `~/.openclaw`).