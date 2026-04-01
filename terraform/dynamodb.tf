resource "aws_dynamodb_table" "sentinel_state" {
  name         = var.dynamodb_table_name
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "PK"

  attribute {
    name = "PK"
    type = "S"
  }

  tags = {
    Name = var.dynamodb_table_name
  }
}
