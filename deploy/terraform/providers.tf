# NOTE: Using local backend. For production use, configure an S3 backend
# with DynamoDB locking. See: https://developer.hashicorp.com/terraform/language/backend/s3

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
