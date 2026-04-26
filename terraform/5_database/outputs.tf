output "aurora_cluster_arn" {
  description = "Aurora cluster ARN"
  value       = aws_rds_cluster.aurora.arn
}

output "aurora_cluster_endpoint" {
  description = "Aurora writer endpoint"
  value       = aws_rds_cluster.aurora.endpoint
}

output "aurora_secret_arn" {
  description = "Secrets Manager ARN for DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "database_name" {
  description = "Database name"
  value       = aws_rds_cluster.aurora.database_name
}

output "setup_instructions" {
  value = <<-EOT

    ✅ Aurora Serverless v2 deployed successfully!

    Add to your .env file:
    AURORA_CLUSTER_ARN=${aws_rds_cluster.aurora.arn}
    AURORA_SECRET_ARN=${aws_secretsmanager_secret.db_credentials.arn}
    DATABASE_NAME=${aws_rds_cluster.aurora.database_name}

    Next step — run migrations:
    cd backend/api
    python run_migrations.py

  EOT
}