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
data "aws_region" "current" {}

# ── Read outputs from previous modules ────────────────────
data "terraform_remote_state" "database" {
  backend = "local"
  config  = { path = "../5_database/terraform.tfstate" }
}

data "terraform_remote_state" "agents" {
  backend = "local"
  config  = { path = "../6_agents/terraform.tfstate" }
}

data "terraform_remote_state" "ingest" {
  backend = "local"
  config  = { path = "../3_ingest/terraform.tfstate" }
}

# ========================================
# S3 — Frontend Static Files
# ========================================

resource "aws_s3_bucket" "frontend" {
  bucket = "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = var.project_name
    Module  = "7_frontend"
  }
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document { suffix = "index.html" }
  error_document { key    = "404.html" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket     = aws_s3_bucket.frontend.id
  depends_on = [aws_s3_bucket_public_access_block.frontend]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
    }]
  })
}

# ========================================
# IAM — API Lambda Role
# ========================================

resource "aws_iam_role" "api_lambda_role" {
  name = "${var.project_name}-api-lambda-role"

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
    Module  = "7_frontend"
  }
}

resource "aws_iam_role_policy_attachment" "api_lambda_basic" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api_lambda_policy" {
  name = "${var.project_name}-api-lambda-policy"
  role = aws_iam_role.api_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
        Action = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = data.terraform_remote_state.agents.outputs.sqs_queue_arn
      },
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
# API Lambda
# ========================================

locals {
  api_lambda_zip = "${path.module}/api_lambda.zip"
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project_name}-api"
  role             = aws_iam_role.api_lambda_role.arn
  filename         = local.api_lambda_zip
  source_code_hash = fileexists(local.api_lambda_zip) ? filebase64sha256(local.api_lambda_zip) : null
  handler          = "main.handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      AURORA_CLUSTER_ARN    = data.terraform_remote_state.database.outputs.aurora_cluster_arn
      AURORA_SECRET_ARN     = data.terraform_remote_state.database.outputs.aurora_secret_arn
      DATABASE_NAME         = "aria"
      SQS_QUEUE_URL         = data.terraform_remote_state.agents.outputs.sqs_queue_url
      CLERK_JWKS_URL        = var.clerk_jwks_url
      DEFAULT_AWS_REGION    = var.aws_region
      OPENAI_SECRET_NAME    = "aria/openai-api-key"
      LANGSMITH_SECRET_NAME = "aria/langsmith-api-key"
    }
  }

  tags = {
    Project = var.project_name
    Module  = "7_frontend"
  }
}

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/lambda/${var.project_name}-api"
  retention_in_days = 7
}

# ========================================
# API Gateway
# ========================================

resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api-gateway"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["Authorization", "Content-Type"]
    max_age       = 300
  }

  tags = {
    Project = var.project_name
    Module  = "7_frontend"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  tags = {
    Project = var.project_name
    Module  = "7_frontend"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /api/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# ========================================
# CloudFront
# ========================================

locals {
  s3_origin_id  = "S3-${var.project_name}-frontend"
  api_origin_id = "API-Gateway-${var.project_name}"
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "Aria Frontend"

  # Origin 1 — S3 static files
  origin {
    domain_name = aws_s3_bucket_website_configuration.frontend.website_endpoint
    origin_id   = local.s3_origin_id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Origin 2 — API Gateway
  origin {
    domain_name = "${aws_apigatewayv2_api.main.id}.execute-api.${var.aws_region}.amazonaws.com"
    origin_id   = local.api_origin_id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default — serve from S3
  default_cache_behavior {
    target_origin_id       = local.s3_origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    default_ttl = 3600
    min_ttl     = 0
    max_ttl     = 86400
  }

  # /api/* — route to API Gateway (never cached)
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = local.api_origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type"]
      cookies { forward = "all" }
    }

    default_ttl = 0
    min_ttl     = 0
    max_ttl     = 0
  }

  # SPA routing — 404s serve index.html
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Project = var.project_name
    Module  = "7_frontend"
  }
}