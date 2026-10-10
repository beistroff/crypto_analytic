# The instance type decides the CPU architecture, and the architecture decides the AMI,
# so moving to another free-tier type (arm64 or x86_64) needs no code change.
data "aws_ec2_instance_type" "selected" {
  instance_type = var.instance_type
}

locals {
  is_arm  = contains(data.aws_ec2_instance_type.selected.supported_architectures, "arm64")
  ami_arc = local.is_arm ? "arm64" : "amd64"
}

# Latest Ubuntu 24.04 LTS (noble) AMI from Canonical for that architecture
data "aws_ami" "ubuntu_24_04" {
  most_recent = true
  owners      = ["099720109477"] # Canonical (Ubuntu)

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-${local.ami_arc}-server-*"]
  }

  filter {
    name   = "architecture"
    values = [local.is_arm ? "arm64" : "x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

data "aws_vpc" "default" {
  default = true
}

locals {
  ami_id = var.ami_id != "" ? var.ami_id : data.aws_ami.ubuntu_24_04.id
}

# No ingress rules at all: access is through SSM Session Manager (outbound HTTPS only).
# DNS (VPC resolver) and time sync (Amazon Time Sync) are link-local and are not filtered
# by security groups, so they need no rules here.
resource "aws_security_group" "sentinel_sg" {
  name        = "${var.instance_name}-sg"
  description = "Security group for Sentinel EC2 instance (outbound only)"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS for APIs, SSM, and secure web"
  }

  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP for apt mirrors"
  }

  tags = {
    Name = "${var.instance_name}-sg"
  }
}

resource "aws_instance" "sentinel_agent" {
  ami                         = local.ami_id
  instance_type               = var.instance_type
  iam_instance_profile        = var.iam_instance_profile_name
  user_data                   = local.user_data_script
  user_data_replace_on_change = true
  vpc_security_group_ids      = [aws_security_group.sentinel_sg.id]

  # Needed for outbound access in the default VPC (no NAT gateway).
  associate_public_ip_address = true

  # Enforce IMDSv2; hop limit 1 keeps containers on the host from reaching the role credentials.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = var.instance_name
  }
}
