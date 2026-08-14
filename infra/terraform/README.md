# Terraform Infrastructure

This directory contains Terraform configurations for the stock-research system.

## Bootstrap: Terraform State Backend

The Terraform state for all environments is stored in S3. The S3 bucket (`stock-research-terraform-state-228281126655`) and its associated DynamoDB lock table must be created once, manually, as a bootstrap step before running any Terraform commands.

This is a one-time, manual exception to the "all AWS resources provisioned via Terraform" constraint, because Terraform cannot create the backend it stores its own state in without a chicken-and-egg problem.

Note: S3 bucket names are globally unique across *all* AWS accounts, not just this one — the bucket and table names below are suffixed with this project's AWS account ID (`228281126655`) to guarantee they don't collide with another account's bucket of the same name (as `stock-research-terraform-state` without a suffix already did). If you fork this into a different AWS account, replace the suffix with that account's ID throughout this file and in `envs/{dev,prod}/backend.tf` and `modules/s3/main.tf`.

### Bootstrap Steps (one-time only)

1. Create the S3 bucket:
   ```bash
   aws s3api create-bucket \
     --bucket stock-research-terraform-state-228281126655 \
     --region us-east-1
   ```

2. Enable versioning on the bucket:
   ```bash
   aws s3api put-bucket-versioning \
     --bucket stock-research-terraform-state-228281126655 \
     --versioning-configuration Status=Enabled
   ```

3. Block public access to the bucket:
   ```bash
   aws s3api put-public-access-block \
     --bucket stock-research-terraform-state-228281126655 \
     --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

4. Create the DynamoDB lock table:
   ```bash
   aws dynamodb create-table \
     --table-name stock-research-terraform-locks-228281126655 \
     --attribute-definitions AttributeName=LockID,AttributeType=S \
     --key-schema AttributeName=LockID,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST \
     --region us-east-1
   ```

After these bootstrap steps, all subsequent Terraform deployments use the S3 backend defined in each environment's `backend.tf`.

## Directory Structure

- `modules/`: Reusable Terraform modules
  - `network/`: VPC, subnets, and routing configuration
  - `iam/`: EC2 instance-profile role and app-access policy
  - `dynamodb/`: ToolResults, AgentOutputs, and ProcessHistory tables
  - `s3/`: Oversized tool-payload storage bucket
  - `cluster/`: EC2 k3s bootstrap (control plane + ELB)
- `envs/`: Environment-specific configurations
  - `dev/`: Development environment
  - `prod/`: Production environment
