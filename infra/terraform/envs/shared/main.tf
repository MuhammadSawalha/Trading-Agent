# Account-level resources shared by both dev and prod: CI builds each service image once
# per commit and the same image (by tag) is later promoted from dev to prod (see
# promote-prod.yml), so ECR repos live outside the per-env `dev`/`prod` state entirely
# rather than being duplicated per environment.

variable "github_repo" {
  type    = string
  default = "MuhammadSawalha/Trading-Agent"
}

locals {
  services = [
    "mcp-server",
    "scheduler",
    "api-backend",
    "frontend",
    "stock-scanner-mcp",
    "tradingview-mcp",
  ]
}

resource "aws_ecr_repository" "service" {
  for_each             = toset(local.services)
  name                 = each.value
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    }]
  })
}

# GitHub Actions OIDC: lets deploy-dev.yml / pr-checks.yml assume an AWS role with
# short-lived, keyless credentials instead of long-lived AWS_ACCESS_KEY_ID secrets.
# The GitHub Actions OIDC provider is an AWS-account-wide singleton (AWS rejects a second
# provider for the same URL) and this AWS account is shared with other projects/students'
# CI roles that already trust it -- so it's looked up read-only here, never created or
# destroyed by this config, to avoid taking Terraform ownership of a resource other
# pipelines depend on.
data "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "ci" {
  name = "stock-research-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github_actions.arn }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_ecr" {
  name = "stock-research-ci-ecr"
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPushPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = [for r in aws_ecr_repository.service : r.arn]
      },
    ]
  })
}

output "repository_urls" {
  value = { for k, r in aws_ecr_repository.service : k => r.repository_url }
}

output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}
