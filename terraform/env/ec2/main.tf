# Get latest Ubuntu 22.04 LTS ARM64 AMI (free tier eligible with t4g)
data "aws_ami" "ubuntu_22_04" {
  most_recent = true
  owners      = ["099720109477"] # Canonical (Ubuntu)

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

resource "aws_instance" "sentinel_agent" {
  ami                  = data.aws_ami.ubuntu_22_04.id
  instance_type        = var.instance_type
  iam_instance_profile = var.iam_instance_profile_name
  user_data            = base64encode(local.user_data_script)

  tags = {
    Name = var.instance_name
  }
}

