# Two tables, single-table style (PK + SK), item layouts in docs/IMPLEMENTATION_PLAN.md Appendix A.
#   real: real trades, positions, lessons, bids (protected from deletion)
#   sim:  snapshots, predictions, votes, alerts, reports (experiment data, TTL on snapshots)
#
# Cost: provisioned capacity stays inside the DynamoDB always-free tier (25 RCU / 25 WCU
# in total across tables and indexes). Encryption at rest uses the default AWS-owned key (free).

locals {
  provisioned = var.dynamodb_billing_mode == "PROVISIONED"
  read_cap    = local.provisioned ? var.read_capacity : null
  write_cap   = local.provisioned ? var.write_capacity : null
}

resource "aws_dynamodb_table" "real" {
  name           = var.real_table_name
  billing_mode   = var.dynamodb_billing_mode
  read_capacity  = local.read_cap
  write_capacity = local.write_cap
  hash_key       = "PK"
  range_key      = "SK"

  deletion_protection_enabled = true

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
    read_capacity   = local.read_cap
    write_capacity  = local.write_cap
  }

  tags = {
    Name = var.real_table_name
  }
}

resource "aws_dynamodb_table" "sim" {
  name           = var.sim_table_name
  billing_mode   = var.dynamodb_billing_mode
  read_capacity  = local.read_cap
  write_capacity = local.write_cap
  hash_key       = "PK"
  range_key      = "SK"

  deletion_protection_enabled = false

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # Sparse index: only open predictions carry GSI2PK = "OPEN", sorted by due time.
  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
    read_capacity   = local.read_cap
    write_capacity  = local.write_cap
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
    read_capacity   = local.read_cap
    write_capacity  = local.write_cap
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = var.sim_table_name
  }
}
