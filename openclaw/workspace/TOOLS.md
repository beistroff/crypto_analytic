# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### Crypto Sentinel (Portfolio)
- Table: `portfolio_info` (DynamoDB)
- Venv: `/home/ubuntu/sentinel/venv/bin/python3`
- Scripts: `/home/ubuntu/sentinel/scripts/`
- Local Data: `/home/ubuntu/sentinel/portfolio.json`

### Sentinel Aliases & Scripts
- **MSUR:** Runs `bash /home/ubuntu/sentinel/scripts/sys_report.sh` to get system stats.
- **S3 Backup:** Runs `bash /home/ubuntu/sentinel/scripts/s3_backup.sh` to back up the workspace and sentinel folders to `s3://openclaw-files/backups/`.
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

### System & Cron Notes
- **Cron Job Timeouts:** When running complex scheduled monitors (combining analysis + news fetching) under API rate limits or slow model responses (e.g. Free Tier), use `agents.defaults.timeoutSeconds` in the OpenClaw config set to `360` seconds to allow sufficient time for API processing.
