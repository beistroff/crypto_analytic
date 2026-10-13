output "state_bucket_name" {
  description = "Name of the Terraform state bucket (must match the backend blocks in the other envs)"
  value       = aws_s3_bucket.tfstate.id
}
