# =============================================================================
# Terraform — module `databases` : RDS PostgreSQL 16 + ElastiCache Redis.
# Instances calibrées plateforme : db.t4g.medium (postgres) + cache.t4g.micro (redis).
# Appliquer APRÈS networking/ (les subnets + SG 5432/6379 sont requis).
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

variable "db_instance_class" {
  description = "Classe d'instance RDS (burst Graviton suffisant en charge normale)"
  type        = string
  default     = "db.t4g.medium"
}

variable "cache_instance_class" {
  description = "Classe de nœud ElastiCache (bus d'événements + cache chaud)"
  type        = string
  default     = "cache.t4g.micro"
}

variable "db_name" {
  description = "Nom de la base PostgreSQL"
  type        = string
  default     = "pcb_ai_v3"
}

variable "db_username" {
  description = "Utilisateur maître PostgreSQL"
  type        = string
  default     = "pcb"
}

variable "db_allocated_storage_gb" {
  description = "Stockage initial RDS (gio)"
  type        = number
  default     = 50
}

# --- Ressources (placeholder AWS — décommenter pour un déploiement réel) -----
#
# resource "aws_db_instance" "postgres" {
#   identifier             = "${var.project}-postgres"
#   engine                 = "postgres"
#   engine_version         = "16"
#   instance_class         = var.db_instance_class
#   allocated_storage      = var.db_allocated_storage_gb
#   db_name                = var.db_name
#   username               = var.db_username
#   password               = var.db_password            # sensible — SSM/Secrets Manager
#   multi_az               = false
#   publicly_accessible    = false
#   vpc_security_group_ids = [var.postgres_sg_id]       # ← output networking
#   skip_final_snapshot    = true
# }
#
# resource "aws_elasticache_cluster" "redis" {
#   cluster_id           = "${var.project}-redis"
#   engine               = "redis"
#   engine_version       = "7.1"
#   node_type            = var.cache_instance_class
#   num_cache_nodes      = 1
#   port                 = 6379
#   security_group_ids   = [var.redis_sg_id]            # ← output networking
# }

resource "null_resource" "databases_manifest" {
  triggers = {
    postgres_identifier = "${var.project}-postgres"
    engine              = "postgres 16"
    instance_class      = var.db_instance_class
    redis_cluster       = "${var.project}-redis"
    cache_node_type     = var.cache_instance_class
    region              = var.region
  }
}

# --- Outputs (chaînes de connexion — SENSIBLES) ------------------------------
output "database_url" {
  description = "URL SQLAlchemy async de PostgreSQL (mot de passe à injecter via secret)"
  value       = "postgresql+asyncpg://${var.db_username}:<DB_PASSWORD>@${var.project}-postgres.${var.region}.rds.amazonaws.com:5432/${var.db_name}"
  sensitive   = true
}

output "redis_url" {
  description = "URL Redis (bus d'événements EVENT_BUS_BACKEND=redis)"
  value       = "redis://${var.project}-redis.${var.region}.cache.amazonaws.com:6379/0"
  sensitive   = true
}
