resource "aws_iam_role" "node_role" {
  name = "stock-research-${var.env}-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "app_access" {
  name = "stock-research-${var.env}-app-access"
  role = aws_iam_role.node_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BedrockInvoke"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0"
      },
      {
        Sid      = "DynamoDBAccess"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
        Resource = var.dynamodb_table_arns
      },
      {
        Sid      = "S3ToolPayloadAccess"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "node_profile" {
  name = "stock-research-${var.env}-node-profile"
  role = aws_iam_role.node_role.name
}
