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
  description = "EC2 instance type (t2.micro is free tier eligible)"
  type        = string
  default     = "t2.micro"
}

variable "instance_name" {
  description = "Name tag for EC2 instance"
  type        = string
  default     = "sentinel-agent"
}

variable "ami_id" {
  description = "AMI ID (leave empty to use latest Amazon Linux 2023 x86_64 - free tier eligible)"
  type        = string
  default     = ""
}

variable "iam_instance_profile_name" {
  description = "IAM instance profile name (from iam output)"
  type        = string
}

variable "architecture" {
  description = "The CPU architecture (x86_64 or arm64)"
  type        = string
  default     = "x86_64" 
}