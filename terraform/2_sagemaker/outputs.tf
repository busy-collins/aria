output "endpoint_name" {
  description = "SageMaker endpoint name — used by Lambda to generate embeddings"
  value       = aws_sagemaker_endpoint.embeddings.name
}

output "endpoint_arn" {
  description = "SageMaker endpoint ARN"
  value       = aws_sagemaker_endpoint.embeddings.arn
}