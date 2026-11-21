resource "random_id" "bucket" { byte_length = 4 }
resource "random_password" "api_key" {
  length  = 32
  special = false
}
resource "aws_s3_bucket" "data" {
  bucket        = "${var.project}-${data.aws_caller_identity.current.account_id}-${random_id.bucket.hex}"
  force_destroy = var.allow_delete_demo_data
}
resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "expire-synthetic-readings"
    status = "Enabled"
    filter { prefix = "readings/" }
    expiration { days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_dynamodb_table" "alerts" {
  name         = "${var.project}-alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "work"
    type = "S"
  }
  attribute {
    name = "due_at"
    type = "N"
  }
  global_secondary_index {
    name            = "work-index"
    hash_key        = "work"
    range_key       = "due_at"
    projection_type = "ALL"
  }
  server_side_encryption { enabled = true }
}
resource "aws_db_subnet_group" "registry" {
  name       = "${var.project}-registry"
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_instance" "registry" {
  identifier                          = "${var.project}-registry"
  engine                              = "postgres"
  instance_class                      = "db.t4g.small"
  allocated_storage                   = 20
  storage_encrypted                   = true
  db_name                             = "registry"
  username                            = "registry_admin"
  manage_master_user_password         = true
  iam_database_authentication_enabled = true
  db_subnet_group_name                = aws_db_subnet_group.registry.name
  vpc_security_group_ids              = [aws_security_group.registry.id]
  publicly_accessible                 = false
  multi_az                            = false
  backup_retention_period             = 0
  skip_final_snapshot                 = true
  deletion_protection                 = false
}
resource "aws_secretsmanager_secret" "api_key" {
  name_prefix             = "${var.project}-api-key-"
  recovery_window_in_days = 0
}
resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = jsonencode({ api_key = random_password.api_key.result })
}
resource "aws_sqs_queue" "dead_letters" {
  name                      = "${var.project}-notifications-dlq"
  message_retention_seconds = 86400
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "notifications" {
  name                       = "${var.project}-notifications"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letters.arn
    maxReceiveCount     = 3
  })
}
resource "aws_sqs_queue_redrive_allow_policy" "dead_letters" {
  queue_url = aws_sqs_queue.dead_letters.url
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.notifications.arn]
  })
}
resource "aws_ecr_repository" "app" {
  name                 = "${var.project}-services"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_ecr_repository" "dispatcher" {
  name                 = "${var.project}-dispatcher"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_cloudwatch_log_group" "eks" {
  name              = "/s23/${var.project}/eks"
  retention_in_days = 3
}
resource "aws_cloudwatch_log_group" "analytics" {
  name              = "/s23/${var.project}/analytics"
  retention_in_days = 3
}
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project}-dispatcher"
  retention_in_days = 3
}
resource "aws_cloudwatch_log_group" "kafka" {
  name              = "/s23/${var.project}/kafka"
  retention_in_days = 3
}
resource "aws_cloudwatch_log_group" "control_plane" {
  name              = "/aws/eks/${var.project}/cluster"
  retention_in_days = 3
}
