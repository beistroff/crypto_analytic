# OpenClaw Agent

This directory holds the agent's OpenClaw side: its workspace (persona, rules, memory templates) and the instance bootstrap. The data tools the agent calls are the `sentinel` package at the repo root (`sentinel --help`); operational shell scripts are in `ops/`; the old standalone scripts are kept unchanged in `legacy/` until their replacements are proven.

**Note:** This directory does not contain the agent's full memory or context. Those dynamic files are generated during operation within the `/workspace` and are backed up separately to S3 (`ops/s3_backup.sh`).

## Directory Structure

- **`/workspace`**: This is the agent's "mind." It contains foundational files like `AGENTS.md` and `SOUL.md` that define the agent's behavior. The files included in the repository serve as a powerful starting template, but users are encouraged to tune and customize them to fit their own needs and strategies.

- **`bootstrap.sh`**: run by Terraform's `user_data` on a new EC2 instance: OS packages, the `sentinel` package at `sentinel_ref`, the readiness gate (`sentinel health`), then OpenClaw.

---

## OpenClaw Runtime Structure (`~/.openclaw`)

When the OpenClaw agent is installed, it creates a standard runtime directory in the user's home folder (`~/.openclaw`). This is where the agent's state, memory, and learned skills are stored. For more details, please refer to the official OpenClaw documentation.

A brief overview of the key directories:

- **`/workspace`**: The agent's active "mind." It contains the core personality files (`SOUL.md`, `IDENTITY.md`), operational guides (`AGENTS.md`), and memory files that the agent uses in every session. The contents of this project's `/workspace` are copied here to serve as a starting point.

- **`/workspace/memory`**: This is where the agent stores its long-term and short-term memories. It includes daily log files (`YYYY-MM-DD.md`) and curated, important recollections (`lessons_learned.md`).

- **`/skills`**: This directory holds reusable capabilities that the agent can learn and execute. Each skill is a self-contained module that extends the agent's abilities, allowing it to interact with new tools or APIs.

This separation ensures that the core logic (in this repository) is distinct from the agent's dynamic, operational state (in `~/.openclaw`).