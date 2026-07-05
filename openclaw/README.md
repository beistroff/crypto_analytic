# OpenClaw Agent

This directory contains the core logic and foundational scripts for the `openclaw` agent, including tools for data analysis, system monitoring, and portfolio management.

**Note:** While this directory includes the agent's executable scripts, it does not contain the agent's full memory or context. Those dynamic files are generated during operation within the `/workspace` and are backed up separately to S3.

## Directory Structure

The agent's functionality is organized into the following subdirectories:

- **`/analysis`**: Contains scripts focused on market intelligence. These tools perform quantitative analysis, scalp candidate identification, and news aggregation to generate market signals.

- **`/monitoring`**: Holds scripts for actively tracking market conditions. This includes monitoring specific price thresholds or tracking the performance of an individual coin after a trade is made.

- **`/portfolio`**: Includes tools for managing the trade portfolio. This involves saving new trades and generating performance summaries (e.g., ROI, total value).

- **`/system_monitoring`**: Contains shell scripts for maintaining the agent's operational environment, such as performing backups to S3 and generating system resource reports.

- **`/utils`**: A collection of helper scripts and common utilities that are used by other parts of the agent, like quick price checks.

- **`/workspace`**: This is the agent's "mind." It contains foundational files like `AGENTS.md` and `SOUL.md` that define the agent's behavior. The files included in the repository serve as a powerful starting template, but users are encouraged to tune and customize them to fit their own needs and strategies.

- **`bootstrap.sh`**: A shell script used by Terraform's `user_data` to set up the agent on a new EC2 instance.

---

## OpenClaw Runtime Structure (`~/.openclaw`)

When the OpenClaw agent is installed, it creates a standard runtime directory in the user's home folder (`~/.openclaw`). This is where the agent's state, memory, and learned skills are stored. For more details, please refer to the official OpenClaw documentation.

A brief overview of the key directories:

- **`/workspace`**: The agent's active "mind." It contains the core personality files (`SOUL.md`, `IDENTITY.md`), operational guides (`AGENTS.md`), and memory files that the agent uses in every session. The contents of this project's `/workspace` are copied here to serve as a starting point.

- **`/workspace/memory`**: This is where the agent stores its long-term and short-term memories. It includes daily log files (`YYYY-MM-DD.md`) and curated, important recollections (`lessons_learned.md`).

- **`/skills`**: This directory holds reusable capabilities that the agent can learn and execute. Each skill is a self-contained module that extends the agent's abilities, allowing it to interact with new tools or APIs.

This separation ensures that the core logic (in this repository) is distinct from the agent's dynamic, operational state (in `~/.openclaw`).