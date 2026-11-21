output "deployment" {
  description = "Non-secret metadata for tools/configure_aws.py; do not publish API keys or private keys."
  value = {
    region             = var.region
    project            = var.project
    cluster_name       = aws_eks_cluster.main.name
    cluster_endpoint   = aws_eks_cluster.main.endpoint
    cluster_ca         = aws_eks_cluster.main.certificate_authority[0].data
    public_url         = "https://${aws_lb.public_api.dns_name}"
    certificate_pem    = tls_self_signed_cert.api.cert_pem
    app_repository     = aws_ecr_repository.app.repository_url
    lambda_repository  = aws_ecr_repository.dispatcher.repository_url
    lambda_function    = "${var.project}-dispatcher"
    emr_cluster_id     = try(aws_emr_cluster.analytics[0].id, null)
    emr_master_dns     = try(aws_emr_cluster.analytics[0].master_public_dns, null)
    runtime_enabled    = var.enable_runtime
    log_groups         = [aws_cloudwatch_log_group.eks.name, aws_cloudwatch_log_group.analytics.name, aws_cloudwatch_log_group.lambda.name]
    role_arns          = { for key, role in aws_iam_role.service : key => role.arn }
    zookeeper_volumes  = [for volume in aws_ebs_volume.zookeeper : { id = volume.id, zone = volume.availability_zone }]
    environment        = local.runtime_environment
    bucket             = aws_s3_bucket.data.id
    notification_queue = aws_sqs_queue.notifications.url
    dead_letter_queue  = aws_sqs_queue.dead_letters.url
  }
}
