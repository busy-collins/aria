# outputs.tf exposes values that OTHER modules need
# Think of these like return values from a function

# Other modules reference this like:
#   data.terraform_remote_state.permissions.outputs.lambda_role_arn

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.arn
}

output "lambda_role_name" {
  description = "Name of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.name
}

output "app_runner_role_arn" {
  description = "ARN of the App Runner role"
  value       = aws_iam_role.app_runner_role.arn
}