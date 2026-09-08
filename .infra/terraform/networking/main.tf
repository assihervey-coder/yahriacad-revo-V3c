# =============================================================================
# Terraform — module `networking` : VPC, 2 subnets, security groups.
# Ports internes : 8000 (API), 3000 (frontend), 5432 (postgres), 6379 (redis).
# Appliquer APRÈS cloud/ et AVANT databases/.
# =============================================================================
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    # aws = {
    #   source  = "hashicorp/aws"
    #   version = "~> 5.40"
    # }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

# --- Variables ---------------------------------------------------------------
variable "project" {
  description = "Préfixe projet"
  type        = string
  default     = "pcb-ai-v3"
}

variable "region" {
  description = "Région de déploiement"
  type        = string
  default     = "eu-west-1"
}

variable "vpc_cidr" {
  description = "Bloc CIDR du VPC"
  type        = string
  default     = "10.42.0.0/16"
}

variable "subnet_cidrs" {
  description = "CIDR des 2 subnets privés (zones a/b)"
  type        = list(string)
  default     = ["10.42.1.0/24", "10.42.2.0/24"]
}

# --- Ressources (placeholder AWS — décommenter pour un déploiement réel) -----
#
# resource "aws_vpc" "main" {
#   cidr_block           = var.vpc_cidr
#   enable_dns_support   = true
#   enable_dns_hostnames = true
#   tags = { Name = "${var.project}-vpc" }
# }
#
# resource "aws_subnet" "private" {
#   count             = length(var.subnet_cidrs)
#   vpc_id            = aws_vpc.main.id
#   cidr_block        = var.subnet_cidrs[count.index]
#   availability_zone = "${var.region}${["a", "b"][count.index]}"
#   tags = { Name = "${var.project}-private-${count.index}" }
# }
#
# resource "aws_security_group" "api" {
#   name_prefix = "${var.project}-api-"
#   vpc_id      = aws_vpc.main.id
#   ingress {
#     from_port   = 8000
#     to_port     = 8000
#     protocol    = "tcp"
#     cidr_blocks = [var.vpc_cidr]      # interne VPC uniquement
#   }
# }
#
# resource "aws_security_group" "frontend" {
#   name_prefix = "${var.project}-frontend-"
#   vpc_id      = aws_vpc.main.id
#   ingress {
#     from_port   = 3000
#     to_port     = 3000
#     protocol    = "tcp"
#     cidr_blocks = [var.vpc_cidr]
#   }
# }
#
# resource "aws_security_group" "postgres" {
#   name_prefix = "${var.project}-postgres-"
#   vpc_id      = aws_vpc.main.id
#   ingress {
#     from_port   = 5432
#     to_port     = 5432
#     protocol    = "tcp"
#     cidr_blocks = [var.vpc_cidr]
#   }
# }
#
# resource "aws_security_group" "redis" {
#   name_prefix = "${var.project}-redis-"
#   vpc_id      = aws_vpc.main.id
#   ingress {
#     from_port   = 6379
#     to_port     = 6379
#     protocol    = "tcp"
#     cidr_blocks = [var.vpc_cidr]
#   }
# }

resource "null_resource" "networking_manifest" {
  triggers = {
    vpc_cidr    = var.vpc_cidr
    subnets     = join(",", var.subnet_cidrs)
    ports       = "8000,3000,5432,6379"
    region      = var.region
  }
}

# --- Outputs -----------------------------------------------------------------
output "vpc_cidr" {
  description = "CIDR du VPC"
  value       = var.vpc_cidr
}

output "subnet_cidrs" {
  description = "CIDR des subnets privés"
  value       = var.subnet_cidrs
}

output "internal_ports" {
  description = "Ports internes ouverts (api/frontend/postgres/redis)"
  value       = "8000,3000,5432,6379"
}

output "postgres_sg_name" {
  description = "Nom du security group postgres (consommé par databases/)"
  value       = "${var.project}-postgres-sg"
}

output "redis_sg_name" {
  description = "Nom du security group redis (consommé par databases/)"
  value       = "${var.project}-redis-sg"
}
