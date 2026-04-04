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

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "sentinel_sg" {
  name        = "${var.instance_name}-sg"
  description = "Security group for Sentinel EC2 instance (Outbound only)"
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
    description = "HTTP for apt updates and general web"
  }

  egress {
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "DNS Resolution (UDP)"
  }

  egress {
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "DNS Resolution (TCP)"
  }

  egress {
    from_port   = 123
    to_port     = 123
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "NTP for clock synchronization"
  }

  tags = {
    Name = "${var.instance_name}-sg"
  }
}

resource "aws_instance" "sentinel_agent" {
  ami                  = data.aws_ami.ubuntu_22_04.id
  instance_type        = var.instance_type
  iam_instance_profile = var.iam_instance_profile_name
  user_data            = local.user_data_script
  vpc_security_group_ids = [aws_security_group.sentinel_sg.id]

  tags = {
    Name = var.instance_name
  }
}
