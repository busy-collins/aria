output "ecr_repository_url" {
  description = "ECR repository URL for pushing Docker images"
  value       = aws_ecr_repository.researcher.repository_url
}

output "app_runner_service_url" {
  description = "App Runner service URL"
  value       = aws_apprunner_service.researcher.service_url
}

output "app_runner_service_arn" {
  description = "App Runner service ARN"
  value       = aws_apprunner_service.researcher.arn
}

output "ecr_repository_name" {
  description = "ECR repository name"
  value       = aws_ecr_repository.researcher.name
}