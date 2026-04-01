resource "aws_instance" "sentinel_agent" {
  ami                    = var.ami_id != "" ? var.ami_id : data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.sentinel_profile.name
  user_data              = base64encode(local.user_data_script)

  tags = {
    Name = var.instance_name
  }

  depends_on = [
    aws_iam_role_policy.sentinel_permissions
  ]
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
