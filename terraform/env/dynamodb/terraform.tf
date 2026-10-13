terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state in S3 with native lock files (no DynamoDB lock table needed).
  # The bucket is created by env/bootstrap; bucket names are not secret, access is via IAM.
  backend "s3" {
    bucket       = "sentinel-tfstate-6c1ff0ad"
    region       = "us-east-1"
    key          = "crypto-sentinel/dynamodb/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
