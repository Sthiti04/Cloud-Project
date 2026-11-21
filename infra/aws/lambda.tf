locals {
  runtime_environment = {
    APP_MODE            = "aws"
    AWS_REGION          = var.region
    KAFKA_BROKERS       = aws_msk_cluster.main.bootstrap_brokers_sasl_iam
    ALERT_TABLE         = aws_dynamodb_table.alerts.name
    SQS_QUEUE_URL       = aws_sqs_queue.notifications.url
    ARCHIVE_BUCKET      = aws_s3_bucket.data.id
    ZOOKEEPER_HOSTS     = "zookeeper-0.zookeeper.s23.svc.cluster.local:2181,zookeeper-1.zookeeper.s23.svc.cluster.local:2181,zookeeper-2.zookeeper.s23.svc.cluster.local:2181"
    API_SECRET_ARN      = aws_secretsmanager_secret.api_key.arn
    DB_HOST             = aws_db_instance.registry.address
    DB_NAME             = "registry"
    DB_USER             = "s23_registry"
    DB_SECRET_ARN       = aws_db_instance.registry.master_user_secret[0].secret_arn
    REGISTRY_GRPC       = "dns:///device-registry-grpc.s23.svc.cluster.local:50051"
    ACK_TIMEOUT_MS      = "120000"
    DISPATCH_LEASE_MS   = "120000"
    MAX_DISPATCHES      = "5"
    FAIL_FIRST_DELIVERY = tostring(var.fail_first_delivery)
  }
}
resource "aws_lambda_function" "dispatcher" {
  count         = var.enable_runtime ? 1 : 0
  function_name = "${var.project}-dispatcher"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.lambda_image_uri
  architectures = ["x86_64"]
  memory_size   = 256
  timeout       = 10
  environment {
    variables = merge(
      { for key, value in local.runtime_environment : key => value if key != "AWS_REGION" },
      { SERVICE = "notification-dispatcher" },
    )
  }
  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
}
resource "aws_lambda_event_source_mapping" "notifications" {
  count                   = var.enable_runtime ? 1 : 0
  event_source_arn        = aws_sqs_queue.notifications.arn
  function_name           = aws_lambda_function.dispatcher[0].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
}
