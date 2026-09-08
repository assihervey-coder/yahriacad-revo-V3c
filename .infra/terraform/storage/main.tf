# =============================================================================
# Terraform — module `storage` : buckets S3 pour data/ et trained_models.
# data/datasets (datasets composants, corpus RAG) + trained_models (RL).
# Appliquer APRÈS cloud/ : `terraform apply` dans storage/.
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
  description = "Préfixe projet (cf. output du module cloud)"
  type        = string
  default     = "pcb-ai-v3"
}

variable "region" {
  description = "Région de déploiement"
  type        = string
  default     = "eu-west-1"
}

variable "versioning_enabled" {
  description = "Versioning des buckets (checkpoints RL et datasets immuables)"
  type        = bool
  default     = true
}

variable "datasets_lifecycle_days" {
  description = "Expiration des anciennes versions de datasets (jours)"
  type        = number
  default     = 90
}

# --- Buckets -----------------------------------------------------------------
# NOTE AWS (placeholder — décommenter pour un déploiement réel) :
#
# resource "aws_s3_bucket" "datasets" {
#   bucket = "${var.project}-datasets"
# }
#
# resource "aws_s3_bucket_versioning" "datasets" {
#   bucket = aws_s3_bucket.datasets.id
#   versioning_configuration {
#     status = var.versioning_enabled ? "Enabled" : "Suspended"
#   }
# }
#
# resource "aws_s3_bucket" "trained_models" {
#   bucket = "${var.project}-trained-models"
# }
#
# resource "aws_s3_bucket_versioning" "trained_models" {
#   bucket = aws_s3_bucket.trained_models.id
#   versioning_configuration {
#     status = var.versioning_enabled ? "Enabled" : "Suspended"
#   }
# }

resource "null_resource" "storage_manifest" {
  triggers = {
    datasets_bucket       = "${var.project}-datasets"        # ← data/datasets
    trained_models_bucket = "${var.project}-trained-models"  # ← data/trained_models
    versioning            = var.versioning_enabled ? "enabled" : "suspended"
    lifecycle_days        = var.datasets_lifecycle_days
    region                = var.region
  }
}

# --- Outputs -----------------------------------------------------------------
output "datasets_bucket" {
  description = "Bucket des datasets (data/datasets)"
  value       = "${var.project}-datasets"
}

output "trained_models_bucket" {
  description = "Bucket des modèles entraînés (data/trained_models)"
  value       = "${var.project}-trained-models"
}
