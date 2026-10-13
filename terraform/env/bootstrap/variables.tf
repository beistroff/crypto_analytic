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

variable "state_bucket_name" {
  description = "State bucket name. Must match the bucket in the backend blocks of the other envs (S3 names are global, hence the random suffix)."
  type        = string
  default     = "sentinel-tfstate-6c1ff0ad"
}

variable "noncurrent_version_expiration_days" {
  description = "Days to keep old state versions"
  type        = number
  default     = 90
}
