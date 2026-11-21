resource "aws_msk_configuration" "main" {
  name              = "${var.project}-configuration"
  kafka_versions    = ["3.9.x"]
  server_properties = <<-PROPERTIES
    auto.create.topics.enable=false
    default.replication.factor=2
    min.insync.replicas=1
    log.retention.hours=24
  PROPERTIES
}
resource "aws_msk_cluster" "main" {
  cluster_name           = "${var.project}-kafka"
  kafka_version          = "3.9.x"
  number_of_broker_nodes = 2
  broker_node_group_info {
    instance_type   = "kafka.t3.small"
    client_subnets  = aws_subnet.private[*].id
    security_groups = [aws_security_group.data.id]
    storage_info {
      ebs_storage_info { volume_size = 10 }
    }
  }
  client_authentication {
    sasl { iam = true }
    unauthenticated = false
  }
  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }
  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }
  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.kafka.name
      }
    }
  }
}

locals {
  flink_artifacts = {
    "clinical-analytics.jar"       = "${path.module}/../../analytics/target/clinical-analytics.jar"
    "flink-s3-fs-hadoop.jar"       = "${path.module}/../../analytics/target/runtime/flink-s3-fs-hadoop.jar"
    "flink-metrics-prometheus.jar" = "${path.module}/../../analytics/target/runtime/flink-metrics-prometheus.jar"
  }
}
resource "aws_s3_object" "runtime" {
  for_each    = var.enable_runtime ? local.flink_artifacts : {}
  bucket      = aws_s3_bucket.data.id
  key         = "artifacts/${each.key}"
  source      = each.value
  source_hash = filemd5(each.value)
}
resource "aws_s3_object" "emr_bootstrap" {
  bucket = aws_s3_bucket.data.id
  key    = "artifacts/emr-bootstrap.sh"
  content = replace(templatefile("${path.module}/emr-bootstrap.sh.tftpl", {
    log_group = aws_cloudwatch_log_group.analytics.name
    region    = var.region
  }), "\r", "")
}
resource "aws_emr_cluster" "analytics" {
  count         = var.enable_runtime ? 1 : 0
  name          = "${var.project}-analytics"
  release_label = "emr-7.14.0"
  applications  = ["Hadoop", "Flink"]
  service_role  = aws_iam_role.emr_service.arn
  log_uri       = "s3://${aws_s3_bucket.data.id}/emr-logs/"
  ec2_attributes {
    subnet_id                         = aws_subnet.private[0].id
    instance_profile                  = aws_iam_instance_profile.emr_node.arn
    emr_managed_master_security_group = aws_security_group.emr_master.id
    emr_managed_slave_security_group  = aws_security_group.emr_core.id
    service_access_security_group     = aws_security_group.emr_service.id
  }
  master_instance_group { instance_type = "m5.xlarge" }
  core_instance_group {
    instance_type  = "m5.xlarge"
    instance_count = 1
  }
  ebs_root_volume_size              = 32
  keep_job_flow_alive_when_no_steps = true
  termination_protection            = false
  bootstrap_action {
    name = "centralized-logs"
    path = "s3://${aws_s3_bucket.data.id}/${aws_s3_object.emr_bootstrap.key}"
  }
  configurations_json = jsonencode([{
    Classification = "flink-conf"
    Properties = {
      "parallelism.default"                 = "2"
      "taskmanager.numberOfTaskSlots"       = "2"
      "jobmanager.memory.process.size"      = "1024m"
      "taskmanager.memory.process.size"     = "2048m"
      "metrics.reporters"                   = "prom"
      "metrics.reporter.prom.factory.class" = "org.apache.flink.metrics.prometheus.PrometheusReporterFactory"
      "metrics.reporter.prom.port"          = "9249-9259"
    }
  }])
  step {
    name              = "start-clinical-analytics"
    action_on_failure = "CANCEL_AND_WAIT"
    hadoop_jar_step {
      jar = "command-runner.jar"
      args = ["bash", "-euc", replace(<<-SCRIPT
        aws s3 cp s3://${aws_s3_bucket.data.id}/artifacts/clinical-analytics.jar /tmp/clinical-analytics.jar
        aws s3 cp s3://${aws_s3_bucket.data.id}/artifacts/flink-metrics-prometheus.jar /tmp/flink-metrics-prometheus.jar
        aws s3 cp s3://${aws_s3_bucket.data.id}/artifacts/flink-s3-fs-hadoop.jar /tmp/flink-s3-fs-hadoop.jar
        sudo cp /tmp/flink-metrics-prometheus.jar /usr/lib/flink/lib/
        sudo mkdir -p /usr/lib/flink/plugins/s3-fs-hadoop
        sudo cp /tmp/flink-s3-fs-hadoop.jar /usr/lib/flink/plugins/s3-fs-hadoop/
        export HADOOP_CLASSPATH="$(hadoop classpath)"
        export AWS_REGION='${var.region}'
        /usr/lib/flink/bin/flink run-application -t yarn-application /tmp/clinical-analytics.jar \
          --brokers '${aws_msk_cluster.main.bootstrap_brokers_sasl_iam}' --mode aws --region '${var.region}' \
          --checkpoint 's3://${aws_s3_bucket.data.id}/flink-checkpoints/'
      SCRIPT
        , "\r", "")
      ]
    }
  }
  tags = { Workload = "analytics" }
  depends_on = [
    aws_s3_object.runtime, aws_iam_role_policy.emr_node, aws_iam_role_policy_attachment.emr_service,
    aws_iam_role_policy.emr_pass_role, aws_route_table_association.private,
  ]
  lifecycle { ignore_changes = [step] }
}
