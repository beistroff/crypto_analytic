# Get latest Amazon Linux 2023 arm64 AMI (free tier eligible)
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-${var.architecture}"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

resource "aws_instance" "sentinel_agent" {
  ami                  = var.ami_id != "" ? var.ami_id : data.aws_ami.amazon_linux_2023.id
  instance_type        = var.instance_type
  iam_instance_profile = var.iam_instance_profile_name
  user_data            = base64encode(local.user_data_script)

  tags = {
    Name = var.instance_name
  }
}

locals {
  user_data_script = <<-EOF
              #!/bin/bash
              set -e

              # Update system
              dnf update -y

              # Install dependencies
              dnf install -y nodejs npm git jq aws-cli

              # Create 2GB swap for stability
              dd if=/dev/zero of=/swapfile bs=1M count=2048
              chmod 600 /swapfile
              mkswap /swapfile
              swapon /swapfile
              echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

              # Install global CLI tool
              npm install -g @openclaw/cli
              EOF
}
