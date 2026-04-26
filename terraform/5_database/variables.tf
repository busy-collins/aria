variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for all resource names"
  type        = string
  default     = "aria"
}

variable "aws_account_id" {
  description = "Your AWS account ID"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "aria"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "ariaadmin"
}

variable "min_capacity" {
  description = "Minimum Aurora Serverless v2 capacity (ACUs)"
  type        = number
  default     = 0.5
}

variable "max_capacity" {
  description = "Maximum Aurora Serverless v2 capacity (ACUs)"
  type        = number
  default     = 4.0
}