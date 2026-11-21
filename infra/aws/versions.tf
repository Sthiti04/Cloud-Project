terraform {
  required_version = ">= 1.8.0, < 2.0.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "6.25.0" }
    random = { source = "hashicorp/random", version = "3.7.2" }
    tls    = { source = "hashicorp/tls", version = "4.1.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project                                  = var.project
      Purpose                                  = "synthetic-student-demo"
      for-use-with-amazon-emr-managed-policies = "true"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

resource "terraform_data" "cost_guard" {
  lifecycle {
    precondition {
      condition     = var.allow_paid_resources
      error_message = "STOP: confirm your AWS budget first, then explicitly set allow_paid_resources=true."
    }
    precondition {
      condition = !var.enable_runtime || (
        startswith(var.lambda_image_uri, aws_ecr_repository.dispatcher.repository_url) &&
        can(regex("^@sha256:[a-f0-9]{64}$", trimprefix(var.lambda_image_uri, aws_ecr_repository.dispatcher.repository_url))) &&
        alltrue([for path in values(local.flink_artifacts) : fileexists(path)])
      )
      error_message = "Runtime needs all three built Flink JARs and this project's Lambda ECR URI with a full sha256 digest."
    }
  }
}
