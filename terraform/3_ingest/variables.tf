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

variable "sagemaker_endpoint_name" {
  description = "SageMaker embedding endpoint name from module 2"
  type        = string
  default     = "aria-embedding-endpoint"
}

variable "vector_index_name" {
  description = "Name of the vector index"
  type        = string
  default     = "research-briefs"
}