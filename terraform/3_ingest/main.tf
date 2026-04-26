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

resource "aws_s3_bucket" "vectors" {
  bucket = "${var.project_name}-vectors-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

resource "aws_s3_bucket_versioning" "vectors" {
  bucket = aws_s3_bucket.vectors.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "vectors" {
  bucket = aws_s3_bucket.vectors.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "vectors" {
  bucket = aws_s3_bucket.vectors.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ========================================
# Lambda Function for Ingestion
# ========================================

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-ingest-lambda-role"

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
    Module  = "3_ingest"
  }
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-ingest-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.vectors.arn,
          "${aws_s3_bucket.vectors.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.sagemaker_endpoint_name}"
      },
      {
        Effect = "Allow"
        Action = [
          "s3vectors:PutVectors",
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
          "s3vectors:DeleteVectors"
        ]
        Resource = "arn:aws:s3vectors:${var.aws_region}:${data.aws_caller_identity.current.account_id}:bucket/${aws_s3_bucket.vectors.id}/index/*"
      }
    ]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name = "${var.project_name}-ingest"
  role          = aws_iam_role.lambda_role.arn

  filename         = "${path.module}/../../backend/ingest/lambda_function.zip"
  source_code_hash = fileexists("${path.module}/../../backend/ingest/lambda_function.zip") ? filebase64sha256("${path.module}/../../backend/ingest/lambda_function.zip") : null

  handler     = "ingest_s3vectors.lambda_handler"
  runtime     = "python3.12"
  timeout     = 60
  memory_size = 512

  environment {
    variables = {
      VECTOR_BUCKET      = aws_s3_bucket.vectors.id
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint_name
      INDEX_NAME         = var.vector_index_name
      PROJECT_NAME       = var.project_name
    }
  }

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-ingest"
  retention_in_days = 7

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

# ========================================
# API Gateway
# ========================================

resource "aws_api_gateway_rest_api" "api" {
  name        = "${var.project_name}-ingest-api"
  description = "Aria Ingest API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

resource "aws_api_gateway_resource" "ingest" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "ingest"
}

resource "aws_api_gateway_method" "ingest_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.ingest.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "lambda" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.ingest.id
  http_method = aws_api_gateway_method.ingest_post.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ingest.invoke_arn
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.ingest.id,
      aws_api_gateway_method.ingest_post.id,
      aws_api_gateway_integration.lambda.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "api" {
  deployment_id = aws_api_gateway_deployment.api.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "prod"

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

resource "aws_api_gateway_api_key" "api_key" {
  name = "${var.project_name}-ingest-api-key"

  tags = {
    Project = var.project_name
    Module  = "3_ingest"
  }
}

resource "aws_api_gateway_usage_plan" "plan" {
  name = "${var.project_name}-ingest-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.api.stage_name
  }

  quota_settings {
    limit  = 10000
    period = "MONTH"
  }

  throttle_settings {
    rate_limit  = 100
    burst_limit = 200
  }
}

resource "aws_api_gateway_usage_plan_key" "plan_key" {
  key_id        = aws_api_gateway_api_key.api_key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.plan.id
}