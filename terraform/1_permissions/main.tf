# main.tf is where you define the actual AWS resources

# ── Data source: get current caller identity ──────────────
# This is a READ operation — Terraform doesn't create this
# It just reads your current AWS account details
data "aws_caller_identity" "current" {}

# ── Lambda execution role ─────────────────────────────────
# Every Lambda needs a role that grants it permission to run
# and to call other AWS services

resource "aws_iam_role" "lambda_execution_role" {
  # Resource names follow a pattern: project-purpose-type
  name = "${var.project_name}-lambda-execution-role"

  # assume_role_policy answers: WHO is allowed to use this role?
  # Here we say: Lambda functions are allowed to assume it
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = var.project_name
    Module  = "1_permissions"
  }
}

# ── Attach managed policies to the Lambda role ────────────
# AWS provides pre-built policies for common permissions
# AWSLambdaBasicExecutionRole allows: write logs to CloudWatch

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ── Custom policy: what services can the Lambda call? ─────
# This is the inline policy — specific permissions for Aria

resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${var.project_name}-lambda-permissions"
  role = aws_iam_role.lambda_execution_role.id

  # policy answers: WHAT actions are allowed on WHICH resources?
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Allow Lambda to call Aurora via Data API
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction"
        ]
        Resource = "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:cluster:${var.project_name}-aurora-cluster"
      },
      # Allow Lambda to read secrets (DB password, API keys)
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}-*"
      },
      # Allow Lambda to send messages to SQS
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:${var.project_name}-*"
      },
      # Allow Lambda to read/write S3 (vectors bucket)
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.project_name}-vectors-${var.aws_account_id}",
          "arn:aws:s3:::${var.project_name}-vectors-${var.aws_account_id}/*"
        ]
      },
      # Allow Lambda to call Bedrock models
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "arn:aws:bedrock:*::foundation-model/*"
      },
      # Allow Lambda to call SageMaker endpoint (embeddings)
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${var.aws_account_id}:endpoint/${var.project_name}-*"
      }
    ]
  })
}

# ── App Runner role ───────────────────────────────────────
# App Runner needs its own role to pull from ECR
# and call AWS services

resource "aws_iam_role" "app_runner_role" {
  name = "${var.project_name}-app-runner-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# App Runner needs to pull images from ECR
resource "aws_iam_role_policy_attachment" "app_runner_ecr" {
  role       = aws_iam_role.app_runner_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# Attach same permissions as Lambda so researcher can call AWS services
resource "aws_iam_role_policy" "app_runner_permissions" {
  name   = "${var.project_name}-app-runner-permissions"
  role   = aws_iam_role.app_runner_role.id
  policy = aws_iam_role_policy.lambda_permissions.policy
}