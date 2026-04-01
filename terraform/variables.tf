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

# --- DynamoDB Configuration ---
variable "dynamodb_table_name" {
  description = "DynamoDB table name for state storage"
  type        = string
  default     = "CryptoSentinel_State"
}

variable "dynamodb_billing_mode" {
  description = "DynamoDB billing mode (PAY_PER_REQUEST or PROVISIONED)"
  type        = string
  default     = "PAY_PER_REQUEST"
}

# --- IAM Configuration ---
variable "iam_role_name" {
  description = "IAM role name for Sentinel"
  type        = string
  default     = "CryptoSentinelRole"
}

# --- EC2 Configuration ---
variable "instance_type" {
  description = "EC2 instance type (t2.micro is free tier eligible)"
  type        = string
  default     = "t2.micro"
}

variable "instance_name" {
  description = "Name tag for EC2 instance"
  type        = string
  default     = "sentinel-agent"
}

# Get latest Amazon Linux 2023 x86_64 AMI (free tier eligible)
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

variable "ami_id" {
  description = "AMI ID (leave empty to use latest Amazon Linux 2023 x86_64 - free tier eligible)"
  type        = string
  default     = ""
}
