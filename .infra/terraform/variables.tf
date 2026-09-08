# =============================================================================
# Terraform — variables communes à tous les modules (.infra/terraform/*).
# Ce fichier est le point de référence ; chaque module le déclare aussi
# localement pour rester autonome (`terraform apply` par dossier).
# =============================================================================
variable "cloud_provider" {
  description = "Fournisseur cloud cible (aws | gcp | azure | local)"
  type        = string
  default     = "local"
}

variable "region" {
  description = "Région de déploiement"
  type        = string
  default     = "eu-west-1"
}

variable "project" {
  description = "Préfixe projet de toutes les ressources"
  type        = string
  default     = "pcb-ai-v3"
}

variable "environment" {
  description = "Environnement (development | staging | production)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment doit être : development, staging ou production."
  }
}

variable "vpc_cidr" {
  description = "Bloc CIDR du VPC (module networking)"
  type        = string
  default     = "10.42.0.0/16"
}

variable "db_instance_class" {
  description = "Classe d'instance RDS (module databases)"
  type        = string
  default     = "db.t4g.medium"
}

variable "cache_instance_class" {
  description = "Classe de nœud ElastiCache (module databases)"
  type        = string
  default     = "cache.t4g.micro"
}

variable "versioning_enabled" {
  description = "Versioning S3 (module storage)"
  type        = bool
  default     = true
}

# Tags communs appliqués à toutes les ressources taguables
variable "common_tags" {
  description = "Tags communs (coûts, traçabilité)"
  type        = map(string)
  default = {
    Project     = "pcb-ai-designer-v3"
    ManagedBy   = "terraform"
    Environment = "production"
  }
}
