variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

/*
  Best Practice (Tagging Strategy):
  This variable, along with `environment`, should be used to consistently tag all resources.
  Proper tagging is crucial for cost allocation, automation, and access control.
*/
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

/*
  Future Improvement (AMI Management):
  For production environments, it's a best practice to pin to a specific AMI ID instead of using a dynamic lookup for the latest one.
  This ensures that deployments are repeatable and not affected by upstream AMI updates.
*/
variable "ami_id" {
  description = "AMI ID (leave empty to use latest Amazon Linux 2023 x86_64 - free tier eligible)"
  type        = string
  default     = ""
}

/*
  Future Improvement (Dependency Management):
  Instead of passing the IAM profile name as a string, this could be sourced directly from the `iam` module's output
  using a `terraform_remote_state` data source. This creates an explicit dependency and avoids using "magic strings".
*/
variable "iam_instance_profile_name" {
  description = "IAM instance profile name (from iam output)"
  type        = string
}

variable "architecture" {
  description = "The CPU architecture (x86_64 or arm64)"
  type        = string
  default     = "x86_64" 
}
