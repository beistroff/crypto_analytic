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

variable "iam_role_name" {
  description = "IAM role name for Sentinel"
  type        = string
  default     = "CryptoSentinelRole"
}

variable "instance_profile_name" {
  description = "IAM instance profile name"
  type        = string
  default     = "SentinelProfile"
}

# Defaults match terraform/env/dynamodb. ARNs are built from these names, so there is
# no manual copy of ARNs between envs.
variable "real_table_name" {
  description = "Name of the real-trades DynamoDB table"
  type        = string
  default     = "sentinel-real"
}

variable "sim_table_name" {
  description = "Name of the simulation DynamoDB table"
  type        = string
  default     = "sentinel-sim"
}

variable "backup_bucket_name" {
  description = "S3 bucket holding agent backups and shareable strategy files"
  type        = string
  default     = "openclaw-files"
}
