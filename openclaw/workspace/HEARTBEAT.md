# Active Scheduled Tasks

- [x] Daily Health Check: `0 0 * * *` (UTC)
- [x] Daily Portfolio Backup: `0 1 * * *` (UTC) [System Crontab]
- [ ] NVIDIA / AI Sector Monitor: `0 17 * * *` (UTC)

---
# HEARTBEAT.md Template

```markdown
# Add tasks below when you want the agent to check something periodically.

- [ ] Run health check: `/usr/bin/python3 /home/ubuntu/sentinel/scripts/health_monitor.py`. (Run once daily).
- [ ] Backup portfolio: `aws s3 cp /home/ubuntu/sentinel/portfolio.json s3://openclaw-files/workspace/portfolio.json`. (Run once daily).
- [ ] Monitor price thresholds: `/usr/bin/python3 /home/ubuntu/sentinel/scripts/threshold_monitor.py 4eb5418e56cc44d9bb7a104f0cec7dc1`. (Run only at 09:00 and 19:20 UTC).
```
