locals {
  oidc_host        = replace(aws_iam_openid_connect_provider.eks.url, "https://", "")
  kafka_cluster    = aws_msk_cluster.main.arn
  kafka_topics     = "${replace(aws_msk_cluster.main.arn, ":cluster/", ":topic/")}/*"
  kafka_groups     = "${replace(aws_msk_cluster.main.arn, ":cluster/", ":group/")}/*"
  kafka_connect    = { Effect = "Allow", Action = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"], Resource = [local.kafka_cluster] }
  kafka_idempotent = { Effect = "Allow", Action = ["kafka-cluster:WriteDataIdempotently"], Resource = [local.kafka_cluster] }
  kafka_read       = { Effect = "Allow", Action = ["kafka-cluster:ReadData", "kafka-cluster:DescribeTopic"], Resource = [local.kafka_topics] }
  kafka_write      = { Effect = "Allow", Action = ["kafka-cluster:WriteData", "kafka-cluster:DescribeTopic"], Resource = [local.kafka_topics] }
  kafka_consumer   = { Effect = "Allow", Action = ["kafka-cluster:DescribeGroup", "kafka-cluster:AlterGroup"], Resource = [local.kafka_groups] }
  dynamo = {
    Effect   = "Allow"
    Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:ConditionCheckItem"]
    Resource = [aws_dynamodb_table.alerts.arn, "${aws_dynamodb_table.alerts.arn}/index/*"]
  }
  api_secret = { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.api_key.arn] }
  service_accounts = {
    patient-simulator       = "s23:patient-simulator"
    vital-ingestion         = "s23:vital-ingestion"
    device-registry         = "s23:device-registry"
    alert-rule-engine       = "s23:alert-rule-engine"
    alert-queue-manager     = "s23:alert-queue-manager"
    acknowledgement-service = "s23:acknowledgement-service"
    schema-init             = "s23:schema-init"
    topic-bootstrap         = "s23:topic-bootstrap"
    load-test               = "s23:load-test"
    fluent-bit              = "observability:fluent-bit"
    prometheus              = "observability:prometheus"
    cloudwatch-exporter     = "observability:cloudwatch-exporter"
    vpc-cni                 = "kube-system:aws-node"
    ebs-csi                 = "kube-system:ebs-csi-controller-sa"
  }
  permissions = {
    patient-simulator = [local.api_secret]
    load-test         = [local.api_secret]
    vital-ingestion = [
      local.api_secret, local.kafka_connect, local.kafka_idempotent, local.kafka_write,
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = ["${aws_s3_bucket.data.arn}/readings/*"] },
    ]
    device-registry = [{
      Effect   = "Allow", Action = ["rds-db:connect"],
      Resource = ["arn:aws:rds-db:${var.region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.registry.resource_id}/s23_registry"],
    }]
    alert-rule-engine = [local.kafka_connect, local.kafka_read, local.kafka_consumer]
    alert-queue-manager = [
      local.dynamo, local.kafka_connect, local.kafka_idempotent, local.kafka_write,
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [aws_sqs_queue.notifications.arn] },
    ]
    acknowledgement-service = [local.dynamo, local.kafka_connect, local.kafka_read, local.kafka_consumer]
    schema-init = [{
      Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"],
      Resource = [aws_db_instance.registry.master_user_secret[0].secret_arn],
    }]
    topic-bootstrap = [
      local.kafka_connect,
      { Effect = "Allow", Action = ["kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic", "kafka-cluster:AlterTopic"], Resource = [local.kafka_topics] },
    ]
    fluent-bit = [{
      Effect   = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = ["${aws_cloudwatch_log_group.eks.arn}:*"],
    }]
    prometheus = [{ Effect = "Allow", Action = ["ec2:DescribeInstances"], Resource = ["*"] }]
    cloudwatch-exporter = [{
      Effect   = "Allow", Action = ["cloudwatch:ListMetrics", "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics"],
      Resource = ["*"],
    }]
  }
}
resource "aws_iam_role" "service" {
  for_each = local.service_accounts
  name     = "${var.project}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn },
      Condition = { StringEquals = {
        "${local.oidc_host}:sub" = "system:serviceaccount:${each.value}"
        "${local.oidc_host}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}
resource "aws_iam_role_policy" "service" {
  for_each = local.permissions
  role     = aws_iam_role.service[each.key].id
  policy   = jsonencode({ Version = "2012-10-17", Statement = each.value })
}
resource "aws_iam_role_policy_attachment" "platform" {
  for_each = {
    vpc-cni = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    ebs-csi = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  }
  role       = aws_iam_role.service[each.key].name
  policy_arn = each.value
}
resource "aws_iam_role" "lambda" {
  name = "${var.project}-dispatcher"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.dynamo,
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = [aws_sqs_queue.notifications.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.lambda.arn}:*"] },
    ]
  })
}
resource "aws_iam_role" "emr_service" {
  name = "${var.project}-emr-service"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "elasticmapreduce.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy_attachment" "emr_service" {
  role       = aws_iam_role.emr_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEMRServicePolicy_v2"
}
resource "aws_iam_role" "emr_node" {
  name = "${var.project}-emr-node"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}
resource "aws_iam_instance_profile" "emr_node" { role = aws_iam_role.emr_node.name }
resource "aws_iam_role_policy" "emr_node" {
  role = aws_iam_role.emr_node.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.kafka_connect, local.kafka_idempotent, local.kafka_read, local.kafka_write, local.kafka_consumer,
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [aws_s3_bucket.data.arn] },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"], Resource = ["${aws_s3_bucket.data.arn}/*"] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"], Resource = ["${aws_cloudwatch_log_group.analytics.arn}:*"] },
    ]
  })
}
resource "aws_iam_role_policy_attachment" "emr_ssm" {
  role       = aws_iam_role.emr_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy" "emr_pass_role" {
  role = aws_iam_role.emr_service.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.emr_node.arn],
      Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } },
    }]
  })
}
