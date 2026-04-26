# variables.tf defines the "parameters" your module accepts
# Think of these like function arguments in Python

variable "aws_region" {
  description = "us-east-1"
  type        = string
  default     = "us-east-1"             # used if not set in tfvars
}

variable "project_name" {
  description = "aria"
  type        = string
  default     = "aria"
}

variable "aws_account_id" {
  description = "975022060655"
  type        = string
  # No default — must be provided in terraform.tfvars
}