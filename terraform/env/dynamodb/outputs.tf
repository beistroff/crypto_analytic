output "real_table_name" {
  description = "Name of the real-trades table"
  value       = aws_dynamodb_table.real.name
}

output "real_table_arn" {
  description = "ARN of the real-trades table"
  value       = aws_dynamodb_table.real.arn
}

output "sim_table_name" {
  description = "Name of the simulation table"
  value       = aws_dynamodb_table.sim.name
}

output "sim_table_arn" {
  description = "ARN of the simulation table"
  value       = aws_dynamodb_table.sim.arn
}
