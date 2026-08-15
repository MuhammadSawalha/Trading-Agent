variable "env" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_profile_name" { type = string }
variable "instance_type" {
  type    = string
  default = "t3.medium"
}
variable "cluster_token" {
  type      = string
  sensitive = true
}
variable "ssh_public_key" { type = string }
