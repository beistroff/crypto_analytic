terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment to use remote state storage (S3 + DynamoDB)
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "crypto-sentinel/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}
