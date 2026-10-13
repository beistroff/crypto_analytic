/*
  Restoring Agent State from S3:
  The EC2 instance has an IAM role with permissions to access the S3 bucket for backups.
  To restore the latest state of the openclaw agent with all its previous context, scripts, and experience,
  you can use a prompt similar to this:

  "Please check the latest backup in S3. This is your agent file backup for your crypto mindset, including experience and lessons learned.
  Load it into your context in the default place where you save these things. Install any required skills and ask clarifying questions if you need help with the restore."
*/

/*
  user_data is bootstrap.sh verbatim, preceded by a few exported settings.
  bootstrap.sh is plain bash (no templating), so it can be linted with shellcheck and
  contains no application code: the sentinel package is deployed separately.
*/
locals {
  user_data_script = join("\n", [
    "#!/bin/bash",
    "export OPENCLAW_VERSION='${var.openclaw_version}'",
    "export OPENCLAW_S3_BUCKET='${var.backup_bucket_name}'",
    "export AWS_REGION='${var.aws_region}'",
    replace(file("${path.module}/../../../openclaw/bootstrap.sh"), "\r\n", "\n"),
  ])
}
