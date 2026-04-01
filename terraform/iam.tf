# IAM Role for EC2 instance
resource "aws_iam_role" "sentinel_role" {
  name = var.iam_role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = var.iam_role_name
  }
}

# Attach AWS managed policy for Systems Manager
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.sentinel_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Custom policy for DynamoDB and SSM Parameters
resource "aws_iam_role_policy" "sentinel_permissions" {
  name = "sentinel-permissions"
  role = aws_iam_role.sentinel_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBAccess"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Effect   = "Allow"
        Resource = aws_dynamodb_table.sentinel_state.arn
      },
      {
        Sid      = "SSMParameterAccess"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/sentinel/*"
      }
    ]
  })
}

# IAM instance profile
resource "aws_iam_instance_profile" "sentinel_profile" {
  name = "SentinelProfile"
  role = aws_iam_role.sentinel_role.name
}
