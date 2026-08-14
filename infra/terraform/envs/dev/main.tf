module "network" {
  source = "../../modules/network"
  env    = "dev"
}

module "s3" {
  source = "../../modules/s3"
  env    = "dev"
}

module "dynamodb" {
  source = "../../modules/dynamodb"
  env    = "dev"
}

module "iam" {
  source              = "../../modules/iam"
  env                 = "dev"
  dynamodb_table_arns = module.dynamodb.table_arns
  s3_bucket_arn       = module.s3.bucket_arn
}

variable "cluster_token" {
  type      = string
  sensitive = true
}

module "cluster" {
  source                 = "../../modules/cluster"
  env                     = "dev"
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.public_subnet_ids
  instance_profile_name   = module.iam.instance_profile_name
  cluster_token           = var.cluster_token
}

output "control_plane_public_ip" {
  value = module.cluster.control_plane_public_ip
}

output "elb_dns_name" {
  value = module.cluster.elb_dns_name
}
