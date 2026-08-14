resource "aws_security_group" "cluster" {
  name   = "stock-research-${var.env}-cluster"
  vpc_id = var.vpc_id

  ingress {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # tighten to a known IP range before real deployment
  }
  ingress {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port = 6443
    to_port   = 6443
    protocol  = "tcp"
    self      = true
  }
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

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_instance" "control_plane" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.cluster.id]
  iam_instance_profile   = var.instance_profile_name
  user_data = templatefile("${path.module}/bootstrap.sh.tpl", {
    role = "control-plane", control_plane_ip = "", cluster_token = var.cluster_token
  })
  tags = { Name = "stock-research-${var.env}-control-plane" }
}

resource "aws_instance" "worker" {
  count                  = 2
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_ids[count.index % length(var.subnet_ids)]
  vpc_security_group_ids = [aws_security_group.cluster.id]
  iam_instance_profile   = var.instance_profile_name
  user_data = templatefile("${path.module}/bootstrap.sh.tpl", {
    role = "worker", control_plane_ip = aws_instance.control_plane.private_ip, cluster_token = var.cluster_token
  })
  tags = { Name = "stock-research-${var.env}-worker-${count.index}" }

  depends_on = [aws_instance.control_plane]
}

resource "aws_elb" "ingress" {
  name    = "stock-research-${var.env}-ingress"
  subnets = var.subnet_ids

  listener {
    instance_port     = 30080  # ingress-nginx's fixed NodePort, set at install time (Task 49)
    instance_protocol = "http"
    lb_port            = 80
    lb_protocol         = "http"
  }

  health_check {
    target              = "HTTP:30080/healthz"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  instances                  = aws_instance.worker[*].id
  cross_zone_load_balancing  = true
  security_groups            = [aws_security_group.cluster.id]
}
