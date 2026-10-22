# TOOLS.md - Local Notes

The tool list (`sentinel` commands and scripts) is in the Tools section of `AGENTS.md`, which is loaded every session.

- OpenClaw: 2026.10.3
- Workspace: `/home/ubuntu/.openclaw/workspace`
- `sentinel` package and repo clone: `/home/ubuntu/sentinel/` (`venv/` and `src/`)
- Trade journal: DynamoDB table `sentinel-real`, read and written only through `sentinel`; no portfolio files in the workspace. The nightly backup also writes it as JSON to `s3://openclaw-files/backups/<UTC stamp>/dynamodb/`.
