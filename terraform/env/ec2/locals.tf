/*
  Restoring Agent State from S3:
  The EC2 instance has an IAM role with permissions to access the S3 bucket for backups.
  To restore the latest state of the openclaw agent with all its previous context, scripts, and experience,
  you can use a prompt similar to this:

  "Please check the latest backup in S3. This is your agent file backup for your crypto mindset, including experience and lessons learned.
  Load it into your context in the default place where you save these things. Install any required skills and ask clarifying questions if you need help with the restore."
*/

/*
  Future Improvement (Configuration Management):
  The current bootstrapping process relies on a bash script (`bootstrap.sh`).
  For more robust, scalable, and idempotent server configuration, this should ideally be replaced with a configuration management tool like Ansible.
*/
locals {
  user_data_script = templatefile("${path.module}/../../../openclaw/bootstrap.sh", {
    market_intelligence = file("${path.module}/../../../openclaw/market_intelligence.py")
    sentinel_memory     = file("${path.module}/../../../openclaw/sentinel_memory.py")
    s3_bucket_name      = "openclaw-files" # Or use a variable: var.s3_bucket_name
  })
}
