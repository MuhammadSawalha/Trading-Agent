terraform {
  backend "s3" {
    bucket         = "stock-research-terraform-state-228281126655"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "stock-research-terraform-locks-228281126655"
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "us-east-1"
}
