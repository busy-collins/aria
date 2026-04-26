output "sqs_queue_url" {
  description = "SQS queue URL for sending research jobs"
  value       = aws_sqs_queue.jobs.url
}

output "sqs_queue_arn" {
  description = "SQS queue ARN"
  value       = aws_sqs_queue.jobs.arn
}

output "analyst_function_name" {
  description = "Analyst Lambda function name"
  value       = aws_lambda_function.analyst.function_name
}

output "writer_function_name" {
  description = "Writer Lambda function name"
  value       = aws_lambda_function.writer.function_name
}

output "critic_function_name" {
  description = "Critic Lambda function name"
  value       = aws_lambda_function.critic.function_name
}

output "setup_instructions" {
  value = <<-EOT

    ✅ Agent Lambdas deployed successfully!

    Add to your .env:
    SQS_QUEUE_URL=${aws_sqs_queue.jobs.url}
    SQS_QUEUE_ARN=${aws_sqs_queue.jobs.arn}

  EOT
}