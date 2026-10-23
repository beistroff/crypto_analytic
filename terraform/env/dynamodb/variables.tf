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

variable "real_table_name" {
  description = "Table for real trades, positions, lessons and bids"
  type        = string
  default     = "sentinel-real"
}

variable "sim_table_name" {
  description = "Table for snapshots, predictions, votes, alerts and reports"
  type        = string
  default     = "sentinel-sim"
}

variable "dynamodb_billing_mode" {
  description = "PROVISIONED stays inside the always-free tier; PAY_PER_REQUEST bills per request from the first one"
  type        = string
  default     = "PROVISIONED"

  validation {
    condition     = contains(["PROVISIONED", "PAY_PER_REQUEST"], var.dynamodb_billing_mode)
    error_message = "dynamodb_billing_mode must be PROVISIONED or PAY_PER_REQUEST."
  }
}

variable "read_capacity" {
  description = "RCU per table and per index (PROVISIONED only). 5 resources x 2 = 10 of the 25 free units."
  type        = number
  default     = 2
}

variable "write_capacity" {
  description = "WCU per table and per index (PROVISIONED only). 5 resources x 2 = 10 of the 25 free units."
  type        = number
  default     = 2
}
