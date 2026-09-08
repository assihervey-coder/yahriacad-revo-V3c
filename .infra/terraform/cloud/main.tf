# =============================================================================
# Terraform — module `cloud` : provider générique (placeholder AWS commenté).
# Appliquer EN PREMIER : `terraform apply` dans cloud/ fournit les outputs
# (provider/region) utilisés par les autres modules via remote state.
# =============================================================================
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    # --- AWS (placeholder) — décommenter et renseigner la région pour AWS ---
    # aws = {
    #   source  = "hashicorp/aws"
    #   version = "~> 5.40"
    # }

    # --- Provider générique : le backend réel est abstrait (docker/k8s local) ---
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }

  # State partagé entre modules (S3 placeholder) :
  # backend "s3" {
  #   bucket = "pcb-ai-v3-terraform-state"
  #   key    = "cloud/terraform.tfstate"
  #   region = "eu-west-1"
  # }
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------
variable "cloud_provider" {
  description = "Fournisseur cloud cible (aws | gcp | azure | local)"
  type        = string
  default     = "local"

  validation {
    condition     = contains(["aws", "gcp", "azure", "local"], var.cloud_provider)
    error_message = "cloud_provider doit être : aws, gcp, azure ou local."
  }
}

variable "region" {
  description = "Région de déploiement (ignorée en local)"
  type        = string
  default     = "eu-west-1"
}

variable "project" {
  description = "Nom du projet (préfixe de toutes les ressources)"
  type        = string
  default     = "pcb-ai-v3"
}

# -----------------------------------------------------------------------------
# Provider local : aucune ressource cloud réelle (déploiement k8s/docker local)
# -----------------------------------------------------------------------------
provider "null" {}

resource "null_resource" "cloud_config" {
  triggers = {
    provider = var.cloud_provider
    region   = var.region
    project  = var.project
  }
}

# -----------------------------------------------------------------------------
# Outputs consommés par les autres modules (storage, databases, networking)
# -----------------------------------------------------------------------------
output "cloud_provider" {
  description = "Fournisseur cloud actif"
  value       = var.cloud_provider
}

output "region" {
  description = "Région de déploiement"
  value       = var.region
}

output "project" {
  description = "Préfixe projet des ressources"
  value       = var.project
}
