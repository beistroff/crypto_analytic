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
          "dynamodb:DeleteItem",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Effect   = "Allow"
        Resource = var.dynamodb_table_arn
      },
      {
        Sid      = "SSMParameterAccess"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/sentinel/*"
      },
      {
        Sid      = "S3BucketAccess"
        Action   = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Effect   = "Allow"
        Resource = ["arn:aws:s3:::*", "arn:aws:s3:::*/*"]
      }
    ]
  })
}

# IAM instance profile
resource "aws_iam_instance_profile" "sentinel_profile" {
  name = var.instance_profile_name
  role = aws_iam_role.sentinel_role.name
}
