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

# ========================================
# ECR Repository
# ========================================

resource "aws_ecr_repository" "researcher" {
  name                 = "${var.project_name}-research-assistant"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

# ========================================
# App Runner IAM Roles
# ========================================

# Role for App Runner to pull from ECR
resource "aws_iam_role" "app_runner_role" {
  name = "${var.project_name}-app-runner-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "build.apprunner.amazonaws.com" }
      },
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "tasks.apprunner.amazonaws.com" }
      }
    ]
  })

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

resource "aws_iam_role_policy_attachment" "app_runner_ecr_access" {
  role       = aws_iam_role.app_runner_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# Role for App Runner instance runtime permissions
resource "aws_iam_role" "app_runner_instance_role" {
  name = "${var.project_name}-app-runner-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
    }]
  })

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

resource "aws_iam_role_policy" "app_runner_instance_policy" {
  name = "${var.project_name}-app-runner-instance-policy"
  role = aws_iam_role.app_runner_instance_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Bedrock — AI model inference
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ListFoundationModels"
        ]
        Resource = "*"
      },
      # SageMaker — embedding endpoint
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.project_name}-*"
      },
      # S3 Vectors — knowledge base
      {
        Effect = "Allow"
        Action = [
          "s3vectors:PutVectors",
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
          "s3vectors:DeleteVectors"
        ]
        Resource = "*"
      },
      # CloudWatch — logging
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}

# ========================================
# App Runner Service
# ========================================

resource "aws_apprunner_service" "researcher" {
  service_name = "${var.project_name}-research-assistant"

  source_configuration {
    auto_deployments_enabled = false

    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_role.arn
    }

    image_repository {
      image_identifier = "${aws_ecr_repository.researcher.repository_url}:latest"

      image_configuration {
        port = "8000"

        runtime_environment_variables = {
          OPENAI_API_KEY    = var.openai_api_key
          ARIA_API_ENDPOINT = var.aria_api_endpoint
          ARIA_API_KEY      = var.aria_api_key
        }
      }

      image_repository_type = "ECR"
    }
  }

  instance_configuration {
    cpu               = "1 vCPU"
    memory            = "2 GB"
    instance_role_arn = aws_iam_role.app_runner_instance_role.arn
  }

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

# ========================================
# EventBridge Scheduler (Optional)
# ========================================

resource "aws_iam_role" "eventbridge_role" {
  count = var.scheduler_enabled ? 1 : 0
  name  = "${var.project_name}-eventbridge-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

resource "aws_iam_role" "lambda_scheduler_role" {
  count = var.scheduler_enabled ? 1 : 0
  name  = "${var.project_name}-scheduler-lambda-role"

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
    Module  = "4_researcher"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_scheduler_basic" {
  count      = var.scheduler_enabled ? 1 : 0
  role       = aws_iam_role.lambda_scheduler_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "scheduler_lambda" {
  count         = var.scheduler_enabled ? 1 : 0
  function_name = "${var.project_name}-research-scheduler"
  role          = aws_iam_role.lambda_scheduler_role[0].arn

  filename         = "${path.module}/../../backend/scheduler/lambda_function.zip"
  source_code_hash = fileexists("${path.module}/../../backend/scheduler/lambda_function.zip") ? filebase64sha256("${path.module}/../../backend/scheduler/lambda_function.zip") : null

  handler     = "lambda_function.handler"
  runtime     = "python3.12"
  timeout     = 180
  memory_size = 256

  environment {
    variables = {
      APP_RUNNER_URL = aws_apprunner_service.researcher.service_url
    }
  }

  tags = {
    Project = var.project_name
    Module  = "4_researcher"
  }
}

resource "aws_scheduler_schedule" "research_schedule" {
  count = var.scheduler_enabled ? 1 : 0
  name  = "${var.project_name}-research-schedule"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(2 hours)"

  target {
    arn      = aws_lambda_function.scheduler_lambda[0].arn
    role_arn = aws_iam_role.eventbridge_role[0].arn
  }
}

resource "aws_lambda_permission" "allow_eventbridge" {
  count         = var.scheduler_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler_lambda[0].function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.research_schedule[0].arn
}

resource "aws_iam_role_policy" "eventbridge_invoke_lambda" {
  count = var.scheduler_enabled ? 1 : 0
  name  = "${var.project_name}-eventbridge-invoke-lambda"
  role  = aws_iam_role.eventbridge_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.scheduler_lambda[0].arn
    }]
  })
}