output "control_plane_public_ip" {
  value = aws_instance.control_plane.public_ip
}

output "worker_public_ips" {
  value = aws_instance.worker[*].public_ip
}

output "elb_dns_name" {
  value = aws_elb.ingress.dns_name
}
