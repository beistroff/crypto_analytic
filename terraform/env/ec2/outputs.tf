output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.sentinel_agent.id
}

output "instance_public_ip" {
  description = "Public IP of the EC2 instance"
  value       = aws_instance.sentinel_agent.public_ip
}

output "instance_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = aws_instance.sentinel_agent.private_ip
}

output "ami_id" {
  description = "AMI ID used for the instance"
  value       = aws_instance.sentinel_agent.ami
}

output "instance_type" {
  description = "EC2 instance type"
  value       = aws_instance.sentinel_agent.instance_type
}
