# Terraform Infrastructure

This directory contains Terraform configurations for the stock-research system.

## Bootstrap: Terraform State Backend

The Terraform state for all environments is stored in S3. The S3 bucket (`stock-research-terraform-state`) and its associated DynamoDB lock table must be created once, manually, as a bootstrap step before running any Terraform commands.

This is a one-time, manual exception to the "all AWS resources provisioned via Terraform" constraint, because Terraform cannot create the backend it stores its own state in without a chicken-and-egg problem.

### Bootstrap Steps (one-time only)

1. Create the S3 bucket:
   ```bash
   aws s3api create-bucket \
     --bucket stock-research-terraform-state \
     --region us-east-1
   ```

2. Enable versioning on the bucket:
   ```bash
   aws s3api put-bucket-versioning \
     --bucket stock-research-terraform-state \
     --versioning-configuration Status=Enabled
   ```

3. Block public access to the bucket:
   ```bash
   aws s3api put-public-access-block \
     --bucket stock-research-terraform-state \
     --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

4. Create the DynamoDB lock table:
   ```bash
   aws dynamodb create-table \
     --table-name stock-research-terraform-locks \
     --attribute-definitions AttributeName=LockID,AttributeType=S \
     --key-schema AttributeName=LockID,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST \
     --region us-east-1
   ```

After these bootstrap steps, all subsequent Terraform deployments use the S3 backend defined in each environment's `backend.tf`.

## Directory Structure

- `modules/`: Reusable Terraform modules
  - `network/`: VPC, subnets, and routing configuration
- `envs/`: Environment-specific configurations
  - `dev/`: Development environment
  - `prod/`: Production environment
