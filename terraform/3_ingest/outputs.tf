output "ingest_endpoint" {
  description = "Full URL of the ingest API endpoint"
  value       = "https://${aws_api_gateway_rest_api.api.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_api_gateway_stage.api.stage_name}/ingest"
}

output "api_key" {
  description = "API key value for the ingest endpoint"
  value       = aws_api_gateway_api_key.api_key.value
  sensitive   = true    # won't print in terminal
}

output "vector_bucket" {
  description = "S3 Vectors bucket name"
  value       = aws_s3_bucket.vectors.bucket
}

output "lambda_function_name" {
  description = "Name of the ingest Lambda function"
  value       = aws_lambda_function.ingest.function_name
}

output "setup_instructions" {
  description = "Values to add to your .env file"
  value = <<-EOT

    ✅ Ingest pipeline deployed successfully!

    Add these to your .env file:
    VECTOR_BUCKET=${aws_s3_bucket.vectors.bucket}
    ARIA_API_ENDPOINT=https://${aws_api_gateway_rest_api.api.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_api_gateway_stage.api.stage_name}/ingest
    ARIA_API_KEY=$(terraform output -raw api_key)

  EOT
}