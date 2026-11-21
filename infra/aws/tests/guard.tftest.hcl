mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012", arn = "arn:aws:iam::123456789012:user/demo" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-south-1a", "ap-south-1b"] }
  }
  mock_resource "aws_eks_cluster" {
    defaults = {
      identity              = [{ oidc = [{ issuer = "https://example.invalid/oidc" }] }]
      certificate_authority = [{ data = "c3ludGhldGlj" }]
    }
  }
  mock_resource "aws_eks_node_group" {
    defaults = {
      resources = [{ autoscaling_groups = [{ name = "mock-workers" }] }]
    }
  }
  mock_resource "aws_launch_template" {
    defaults = { id = "lt-00000000000000000", latest_version = 1 }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:mock-registry-abcdef" }]
    }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock-role" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/mock/0000000000000000" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:targetgroup/mock/0000000000000000" }
  }
  mock_resource "aws_acm_certificate" {
    defaults = { arn = "arn:aws:acm:ap-south-1:123456789012:certificate/00000000-0000-0000-0000-000000000000" }
  }
  mock_resource "aws_msk_configuration" {
    defaults = { arn = "arn:aws:kafka:ap-south-1:123456789012:configuration/mock/00000000-0000-0000-0000-000000000000-2" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:ap-south-1:123456789012:mock-queue" }
  }
  mock_resource "aws_msk_cluster" {
    defaults = {
      arn = "arn:aws:kafka:ap-south-1:123456789012:cluster/demo/00000000-0000-0000-0000-000000000000-2"
    }
  }
  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/s23-demo-dispatcher"
    }
  }
}
mock_provider "tls" {
  mock_data "tls_certificate" {
    defaults = { certificates = [{ sha1_fingerprint = "0000000000000000000000000000000000000000" }] }
  }
}
mock_provider "random" {}

variables {
  admin_cidr          = "192.0.2.1/32"
  admin_principal_arn = "arn:aws:iam::123456789012:user/demo"
  enable_runtime      = false
}
run "refuses_unapproved_spend" {
  command         = plan
  expect_failures = [terraform_data.cost_guard]
}
run "plans_foundation_with_explicit_approval_and_mocked_aws" {
  command = plan
  variables { allow_paid_resources = true }
  assert {
    condition     = aws_eks_node_group.main.scaling_config[0].desired_size == 2
    error_message = "Keep two EKS nodes for the demo."
  }
  assert {
    condition     = length(aws_ebs_volume.zookeeper) == 3 && aws_msk_cluster.main.number_of_broker_nodes == 2
    error_message = "Expected three ZooKeeper volumes and two MSK brokers."
  }
  assert {
    condition     = length(aws_lambda_function.dispatcher) == 0 && length(aws_emr_cluster.analytics) == 0
    error_message = "The first apply must not create runtime services before artifacts and topics."
  }
  assert {
    condition     = !strcontains(aws_s3_object.emr_bootstrap.content, "\r")
    error_message = "The Linux EMR bootstrap uploaded to S3 must not contain Windows carriage returns."
  }
}
run "applies_mock_runtime_from_built_artifacts_without_real_aws" {
  command = apply
  variables {
    allow_paid_resources = true
    enable_runtime       = true
    lambda_image_uri     = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/s23-demo-dispatcher@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  }
  assert {
    condition     = length(aws_lambda_function.dispatcher) == 1 && length(aws_emr_cluster.analytics) == 1 && length(aws_s3_object.runtime) == 3
    error_message = "The second phase needs exactly one Lambda, one managed EMR cluster and all three JARs."
  }
  assert {
    condition = alltrue(flatten([
      for step in aws_emr_cluster.analytics[0].step : [
        for runner in step.hadoop_jar_step : [
          for argument in runner.args : !strcontains(argument, "\r")
        ]
      ]
    ]))
    error_message = "The managed Flink shell command must be Unix-safe even on a Windows workstation."
  }
}
