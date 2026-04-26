terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ── Read outputs from previous modules ────────────────────
data "terraform_remote_state" "permissions" {
  backend = "local"
  config  = { path = "../1_permissions/terraform.tfstate" }
}

data "terraform_remote_state" "database" {
  backend = "local"
  config  = { path = "../5_database/terraform.tfstate" }
}

data "terraform_remote_state" "ingest" {
  backend = "local"
  config  = { path = "../3_ingest/terraform.tfstate" }
}

# ========================================
# SQS Queues
# ========================================

resource "aws_sqs_queue" "jobs_dlq" {
  name                      = "${var.project_name}-jobs-dlq"
  message_retention_seconds = 1209600

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.project_name}-research-jobs"
  visibility_timeout_seconds = 900
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

# ========================================
# IAM Role
# ========================================

resource "aws_iam_role" "agent_lambda_role" {
  name = "${var.project_name}-agent-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

resource "aws_iam_role_policy_attachment" "agent_lambda_basic" {
  role       = aws_iam_role.agent_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "agent_lambda_policy" {
  name = "${var.project_name}-agent-lambda-policy"
  role = aws_iam_role.agent_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:SendMessage"
        ]
        Resource = [
          aws_sqs_queue.jobs.arn,
          aws_sqs_queue.jobs_dlq.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction"
        ]
        Resource = data.terraform_remote_state.database.outputs.aurora_cluster_arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          data.terraform_remote_state.database.outputs.aurora_secret_arn,
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:aria/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.project_name}-*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-*"
      }
    ]
  })
}

# ========================================
# Lambda Package
# ── Pre-built by backend/agents/package_lambda.py
# ── Run: python backend/agents/package_lambda.py
# ── before terraform apply to update the package
# ========================================

locals {
  lambda_zip = "${path.module}/agents_lambda.zip"
}

# ========================================
# Analyst Lambda
# ========================================

resource "aws_lambda_function" "analyst" {
  function_name    = "${var.project_name}-analyst"
  role             = aws_iam_role.agent_lambda_role.arn
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  handler          = "analyst_handler.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 1024

  environment {
    variables = {
      OPENAI_SECRET_NAME    = "aria/openai-api-key"
      LANGSMITH_SECRET_NAME = "aria/langsmith-api-key"
      AURORA_CLUSTER_ARN    = data.terraform_remote_state.database.outputs.aurora_cluster_arn
      AURORA_SECRET_ARN     = data.terraform_remote_state.database.outputs.aurora_secret_arn
      DATABASE_NAME         = "aria"
      VECTOR_BUCKET         = data.terraform_remote_state.ingest.outputs.vector_bucket
      VECTOR_INDEX_NAME     = var.vector_index_name
      SAGEMAKER_ENDPOINT    = "${var.project_name}-embedding-endpoint"
      DEFAULT_AWS_REGION    = var.aws_region
      LANGSMITH_PROJECT     = var.langsmith_project
      PROJECT_NAME          = var.project_name
      RESEARCHER_URL        = var.researcher_url
    }
  }

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

resource "aws_cloudwatch_log_group" "analyst_logs" {
  name              = "/aws/lambda/${var.project_name}-analyst"
  retention_in_days = 7
}

# ========================================
# Writer Lambda
# ========================================

resource "aws_lambda_function" "writer" {
  function_name    = "${var.project_name}-writer"
  role             = aws_iam_role.agent_lambda_role.arn
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  handler          = "writer_handler.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 1024

  environment {
    variables = {
      OPENAI_SECRET_NAME    = "aria/openai-api-key"
      LANGSMITH_SECRET_NAME = "aria/langsmith-api-key"
      AURORA_CLUSTER_ARN    = data.terraform_remote_state.database.outputs.aurora_cluster_arn
      AURORA_SECRET_ARN     = data.terraform_remote_state.database.outputs.aurora_secret_arn
      DATABASE_NAME         = "aria"
      DEFAULT_AWS_REGION    = var.aws_region
      LANGSMITH_PROJECT     = var.langsmith_project
      PROJECT_NAME          = var.project_name
    }
  }

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

resource "aws_cloudwatch_log_group" "writer_logs" {
  name              = "/aws/lambda/${var.project_name}-writer"
  retention_in_days = 7
}

# ========================================
# Critic Lambda
# ========================================

resource "aws_lambda_function" "critic" {
  function_name    = "${var.project_name}-critic"
  role             = aws_iam_role.agent_lambda_role.arn
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  handler          = "critic_handler.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 1024

  environment {
    variables = {
      OPENAI_SECRET_NAME    = "aria/openai-api-key"
      LANGSMITH_SECRET_NAME = "aria/langsmith-api-key"
      AURORA_CLUSTER_ARN    = data.terraform_remote_state.database.outputs.aurora_cluster_arn
      AURORA_SECRET_ARN     = data.terraform_remote_state.database.outputs.aurora_secret_arn
      DATABASE_NAME         = "aria"
      DEFAULT_AWS_REGION    = var.aws_region
      LANGSMITH_PROJECT     = var.langsmith_project
      PROJECT_NAME          = var.project_name
    }
  }

  tags = {
    Project = var.project_name
    Module  = "6_agents"
  }
}

resource "aws_cloudwatch_log_group" "critic_logs" {
  name              = "/aws/lambda/${var.project_name}-critic"
  retention_in_days = 7
}

# ========================================
# SQS → Analyst Trigger
# ========================================

resource "aws_lambda_event_source_mapping" "sqs_to_analyst" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.analyst.arn
  batch_size       = 1
  enabled          = true
}