terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "permissions" {
  backend = "local"
  config  = { path = "../1_permissions/terraform.tfstate" }
}

# ── SageMaker IAM role ────────────────────────────────────
resource "aws_iam_role" "sagemaker_role" {
  name = "${var.project_name}-sagemaker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# ── SageMaker model ───────────────────────────────────────
resource "aws_sagemaker_model" "embeddings" {
  name               = "${var.project_name}-embedding-model"
  execution_role_arn = aws_iam_role.sagemaker_role.arn

  primary_container {
    image = var.sagemaker_image_uri

    environment = {
      HF_MODEL_ID = var.embedding_model_name
      HF_TASK     = "feature-extraction"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.sagemaker_full_access]
}

# ── Serverless endpoint configuration ────────────────────
# No instance_type needed — serverless handles scaling
resource "aws_sagemaker_endpoint_configuration" "embeddings" {
  name = "${var.project_name}-embedding-serverless-config"

  production_variants {
    model_name = aws_sagemaker_model.embeddings.name

    serverless_config {
      memory_size_in_mb = 3072   # 3GB — enough for all-MiniLM-L6-v2
      max_concurrency   = 2      # max simultaneous requests
    }
  }
}

# ── Wait for IAM to propagate before creating endpoint ────
# IAM changes take ~10-15 seconds to propagate globally
# Without this wait, the endpoint creation fails
resource "time_sleep" "wait_for_iam" {
  depends_on      = [aws_iam_role_policy_attachment.sagemaker_full_access]
  create_duration = "15s"
}

# ── The actual endpoint ───────────────────────────────────
resource "aws_sagemaker_endpoint" "embeddings" {
  name                 = "${var.project_name}-embedding-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.embeddings.name

  depends_on = [time_sleep.wait_for_iam]

  tags = {
    Project = var.project_name
    Module  = "2_sagemaker"
  }
}