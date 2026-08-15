module "network" {
  source = "../../modules/network"
  env    = "prod"
}

module "s3" {
  source = "../../modules/s3"
  env    = "prod"
}

module "dynamodb" {
  source = "../../modules/dynamodb"
  env    = "prod"
}

module "iam" {
  source              = "../../modules/iam"
  env                 = "prod"
  dynamodb_table_arns = module.dynamodb.table_arns
  s3_bucket_arn       = module.s3.bucket_arn
}

variable "cluster_token" {
  type      = string
  sensitive = true
}
variable "ssh_public_key" { type = string }

module "cluster" {
  source                = "../../modules/cluster"
  env                   = "prod"
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.public_subnet_ids
  instance_profile_name = module.iam.instance_profile_name
  cluster_token         = var.cluster_token
  ssh_public_key        = var.ssh_public_key
}

output "control_plane_public_ip" {
  value = module.cluster.control_plane_public_ip
}

output "elb_dns_name" {
  value = module.cluster.elb_dns_name
}

output "dynamodb_table_suffix" {
  value = "-prod"
}
