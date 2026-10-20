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
9. Workspace: copy `SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `TOOLS.md` and `memory/lessons_learned.md` from `~/sentinel/src/openclaw/workspace/` into `~/.openclaw/workspace/`, write `USER.md` from `USER.md.example` by hand (it stays on the instance), and delete `BOOTSTRAP.md`.
10. Run `openclaw config validate && systemctl --user start openclaw-gateway.service`. In Telegram send `/new`, then "run a health check".
11. Watch alerts (plan 1.9): `sentinel watch check` posts each hit to the hook `POST /hooks/watch`, which runs the agent in an isolated session and delivers its reply to you on Telegram. The hook token is its own value (not the gateway token) in `/sentinel/openclaw_hook_token`; create it once from the laptop:
    ```bash
    HOOK_TOKEN="$(openssl rand -hex 32)"
    aws ssm put-parameter --region us-east-1 --name /sentinel/openclaw_hook_token --type SecureString --value "$HOOK_TOKEN"
    unset HOOK_TOKEN
    ```
    On the instance, give the gateway the token through an environment file (`hooks.token` takes no SecretRef), then add the hooks config. The `${OPENCLAW_HOOKS_TOKEN}` reference syntax and the Telegram `to` format are not confirmed in the docs: check `openclaw config schema` first, and the manual test confirms delivery.
    ```bash
    aws ssm get-parameter --region us-east-1 --name /sentinel/openclaw_hook_token --with-decryption --query Parameter.Value --output text | sed 's/^/OPENCLAW_HOOKS_TOKEN=/' | install -m 600 /dev/stdin ~/.openclaw/credentials/hooks.env
    systemctl --user edit openclaw-gateway.service   # add: [Service] EnvironmentFile=%h/.openclaw/credentials/hooks.env
    openclaw config set hooks "{\"enabled\":true,\"token\":\"\${OPENCLAW_HOOKS_TOKEN}\",\"allowedAgentIds\":[\"main\"],\"mappings\":[{\"id\":\"watch\",\"match\":{\"path\":\"watch\"},\"action\":\"agent\",\"agentId\":\"main\",\"sessionMode\":\"isolated\",\"messageTemplate\":\"{{payload.message}}\",\"deliver\":true,\"channel\":\"telegram\",\"to\":\"$(aws ssm get-parameter --region us-east-1 --name /sentinel/telegram_user_id --with-decryption --query Parameter.Value --output text)\"}]}" --strict-json
    openclaw config validate && systemctl --user restart openclaw-gateway.service
    ```
    Then run the check every 15 minutes from the `ubuntu` user's crontab (`crontab -e`); stdout and errors both go to a small run log:
    ```
    */15 * * * * /home/ubuntu/sentinel/venv/bin/sentinel watch check >>/home/ubuntu/sentinel/watch-check.log 2>&1
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