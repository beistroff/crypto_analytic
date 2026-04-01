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

variable "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table (from dynamodb output)"
  type        = string
}
