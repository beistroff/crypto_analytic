terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Intentionally a local backend: this env creates the bucket that every other
  # env uses for remote state. Its own (tiny) state file stays on your machine.
}
