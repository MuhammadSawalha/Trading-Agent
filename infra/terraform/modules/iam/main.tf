data "aws_caller_identity" "current" {}

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
        # us.anthropic.claude-haiku-4-5 is only invokable in Bedrock through a cross-region
        # inference profile, not directly by its plain foundation-model ARN -- Bedrock checks
        # permissions on both the inference-profile ARN invoked AND the underlying regional
        # foundation-model ARN(s) that profile fans out to (us-east-1/us-east-2/us-west-2 for
        # a "us." profile), so both must be granted or InvokeModel is denied even though the
        # profile ARN alone looks like the resource being called.
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        ]
      },
      {
        Sid      = "DynamoDBAccess"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Scan", "dynamodb:BatchWriteItem"]
        Resource = var.dynamodb_table_arns
      },
      {
        Sid      = "S3ToolPayloadAccess"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      {
        # Nodes pull every service image from ECR at container start, and the in-cluster
        # ecr-cred-refresher CronJob (infra/k8s/ecr-cred-refresher) mints the imagePullSecret
        # that makes that possible -- both run as this same node role via IMDS, since k3s has
        # no IRSA-equivalent outside EKS. GetAuthorizationToken must be Resource "*" (AWS
        # rejects it scoped to a repository ARN); the pull actions are scoped to this
        # project's own repos.
        Sid      = "EcrPull"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPullRepos"
        Effect = "Allow"
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = [
          for svc in ["mcp-server", "scheduler", "api-backend", "frontend", "stock-scanner-mcp", "tradingview-mcp"] :
          "arn:aws:ecr:us-east-1:${data.aws_caller_identity.current.account_id}:repository/${svc}"
        ]
      },
    ]
  })
}

resource "aws_iam_instance_profile" "node_profile" {
  name = "stock-research-${var.env}-node-profile"
  role = aws_iam_role.node_role.name
}
