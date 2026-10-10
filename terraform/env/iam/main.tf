data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  dynamodb_table_arns = [
    for name in [var.real_table_name, var.sim_table_name] :
    "arn:aws:dynamodb:${var.aws_region}:${local.account_id}:table/${name}"
  ]

  # Query on a global secondary index is authorised on the index ARN, not the table ARN.
  dynamodb_resources = concat(local.dynamodb_table_arns, [for arn in local.dynamodb_table_arns : "${arn}/index/*"])
}

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

# Session Manager access (no SSH, no inbound ports)
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.sentinel_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least-privilege permissions for the agent (checked against the calls the code makes):
#   - DynamoDB: only the two tables and their indexes; no Scan (reads are Queries by key).
#     TransactWriteItems is authorised through the item-level actions plus ConditionCheckItem.
#   - SSM: GetParameter(s) on /sentinel/* only (secrets read at start, decrypted with the
#     default aws/ssm key, which needs no extra KMS statement).
#   - S3: read/write on the backup bucket; delete only under strategy-share/ because
#     `aws s3 sync --delete` prunes that prefix. Backups can therefore not be deleted by the role.
# Note: OpenClaw runs shell commands, so anything it ingests (news, web pages) could try to
# steer it. Mitigations: deletion protection on sentinel-real, nightly JSON export to S3,
# no IAM/EC2 permissions on this role, and (manually) versioning on the backup bucket.
resource "aws_iam_role_policy" "sentinel_permissions" {
  name = "sentinel-permissions"
  role = aws_iam_role.sentinel_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "DynamoDBAccess"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:ConditionCheckItem",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:DescribeTable"
        ]
        Effect   = "Allow"
        Resource = local.dynamodb_resources
      },
      {
        Sid      = "SSMParameterRead"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter/sentinel/*"
      },
      {
        Sid      = "S3ListBackupBucket"
        Action   = "s3:ListBucket"
        Effect   = "Allow"
        Resource = "arn:aws:s3:::${var.backup_bucket_name}"
      },
      {
        Sid      = "S3ReadWriteObjects"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Effect   = "Allow"
        Resource = "arn:aws:s3:::${var.backup_bucket_name}/*"
      },
      {
        Sid      = "S3DeleteSharedStrategyOnly"
        Action   = "s3:DeleteObject"
        Effect   = "Allow"
        Resource = "arn:aws:s3:::${var.backup_bucket_name}/strategy-share/*"
      }
    ]
  })
}

# IAM instance profile
resource "aws_iam_instance_profile" "sentinel_profile" {
  name = var.instance_profile_name
  role = aws_iam_role.sentinel_role.name
}
