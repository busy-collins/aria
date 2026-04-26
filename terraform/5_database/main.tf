terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ── Random password ───────────────────────────────────────
resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_id" "suffix" {
  byte_length = 4
}

# ── Secrets Manager ───────────────────────────────────────
resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project_name}-aurora-credentials-${random_id.suffix.hex}"
  recovery_window_in_days = 0

  tags = {
    Project = var.project_name
    Module  = "5_database"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
  })
}

# ── Networking ────────────────────────────────────────────
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${var.project_name}-aurora-subnet-group"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Project = var.project_name
    Module  = "5_database"
  }
}

resource "aws_security_group" "aurora" {
  name        = "${var.project_name}-aurora-sg"
  description = "Security group for Aria Aurora cluster"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Module  = "5_database"
  }
}

# ── Aurora Serverless v2 Cluster ──────────────────────────
resource "aws_rds_cluster" "aurora" {
  cluster_identifier = "${var.project_name}-aurora-cluster"
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = "15.12"
  database_name      = var.db_name
  master_username    = var.db_username
  master_password    = random_password.db_password.result

  serverlessv2_scaling_configuration {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }

  # Data API — call via HTTP, no VPN needed
  enable_http_endpoint = true

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]

  backup_retention_period      = 7
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"

  skip_final_snapshot = true
  apply_immediately   = true

  tags = {
    Project = var.project_name
    Module  = "5_database"
  }
}

# ── Aurora Instance ───────────────────────────────────────
resource "aws_rds_cluster_instance" "aurora" {
  identifier         = "${var.project_name}-aurora-instance-1"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version

  performance_insights_enabled = false

  tags = {
    Project = var.project_name
    Module  = "5_database"
  }
}