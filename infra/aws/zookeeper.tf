resource "aws_ebs_volume" "zookeeper" {
  count             = 3
  availability_zone = data.aws_availability_zones.available.names[count.index % 2]
  size              = 2
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "${var.project}-zookeeper-${count.index}" }
}
