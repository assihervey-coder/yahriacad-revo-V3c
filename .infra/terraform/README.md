# Terraform — PCB_AI_DESIGNER_V3

Infrastructure cloud découpée en 4 modules indépendants (un état par module).

## Ordre d'application (dépendances)

1. **cloud/**      → provider, région, préfixe projet (base de tout)
2. **networking/** → VPC + 2 subnets + security groups (8000/3000/5432/6379 internes)
3. **storage/**    → buckets S3 `datasets` (data/datasets) + `trained_models` (versioning)
4. **databases/**  → RDS PostgreSQL 16 (db.t4g.medium) + ElastiCache Redis (cache.t4g.micro)
                     — consomme les SG de networking

```bash
cd .infra/terraform
cp terraform.tfvars.example terraform.tfvars   # ajuster les valeurs

for module in cloud networking storage databases; do
  (cd $module && terraform init && terraform plan -out=tfplan && terraform apply tfplan)
done
```

## Remarques

- Les ressources AWS sont en **placeholder commenté** dans chaque module :
  décommenter les blocs `aws_*`, renseigner le provider et le backend S3
  (`cloud/main.tf`) pour un déploiement réel.
- Les outputs `database_url` / `redis_url` (databases/) sont **sensibles** :
  injecter le mot de passe via Secrets Manager / SSM, jamais en clair.
- Les variables communes sont documentées dans `variables.tf` ;
  `terraform.tfvars.example` donne les valeurs de départ.
