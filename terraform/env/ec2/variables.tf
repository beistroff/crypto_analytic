variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for tagging"
  type        = string
  default     = "CryptoSentinel"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "instance_type" {
  description = "EC2 instance type, arm64 or x86_64. The AMI architecture follows from it."
  type        = string
  default     = "t4g.small"
}

variable "instance_name" {
  description = "Name tag for EC2 instance"
  type        = string
  default     = "sentinel-agent"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB (gp3, encrypted)"
  type        = number
  default     = 20
}

# Pin the AMI for repeatable deployments once a known-good one is chosen.
variable "ami_id" {
  description = "AMI ID matching the instance architecture. Leave empty to use the latest Ubuntu 24.04 AMI."
  type        = string
  default     = ""
}

variable "iam_instance_profile_name" {
  description = "IAM instance profile name (from iam output)"
  type        = string
}

variable "openclaw_version" {
  description = "OpenClaw version for the installer (--version): an exact version such as 2026.5.1, or latest/next. Pin an exact version after the first bring-up."
  type        = string
  default     = "latest"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.openclaw_version))
    error_message = "openclaw_version may only contain letters, digits, dots, dashes and underscores."
  }
}

variable "backup_bucket_name" {
  description = "S3 bucket for agent backups (exported to the instance as OPENCLAW_S3_BUCKET)"
  type        = string
  default     = "openclaw-files"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.backup_bucket_name))
    error_message = "backup_bucket_name must be a valid S3 bucket name."
  }
}

variable "sentinel_ref" {
  description = "Git tag (or branch) of this repo that bootstrap deploys as the sentinel package. Use a release tag such as v0.1.0."
  type        = string
  default     = "main"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]*$", var.sentinel_ref))
    error_message = "sentinel_ref may only contain letters, digits, dots, dashes, underscores and slashes."
  }
}

check "sentinel_ref_pinned" {
  assert {
    condition     = can(regex("^v[0-9]", var.sentinel_ref))
    error_message = "sentinel_ref is a branch, not a release tag. Tag a tested commit (e.g. v0.1.0) and set it in terraform.tfvars."
  }
}

check "openclaw_version_pinned" {
  assert {
    condition     = !contains(["latest", "next"], var.openclaw_version)
    error_message = "openclaw_version is not pinned. Record the installed version after the first bring-up and set it in terraform.tfvars."
  }
}
