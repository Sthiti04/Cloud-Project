resource "aws_security_group" "public_api" {
  name_prefix = "${var.project}-https-"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port       = 30080
    to_port         = 30080
    protocol        = "tcp"
    security_groups = [aws_security_group.nodes.id]
  }
}
resource "aws_security_group_rule" "public_to_nodes" {
  type                     = "ingress"
  security_group_id        = aws_security_group.nodes.id
  source_security_group_id = aws_security_group.public_api.id
  from_port                = 30080
  to_port                  = 30080
  protocol                 = "tcp"
}
resource "aws_lb" "public_api" {
  name               = "${var.project}-api"
  internal           = false
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.public_api.id]
}
resource "tls_private_key" "api" {
  algorithm = "RSA"
  rsa_bits  = 2048
}
resource "tls_self_signed_cert" "api" {
  private_key_pem       = tls_private_key.api.private_key_pem
  dns_names             = [aws_lb.public_api.dns_name]
  validity_period_hours = 720
  early_renewal_hours   = 72
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]
  subject { common_name = aws_lb.public_api.dns_name }
}
resource "aws_acm_certificate" "api" {
  private_key      = tls_private_key.api.private_key_pem
  certificate_body = tls_self_signed_cert.api.cert_pem
}
resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api"
  port        = 30080
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/health/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
  }
}
resource "aws_autoscaling_attachment" "api" {
  autoscaling_group_name = aws_eks_node_group.main.resources[0].autoscaling_groups[0].name
  lb_target_group_arn    = aws_lb_target_group.api.arn
}
resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.public_api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.api.arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
