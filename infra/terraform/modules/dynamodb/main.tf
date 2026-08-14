resource "aws_dynamodb_table" "tool_results" {
  name         = "ToolResults-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "agent_outputs" {
  name         = "AgentOutputs-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  range_key    = "agent_name"
  attribute {
    name = "symbol"
    type = "S"
  }
  attribute {
    name = "agent_name"
    type = "S"
  }
}

resource "aws_dynamodb_table" "process_history" {
  name         = "ProcessHistory-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  range_key    = "sk"
  attribute {
    name = "symbol"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
}
