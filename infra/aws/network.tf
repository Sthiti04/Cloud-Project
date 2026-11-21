resource "aws_vpc" "main" {
  cidr_block           = "10.23.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  depends_on           = [terraform_data.cost_guard]
}
resource "aws_internet_gateway" "main" { vpc_id = aws_vpc.main.id }

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.23.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
  tags                    = { "kubernetes.io/role/elb" = "1" }
}
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.23.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = { "kubernetes.io/role/internal-elb" = "1" }
}
resource "aws_eip" "nat" { domain = "vpc" }
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.main]
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
}
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_security_group" "nodes" {
  name_prefix = "${var.project}-nodes-"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group_rule" "control_to_nodes" {
  type                     = "ingress"
  security_group_id        = aws_security_group.nodes.id
  source_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
}
resource "aws_security_group_rule" "nodes_to_control" {
  type                     = "ingress"
  security_group_id        = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  source_security_group_id = aws_security_group.nodes.id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
}
resource "aws_security_group" "registry" {
  name_prefix = "${var.project}-registry-"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.nodes.id]
  }
}
resource "aws_security_group" "data" {
  name_prefix = "${var.project}-data-"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  ingress {
    from_port       = 9098
    to_port         = 9098
    protocol        = "tcp"
    security_groups = [aws_security_group.nodes.id, aws_security_group.emr_core.id, aws_security_group.emr_master.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "emr_master" {
  name_prefix = "${var.project}-emr-master-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "emr_core" {
  name_prefix = "${var.project}-emr-core-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "emr_service" {
  name_prefix = "${var.project}-emr-service-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group_rule" "emr_metrics" {
  for_each                 = { master = aws_security_group.emr_master.id, core = aws_security_group.emr_core.id }
  type                     = "ingress"
  security_group_id        = each.value
  source_security_group_id = aws_security_group.nodes.id
  from_port                = 9249
  to_port                  = 9259
  protocol                 = "tcp"
}
